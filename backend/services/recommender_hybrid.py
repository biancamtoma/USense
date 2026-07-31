from sqlalchemy import func
from models.database import (
    db,
    FavoriteRecommendation,
    FriendRequest,
    User,
    UserPreferences,
    RoomReaction,
    RoomEvent,
)
from services.recommender_content import get_recommendations, _cached_column_stats
from services.recommender_shared import (
    COMPARISON_FEATURES,
    cosine_similarity,
    decorate_song,
    normalize_score_map,
    track_key,
    minmax,
    column_stats,
)
from services.song_service import ALL_SONGS


def _pref_value(prefs, key, default):
    value = getattr(prefs, key, None) if prefs else None
    if value is None:
        return default
    return value


def _prefs_vector(prefs):
    return [
        _pref_value(prefs, "pref_danceability", 0.5),
        _pref_value(prefs, "pref_energy", 0.5),
        _pref_value(prefs, "pref_valence", 0.5),
        _pref_value(prefs, "pref_acousticness", 0.5),
        _pref_value(prefs, "pref_instrumentalness", 0.0),
    ]


def _preference_similarity(current_prefs, other_prefs):
    return cosine_similarity(_prefs_vector(current_prefs), _prefs_vector(other_prefs))


def _accepted_collaborator_ids(user_id):
    links = FriendRequest.query.filter(
        FriendRequest.status == "accepted",
        ((FriendRequest.sender_id == user_id) | (FriendRequest.receiver_id == user_id)),
    ).all()
    collaborator_ids = set()
    for item in links:
        collaborator_ids.add(
            item.receiver_id if item.sender_id == user_id else item.sender_id
        )
    return collaborator_ids


def _hot_saved_track_scores():
    rows = (
        FavoriteRecommendation.query.with_entities(
            FavoriteRecommendation.track_name,
            FavoriteRecommendation.artist_name,
            func.count(FavoriteRecommendation.id).label("save_count"),
        )
        .group_by(FavoriteRecommendation.track_name, FavoriteRecommendation.artist_name)
        .all()
    )

    hot = {}
    for track_name, artist_name, save_count in rows:
        hot[track_key(track_name, artist_name)] = float(save_count)
    return normalize_score_map(hot)


import math
import numpy as np
from services.recommender_shared import get_feature_weight_values

import math
import numpy as np
from services.recommender_shared import get_feature_weight_values

# Global in-memory neighbor cache to prevent database bottlenecks on User.query
_NEIGHBOR_CACHE = {}


