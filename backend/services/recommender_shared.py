import json

from services.song_service import GENRE_COLORS, DEFAULT_COLOR


COMPARISON_FEATURES = [
    "danceability",
    "energy",
    "valence",
    "acousticness",
    "instrumentalness",
    "loudness",
    "speechiness",
    "liveness",
    "tempo",
    "duration_ms",
    "ms_played",
]

FEATURE_WEIGHT_DEFAULTS = {
    "danceability": 1.0,
    "energy": 1.0,
    "valence": 1.0,
    "acousticness": 1.0,
    "instrumentalness": 1.0,
    "loudness": 0.7,
    "speechiness": 0.6,
    "liveness": 0.6,
    "tempo": 0.6,
    "duration_ms": 0.35,
    "ms_played": 0.0,
}

FEATURE_WEIGHT_UI = {
    "danceability": ("Danceability", "How much rhythm and dance feel influences ranking."),
    "energy": ("Energy", "How much intensity and activity matter."),
    "valence": ("Valence", "How much positive or darker mood should drive results."),
    "acousticness": ("Acousticness", "How much acoustic texture should influence recommendations."),
    "instrumentalness": ("Instrumentalness", "How strongly vocal-free tracks should be preferred."),
    "loudness": ("Loudness", "How much loudness contributes to similarity."),
    "speechiness": ("Speechiness", "How much spoken-word character affects ranking."),
    "liveness": ("Liveness", "How much live-performance feel influences ranking."),
    "tempo": ("Tempo", "How strongly BPM similarity should matter."),
    "duration_ms": ("Duration", "How much track length should influence similarity."),
    "ms_played": ("Popularity (msPlayed)", "Default is 0 so popular tracks do not take over."),
}

PREF_TO_FEATURE = {
    "danceability": "pref_danceability",
    "energy": "pref_energy",
    "valence": "pref_valence",
    "acousticness": "pref_acousticness",
    "instrumentalness": "pref_instrumentalness",
}

PERSONALIZED_KEYWORDS = {
    "danceability": ["dance", "groove", "rhythm"],
    "energy": ["energy", "intense", "power", "aggressive"],
    "valence": ["happy", "positive", "uplifting", "sad", "dark", "moody"],
    "acousticness": ["acoustic", "organic", "unplugged"],
    "instrumentalness": ["instrumental", "no vocals", "ambient"],
    "loudness": ["loud", "quiet", "soft"],
    "speechiness": ["spoken", "rap", "lyrics", "vocal"],
    "liveness": ["live", "concert", "stage"],
    "tempo": ["tempo", "bpm", "fast", "slow"],
    "duration_ms": ["short", "long", "duration", "length"],
    "ms_played": ["popular", "mainstream", "trending", "hot"],
}


def cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(x * x for x in vec_a) ** 0.5
    norm_b = sum(x * x for x in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def column_stats(items, columns):
    stats = {}
    for col in columns:
        values = [float(item.get(col, 0.0)) for item in items]
        stats[col] = (min(values), max(values)) if values else (0.0, 1.0)
    return stats


def minmax(value, min_val, max_val):
    if max_val == min_val:
        return 0.0
    return (value - min_val) / (max_val - min_val)


def normalize_score_map(score_map):
    if not score_map:
        return {}
    max_val = max(score_map.values())
    if max_val <= 0:
        return {k: 0.0 for k in score_map}
    return {k: v / max_val for k, v in score_map.items()}


def track_key(track_name, artist_name):
    return (track_name.strip().lower(), artist_name.strip().lower())


def get_feature_weight_values(prefs):
    raw_map = {}
    if prefs and getattr(prefs, "feature_weights", None):
        try:
            raw_map = json.loads(prefs.feature_weights)
        except (TypeError, ValueError):
            raw_map = {}

    values = {}
    for key in COMPARISON_FEATURES:
        raw_value = raw_map.get(key, FEATURE_WEIGHT_DEFAULTS[key])
        try:
            values[key] = max(0.0, min(2.0, float(raw_value)))
        except (TypeError, ValueError):
            values[key] = FEATURE_WEIGHT_DEFAULTS[key]
    return values


def get_feature_weight_controls():
    controls = []
    for key in COMPARISON_FEATURES:
        label, desc = FEATURE_WEIGHT_UI[key]
        controls.append(
            {
                "key": key,
                "label": label,
                "desc": desc,
                "default": FEATURE_WEIGHT_DEFAULTS[key],
            }
        )
    return controls


def duration_label(duration_ms):
    total_seconds = max(0, int(float(duration_ms or 0) / 1000))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def decorate_song(song, score):
    return {
        **song,
        "raw_score": score,
        "match": max(60, min(99, int(score * 100))),
        "color": GENRE_COLORS.get(song["genre"], DEFAULT_COLOR),
        "tempo_bpm": int(round(float(song.get("tempo", 0.0)))),
        "duration_label": duration_label(song.get("duration_ms", 0)),
        "loudness_db": round(float(song.get("loudness", 0.0)), 1),
        "speechiness_pct": int(round(float(song.get("speechiness", 0.0)) * 100)),
        "liveness_pct": int(round(float(song.get("liveness", 0.0)) * 100)),
    }
