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
from services.vector_mapping import (
    get_generation_vector,
    get_industry_vector,
    get_campaign_vector,
)


# Module-level cache for column_stats — ALL_SONGS is immutable at runtime
_COLUMN_STATS_CACHE = None


def _cached_column_stats():
    global _COLUMN_STATS_CACHE
    if _COLUMN_STATS_CACHE is None:
        _COLUMN_STATS_CACHE = column_stats(ALL_SONGS, COMPARISON_FEATURES)
    return _COLUMN_STATS_CACHE


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

    by_key = {
        track_key(song["trackName"], song["artistName"]): song for song in candidates
    }

    vectors = []
    for item in favorite_rows:
        key = track_key(item.track_name, item.artist_name)
        song = by_key.get(key)
        if not song:
            continue

        vec = []
        for feature in COMPARISON_FEATURES:
            min_val, max_val = feature_stats[feature]
            raw_value = song.get(feature)
            if raw_value is None:
                vec.append(None)
            else:
                vec.append(
                    minmax(float(raw_value), min_val, max_val)
                    * feature_weights[feature]
                )
        vectors.append(vec)

    if not vectors:
        return None

    avg_vec = []
    for col in zip(*vectors):
        valid_vals = [v for v in col if v is not None]
        if valid_vals:
            avg_vec.append(sum(valid_vals) / len(valid_vals))
        else:
            avg_vec.append(0.5)
    return avg_vec


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

    feature_stats = _cached_column_stats()
    feature_weights = _effective_feature_weights(prefs)

    slider_target = []
    for feature in COMPARISON_FEATURES:
        pref_name = PREF_TO_FEATURE.get(feature)
        if pref_name:
            pref_value = getattr(prefs, pref_name, None) if prefs else None
            if pref_value is None:
                pref_value = 0.0 if feature == "instrumentalness" else 0.5
            target_value = max(0.0, min(1.0, float(pref_value)))
        else:
            min_val, max_val = feature_stats[feature]
            valid_vals = [
                float(song[feature])
                for song in candidates
                if song.get(feature) is not None
            ]
            avg_val = sum(valid_vals) / len(valid_vals) if valid_vals else 0.5
            target_value = minmax(avg_val, min_val, max_val)
        slider_target.append(target_value * feature_weights[feature])

    interaction_target = _interaction_target_vector(
        prefs, candidates, feature_stats, feature_weights
    )
    if interaction_target is not None:
        feedback_weight = max(
            0.55, min(0.9, float(getattr(prefs, "interaction_blend", 0.65) or 0.65))
        )
        target = [
            (feedback_weight * interaction_val) + ((1.0 - feedback_weight) * slider_val)
            for slider_val, interaction_val in zip(slider_target, interaction_target)
        ]
    else:
        target = slider_target

    genre_boost_weight = (
        float(
            max(
                1,
                min(
                    3,
                    int(round(float(getattr(prefs, "genre_boost_weight", 1.0) or 1.0))),
                ),
            )
        )
        if use_genre_boost
        else 1.0
    )

    # Pre-compute target vectors and weights ONCE outside the per-song loop
    industry = getattr(prefs, "industry_focus", "other") if prefs else "other"
    generation = getattr(prefs, "target_generation", "") if prefs else ""
    campaign = getattr(prefs, "target_campaign", "") if prefs else ""

    w_base = getattr(prefs, "weight_base_audio", 0.40) if prefs else 0.40
    w_ind = getattr(prefs, "weight_industry", 0.20) if prefs else 0.20
    w_gen = getattr(prefs, "weight_generation", 0.20) if prefs else 0.20
    w_camp = getattr(prefs, "weight_campaign", 0.20) if prefs else 0.20

    total_w = w_base + w_ind + w_gen + w_camp
    if total_w == 0:
        total_w = 1.0
        w_base = 1.0

    ind_target = None
    if industry:
        ind_target = [
            val * feature_weights[f]
            for f, val in zip(COMPARISON_FEATURES, get_industry_vector(industry))
        ]

    gen_target = None
    if generation:
        gen_target = [
            val * feature_weights[f]
            for f, val in zip(COMPARISON_FEATURES, get_generation_vector(generation))
        ]

    camp_target = None
    if campaign:
        camp_target = [
            val * feature_weights[f]
            for f, val in zip(COMPARISON_FEATURES, get_campaign_vector(campaign))
        ]

    # Pre-extract feature stats tuples for inner loop speed
    _fs_tuples = [(feature, feature_stats[feature], feature_weights[feature]) for feature in COMPARISON_FEATURES]
    _saved_genres_set = set(saved_genres) if use_genre_boost and saved_genres else None

    def score(song):
        song_vec = []
        for feature, (min_val, max_val), fw in _fs_tuples:
            raw_value = song.get(feature)
            if raw_value is None:
                song_vec.append(None)
            else:
                song_vec.append(
                    minmax(float(raw_value), min_val, max_val) * fw
                )

        # 1. Base Audio Match
        base_fit = cosine_similarity(song_vec, target)

        # 2. Industry Match
        ind_fit = cosine_similarity(song_vec, ind_target) if ind_target else base_fit

        # 3. Generation Match
        gen_fit = cosine_similarity(song_vec, gen_target) if gen_target else base_fit

        # 4. Campaign Match
        camp_fit = cosine_similarity(song_vec, camp_target) if camp_target else base_fit

        # Overall Fitness
        overall_fitness = (
            (base_fit * w_base)
            + (ind_fit * w_ind)
            + (gen_fit * w_gen)
            + (camp_fit * w_camp)
        ) / total_w

        if _saved_genres_set and song.get("genre") in _saved_genres_set:
            overall_fitness *= genre_boost_weight

        # Attach the independent scores to the song dict so we can use them later if needed
        song["_fitness_base"] = base_fit
        song["_fitness_ind"] = ind_fit
        song["_fitness_gen"] = gen_fit
        song["_fitness_camp"] = camp_fit
        song["_fitness_overall"] = overall_fitness

        return overall_fitness

    # Score all candidates and sort
    scored = [(score(song), song) for song in candidates]
    scored.sort(key=lambda item: item[0], reverse=True)

    result = []
    artist_counts = {}
    for s, song in scored:
        artist_key = song["artistName"].strip().lower()
        if artist_counts.get(artist_key, 0) >= 2:
            continue

        result.append(decorate_song(song, s, match_pct=s * 100))
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        if len(result) >= n:
            break

    result.sort(key=lambda item: item["raw_score"], reverse=True)
    return result
