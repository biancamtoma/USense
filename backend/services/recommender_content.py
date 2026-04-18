from models.database import FavoriteRecommendation
from services.song_service import ALL_SONGS, get_saved_genres

from services.recommender_shared import (
    COMPARISON_FEATURES,
    PERSONALIZED_KEYWORDS,
    PREF_TO_FEATURE,
    column_stats,
    cosine_similarity,
    decorate_song,
    get_feature_weight_values,
    minmax,
    track_key,
)


def _effective_feature_weights(prefs):
    weights = get_feature_weight_values(prefs)
    if not prefs or not getattr(prefs, "enable_personalized_similarity", False):
        return weights

    text = (getattr(prefs, "personalized_similarity_text", "") or "").lower().strip()
    if not text:
        return weights

    for feature, keywords in PERSONALIZED_KEYWORDS.items():
        hits = sum(1 for token in keywords if token in text)
        if hits:
            weights[feature] = min(2.0, weights[feature] + 0.2 * hits)
    return weights


def _interaction_target_vector(prefs, candidates, feature_stats, feature_weights):
    if not prefs or not getattr(prefs, "use_interaction_signal", False):
        return None

    favorite_rows = FavoriteRecommendation.query.filter_by(user_id=prefs.user_id).all()
    if not favorite_rows:
        return None

    by_key = {track_key(song["trackName"], song["artistName"]): song for song in candidates}

    vectors = []
    for item in favorite_rows:
        key = track_key(item.track_name, item.artist_name)
        song = by_key.get(key)
        if not song:
            continue

        vec = []
        for feature in COMPARISON_FEATURES:
            min_val, max_val = feature_stats[feature]
            raw_value = float(song.get(feature, 0.0))
            vec.append(minmax(raw_value, min_val, max_val) * feature_weights[feature])
        vectors.append(vec)

    if not vectors:
        return None

    return [sum(col) / len(vectors) for col in zip(*vectors)]


def get_recommendations(prefs=None, n=9):
    if not ALL_SONGS:
        return []

    pool = ALL_SONGS
    saved_genres = get_saved_genres(prefs)
    use_genre_boost = bool(prefs and getattr(prefs, "enable_genre_boost", False))
    if saved_genres and not use_genre_boost:
        pool = [song for song in pool if song["genre"] in saved_genres]

    deduped = {}
    for song in pool:
        key = track_key(song["trackName"], song["artistName"])
        if key not in deduped:
            deduped[key] = song
    candidates = list(deduped.values())

    feature_stats = column_stats(candidates, COMPARISON_FEATURES)
    feature_weights = _effective_feature_weights(prefs)

    target = []
    for feature in COMPARISON_FEATURES:
        pref_name = PREF_TO_FEATURE.get(feature)
        if pref_name:
            pref_value = getattr(prefs, pref_name, None) if prefs else None
            if pref_value is None:
                pref_value = 0.0 if feature == "instrumentalness" else 0.5
            target_value = max(0.0, min(1.0, float(pref_value)))
        else:
            min_val, max_val = feature_stats[feature]
            avg_val = sum(float(song.get(feature, 0.0)) for song in candidates) / len(candidates)
            target_value = minmax(avg_val, min_val, max_val)
        target.append(target_value * feature_weights[feature])

    interaction_target = _interaction_target_vector(prefs, candidates, feature_stats, feature_weights)
    if interaction_target is not None:
        blend = max(0.0, min(0.8, float(getattr(prefs, "interaction_blend", 0.25) or 0.25)))
        target = [
            ((1.0 - blend) * base_val) + (blend * interaction_val)
            for base_val, interaction_val in zip(target, interaction_target)
        ]

    genre_boost_weight = (
        float(max(1, min(3, int(round(float(getattr(prefs, "genre_boost_weight", 1.0) or 1.0))))))
        if use_genre_boost
        else 1.0
    )

    def score(song):
        song_vec = []
        for feature in COMPARISON_FEATURES:
            min_val, max_val = feature_stats[feature]
            raw_value = float(song.get(feature, 0.0))
            song_vec.append(minmax(raw_value, min_val, max_val) * feature_weights[feature])
        value = cosine_similarity(song_vec, target)
        if use_genre_boost and saved_genres and song.get("genre") in saved_genres:
            value *= genre_boost_weight
        return value

    ranked = sorted(candidates, key=score, reverse=True)

    result = []
    artist_counts = {}
    for song in ranked:
        artist_key = song["artistName"].strip().lower()
        if artist_counts.get(artist_key, 0) >= 2:
            continue

        result.append(decorate_song(song, score(song)))
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        if len(result) >= n:
            break

    result.sort(key=lambda item: item["raw_score"], reverse=True)
    return result
