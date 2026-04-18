from sqlalchemy import func

from models.database import FavoriteRecommendation, FriendRequest, User, UserPreferences
from services.recommender_content import get_recommendations
from services.recommender_shared import cosine_similarity, decorate_song, normalize_score_map, track_key


def _prefs_vector(prefs):
    return [
        getattr(prefs, "pref_danceability", 0.5) if prefs else 0.5,
        getattr(prefs, "pref_energy", 0.5) if prefs else 0.5,
        getattr(prefs, "pref_valence", 0.5) if prefs else 0.5,
        getattr(prefs, "pref_acousticness", 0.5) if prefs else 0.5,
        getattr(prefs, "pref_instrumentalness", 0.0) if prefs else 0.0,
    ]


def _preference_similarity(current_prefs, other_prefs):
    return cosine_similarity(_prefs_vector(current_prefs), _prefs_vector(other_prefs))


def _accepted_friend_ids(user_id):
    links = FriendRequest.query.filter(
        FriendRequest.status == "accepted",
        ((FriendRequest.sender_id == user_id) | (FriendRequest.receiver_id == user_id)),
    ).all()
    friend_ids = set()
    for item in links:
        friend_ids.add(item.receiver_id if item.sender_id == user_id else item.sender_id)
    return friend_ids


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


def get_hybrid_recommendations(user, prefs=None, n=9):
    content_recs = get_recommendations(prefs, n=max(60, n * 4))
    if not content_recs:
        return []

    base_by_key = {track_key(song["trackName"], song["artistName"]): song for song in content_recs}
    content_scores = {
        key: max(0.0, float(song.get("raw_score", 0.0)))
        for key, song in base_by_key.items()
    }

    collaborative_scores = {key: 0.0 for key in base_by_key}
    if user:
        prefs_map = {item.user_id: item for item in UserPreferences.query.all()}
        friend_ids = _accepted_friend_ids(user.id)

        for candidate in User.query.order_by(User.id.asc()).all():
            if candidate.id == user.id:
                continue

            candidate_prefs = prefs_map.get(candidate.id)
            similarity = _preference_similarity(prefs, candidate_prefs)
            if similarity <= 0:
                continue

            relation_boost = 1.15 if candidate.id in friend_ids else 1.0
            neighbor_weight = similarity * relation_boost

            for rec in get_recommendations(candidate_prefs, n=8):
                key = track_key(rec["trackName"], rec["artistName"])
                if key not in collaborative_scores:
                    continue
                collaborative_scores[key] += neighbor_weight * max(0.0, float(rec.get("raw_score", 0.0)))

    collaborative_scores = normalize_score_map(collaborative_scores)
    hot_scores = _hot_saved_track_scores()

    w_content = 0.82
    w_collab = 0.13
    w_hot = 0.05

    ranked = []
    for key, song in base_by_key.items():
        final_score = (
            w_content * content_scores.get(key, 0.0)
            + w_collab * collaborative_scores.get(key, 0.0)
            + w_hot * hot_scores.get(key, 0.0)
        )
        ranked.append((final_score, song))

    ranked.sort(key=lambda item: item[0], reverse=True)

    result = []
    artist_counts = {}
    for final_score, song in ranked:
        artist_key = song["artistName"].strip().lower()
        if artist_counts.get(artist_key, 0) >= 2:
            continue

        result.append(decorate_song(song, final_score))
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        if len(result) >= n:
            break

    return result