def cluster_liked_vectors(vectors_with_weights, max_clusters=3):
    """
    Groups liked vectors into up to max_clusters centroids.
    Each element in vectors_with_weights is (vector, weight).
    Returns a list of (centroid_vector, cluster_weight) tuples.
    Uses Spherical/Cosine K-Means alignment by normalizing centroids to unit length.
    """
    if not vectors_with_weights:
        return []

    # Filter out empty or None-heavy vectors, fill None with 0.5
    processed = []
    for vec, w in vectors_with_weights:
        clean_vec = [v if v is not None else 0.5 for v in vec]
        # Normalize processing to unit vector for Cosine K-Means alignment
        arr = np.array(clean_vec)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        processed.append((arr, w))

    n_samples = len(processed)
    if n_samples <= max_clusters:
        # Each liked song is its own centroid
        return [([float(x) for x in vec], w) for vec, w in processed]

    # K-Means clustering (using numpy)
    X = np.array([item[0] for item in processed])  # shape (n_samples, n_features)
    weights = np.array([item[1] for item in processed])

    # Deteministic initialization: pick the first max_clusters elements (newest)
    centroids = X[:max_clusters]

    for _ in range(10):  # 10 iterations are plenty for small catalog clustering
        # Assign to nearest centroid (Euclidean distance on normalized sphere aligns with Cosine similarity)
        dists = np.linalg.norm(
            X[:, np.newaxis] - centroids, axis=2
        )  # shape (n_samples, max_clusters)
        labels = np.argmin(dists, axis=1)

        new_centroids = []
        for c in range(max_clusters):
            mask = labels == c
            if np.any(mask):
                # Weighted average for centroid smoothing
                c_weights = weights[mask]
                c_vectors = X[mask]
                weighted_sum = np.sum(c_vectors * c_weights[:, np.newaxis], axis=0)
                sum_weights = np.sum(c_weights)
                centroid_val = weighted_sum / (sum_weights if sum_weights > 0 else 1.0)

                # Spherical Normalization for Cosine K-Means alignment
                norm = np.linalg.norm(centroid_val)
                if norm > 0:
                    centroid_val = centroid_val / norm
                new_centroids.append(centroid_val)
            else:
                # Deterministic fallback to first sample if empty
                new_centroids.append(X[0])
        centroids = np.array(new_centroids)

    cluster_weights = np.zeros(max_clusters)
    dists = np.linalg.norm(X[:, np.newaxis] - centroids, axis=2)
    labels = np.argmin(dists, axis=1)

    for idx, c in enumerate(labels):
        cluster_weights[c] += weights[idx]

    results = []
    for c in range(max_clusters):
        if cluster_weights[c] > 0:
            results.append(
                ([float(x) for x in centroids[c]], float(cluster_weights[c]))
            )

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def weighted_cosine_similarity(vec_a, vec_b, feature_weights):
    """Calculates cosine similarity focusing on robust features and suppressing noisy features."""
    zipped = []
    for a, b, feat in zip(vec_a, vec_b, COMPARISON_FEATURES):
        if a is not None and b is not None:
            w = feature_weights.get(feat, 1.0)
            zipped.append((a * w, b * w))

    if not zipped:
        return 0.0
    dot = sum(a * b for a, b in zipped)
    norm_a = sum(a * a for a, _ in zipped) ** 0.5
    norm_b = sum(b * b for _, b in zipped) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_team_liked_vectors(user_id, room_id=None):
    """Retrieve normalized vectors of tracks liked/reacted positively by the team with recency decay."""
    pos_emojis = {"👍", "🔥", "💎", "🎯"}
    neg_emojis = {"👎", "❌"}

    # Retrieve approvals chronologically
    q_app = RoomEvent.query.filter_by(event_type="approve")
    if room_id:
        q_app = q_app.filter_by(room_id=room_id)
    approvals = q_app.order_by(RoomEvent.created_at.desc()).all()

    # Retrieve reactions chronologically
    q_re = RoomReaction.query
    if room_id:
        q_re = q_re.filter_by(room_id=room_id)
    reactions = q_re.order_by(RoomReaction.created_at.desc()).all()

    events = []
    for ev in approvals:
        if ev.track_key:
            events.append((ev.track_key, ev.created_at, "liked"))
    for r in reactions:
        if r.emoji in pos_emojis:
            events.append((r.track_key, r.created_at, "liked"))
        elif r.emoji in neg_emojis:
            events.append((r.track_key, r.created_at, "hated"))

    # Sort all by created_at desc (newest first)
    events.sort(key=lambda x: x[1], reverse=True)

    hated_keys = set()
    liked_keys = []
    seen_liked = set()
    for tk, _, action in events:
        if action == "hated":
            hated_keys.add(tk)
        elif action == "liked":
            if tk not in seen_liked and tk not in hated_keys:
                seen_liked.add(tk)
                liked_keys.append(tk)

    # Limit memory to last N=30 likes
    liked_keys = liked_keys[:30]

    if not liked_keys:
        return [], hated_keys

    by_key = {track_key(s["trackName"], s["artistName"]): s for s in ALL_SONGS}
    stats = _cached_column_stats()

    vectors_with_weights = []
    tau = 10.0  # decay constant
    for idx, key in enumerate(liked_keys):
        song = by_key.get(key)
        if not song:
            continue

        vec = []
        for feat in COMPARISON_FEATURES:
            v = song.get(feat)
            if v is None:
                vec.append(None)
            else:
                mn, mx = stats[feat]
                vec.append(minmax(float(v), mn, mx))

        weight = math.exp(-idx / tau)
        vectors_with_weights.append((vec, weight))

    return vectors_with_weights, hated_keys


def _knn_team_score(song, stats, centroids, feature_weights):
    """Scoring: positive similarity to centroid profiles with cluster weighting and top-centroid diversity penalty."""
    cand_vec = []
    for feat in COMPARISON_FEATURES:
        v = song.get(feat)
        if v is None:
            cand_vec.append(None)
        else:
            mn, mx = stats[feat]
            cand_vec.append(minmax(float(v), mn, mx))

    score = 0.0
    if centroids:
        # Centroid Smoothing: calculate similarity against each centroid using weighted cosine similarity
        sims = [
            weighted_cosine_similarity(cand_vec, centroid, feature_weights)
            for centroid, _ in centroids
        ]

        # Use cluster importance weights (c_w) directly in scoring instead of harmonic ranking
        weighted_sum = 0.0
        sum_weights = 0.0
        for sim, (_, c_w) in zip(sims, centroids):
            weighted_sum += sim * c_w
            sum_weights += c_w

        score = weighted_sum / sum_weights if sum_weights > 0 else 0.0

        # Better Diversity Penalty: penalize similarity strictly against the top (dominant) centroid to preserve secondary tastes
        top_sim = sims[0] if sims else 0.0
        score = max(0.0, score - 0.15 * top_sim)

    return score


def get_hybrid_recommendations(user, prefs=None, n=10):
    content_recs = get_recommendations(prefs, n=max(60, n * 4))
    if not content_recs:
        return []

    base_by_key = {
        track_key(song["trackName"], song["artistName"]): song for song in content_recs
    }
    content_scores = {
        key: max(0.0, float(song.get("raw_score", 0.0)))
        for key, song in base_by_key.items()
    }

    collaborative_scores = {key: 0.0 for key in base_by_key}
    if user:
        # High-performance O(1) in-memory neighbor query caching
        cache_key = (user.id, len(ALL_SONGS))
        global _NEIGHBOR_CACHE

        if cache_key in _NEIGHBOR_CACHE:
            neighbors = _NEIGHBOR_CACHE[cache_key]
        else:
            prefs_map = {item.user_id: item for item in UserPreferences.query.all()}
            collaborator_ids = _accepted_collaborator_ids(user.id)

            # Soft similarity weighting (no hard 0.3 threshold) to optimize recall
            neighbors = []
            for candidate in User.query.limit(
                50
            ).all():  # Performance limit to avoid database bottlenecks
                if candidate.id == user.id:
                    continue
                if candidate.username == "demo.supervisor@gmail.com":
                    continue
                candidate_prefs = prefs_map.get(candidate.id)
                similarity = _preference_similarity(prefs, candidate_prefs)
                if similarity > 0.0:  # Include all soft-correlated neighbors
                    relation_boost = 1.15 if candidate.id in collaborator_ids else 1.0
                    neighbors.append((similarity * relation_boost, candidate_prefs))

            neighbors.sort(key=lambda x: x[0], reverse=True)
            neighbors = neighbors[:5]  # Cache only the top 5 closest neighbors
            _NEIGHBOR_CACHE[cache_key] = neighbors

        for neighbor_weight, neighbor_prefs in neighbors:
            for rec in get_recommendations(neighbor_prefs, n=8):
                key = track_key(rec["trackName"], rec["artistName"])
                if key not in collaborative_scores:
                    continue
                collaborative_scores[key] += neighbor_weight * max(
                    0.0, float(rec.get("raw_score", 0.0))
                )

    collaborative_scores = normalize_score_map(collaborative_scores)
    room_id = getattr(prefs, "room_id", None)
    res = _get_team_liked_vectors(user.id, room_id=room_id) if user else ([], set())
    liked_vectors, hated_keys = res
    stats = _cached_column_stats()
    feature_weights = get_feature_weight_values(prefs)

    # Multi-taste Clustering to compute centroids (Deterministic Spherical K-Means)
    centroids = cluster_liked_vectors(liked_vectors, max_clusters=3)

    # Sigmoid alpha scaling curve for confidence saturation
    alpha = 0.6 * (1.0 - math.exp(-len(liked_vectors) / 10.0))

    hot_scores = _hot_saved_track_scores()
    ms_stats = stats.get("ms_played", (0, 1000000))

    # Cold-Start Warm Fallback: if collaborative neighborhood fails, gracefully fallback to trend hotness
    if sum(collaborative_scores.values()) == 0.0:
        collaborative_scores = hot_scores

    # Extract user's liked artists list for retention predictor features
    liked_artists = set()
    if user:
        try:
            favorites = FavoriteRecommendation.query.filter_by(user_id=user.id).all()
            for f in favorites:
                if f.artist_name:
                    liked_artists.add(f.artist_name.strip().lower())
        except Exception:
            pass

    from services.retention_predictor import predict_ad_completion_probability

    # 4-Layer Normalized Ranking Blend (Clean separation of signals) or 70/30 Logistic Blend for campaigns
    ranked = []
    for key, song in base_by_key.items():
        if key in hated_keys:
            continue

        # 1. Content component (Brief fit)
        brief_score = content_scores.get(key, 0.0)

        # 2. Behavioral component (Curation fit)
        knn_score = _knn_team_score(song, stats, centroids, feature_weights)

        # 3. Collaborative component (Neighbor overlap)
        collab_score = collaborative_scores.get(key, 0.0)

        # 4. Popularity component (Trend fit)
        ms_p = float(song.get("ms_played", 0.0))
        intrinsic_pop = minmax(ms_p, ms_stats[0], ms_stats[1])
        app_hotness = hot_scores.get(key, 0.0)
        pop_score = (intrinsic_pop * 0.7) + (app_hotness * 0.3)

        # Calculate ad completion probability using the logistic model
        completion_prob = predict_ad_completion_probability(
            song, prefs, brief_score, liked_artists
        )

        # Check if we are in a campaign room context
        is_campaign = prefs is not None and getattr(prefs, "room_id", None) is not None

        if is_campaign:
            # 70/30 Blend: 0.7 * cosine_similarity + 0.3 * logistic_probability
            final_score = 0.7 * brief_score + 0.3 * completion_prob
        else:
            # Mathematically clear blending with partition weight normalization
            w_brief = 0.85 * (1.0 - alpha)
            w_behavioral = 0.85 * alpha
            w_collab = 0.10
            w_pop = 0.05

            final_score = (
                w_brief * brief_score
                + w_behavioral * knn_score
                + w_collab * collab_score
                + w_pop * pop_score
            )

            # Uncertainty-scaled exploration noise (calibrated to score density)
            exploration_noise = np.random.normal(0, 0.01 * (1.0 - final_score))
            final_score = max(0.0, min(1.0, final_score + exploration_noise))

        ranked.append((final_score, song, knn_score, completion_prob))

    ranked.sort(key=lambda item: item[0], reverse=True)

    result = []
    artist_counts = {}
    for final_score, song, s_knn, completion_prob in ranked:
        artist_key = song["artistName"].strip().lower()
        if artist_counts.get(artist_key, 0) >= 2:
            continue

        decorated = decorate_song(
            song,
            final_score,
            behavioral_fit=s_knn,
            match_pct=final_score * 100,
        )
        decorated["ad_completion_probability"] = int(round(completion_prob * 100))

        result.append(decorated)
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        if len(result) >= n:
            break

    return result
