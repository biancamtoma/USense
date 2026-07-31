import json
import numpy as np

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
    "danceability": (
        "Campaign Momentum",
        "How much groove and movement should shape campaign alignment.",
    ),
    "energy": (
        "Launch Energy",
        "How much intensity and activation should influence results.",
    ),
    "valence": (
        "Emotional Tone",
        "How much upbeat versus reflective mood should steer recommendations.",
    ),
    "acousticness": (
        "Organic Texture",
        "How much acoustic or natural texture should matter for the brief.",
    ),
    "instrumentalness": (
        "Instrumental Layer",
        "How strongly vocal-free or soundtrack-like tracks should be preferred.",
    ),
    "loudness": ("Presence", "How much sonic punch should contribute to similarity."),
    "speechiness": (
        "Voice Presence",
        "How much spoken-word or lyrical character should affect ranking.",
    ),
    "liveness": (
        "Live Feel",
        "How much live-performance energy should influence ranking.",
    ),
    "tempo": ("Pacing", "How strongly BPM should matter for campaign rhythm."),
    "duration_ms": (
        "Placement Length",
        "How much track length should influence fit for the channel.",
    ),
    "ms_played": (
        "Audience Pull",
        "Default is 0 so popularity does not overpower campaign fit.",
    ),
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
    zipped = [(a, b) for a, b in zip(vec_a, vec_b) if a is not None and b is not None]
    if not zipped:
        return 0.0
    dot = sum(a * b for a, b in zipped)
    norm_a = sum(a * a for a, _ in zipped) ** 0.5
    norm_b = sum(b * b for _, b in zipped) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def column_stats(items, columns):
    stats = {}
    for col in columns:
        values = [float(item[col]) for item in items if item.get(col) is not None]
        if not values:
            stats[col] = (0.0, 1.0)
        else:
            # Use 5th and 95th percentiles instead of absolute min/max to avoid outlier influence
            stats[col] = (
                float(np.percentile(values, 5)),
                float(np.percentile(values, 95)),
            )
    return stats


def minmax(value, min_val, max_val):
    if value is None:
        return None
    if max_val == min_val:
        return 0.0
    # Clip the value to our robust bounds so outliers don't break the [0, 1] range
    clipped_value = max(min_val, min(value, max_val))
    return (clipped_value - min_val) / (max_val - min_val)


def normalize_score_map(score_map):
    if not score_map:
        return {}
    max_val = max(score_map.values())
    if max_val <= 0:
        return {k: 0.0 for k in score_map}
    return {k: v / max_val for k, v in score_map.items()}


def track_key(track_name, artist_name):
    return f"{track_name.strip().lower()}|||{artist_name.strip().lower()}"


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


def _extract_track_id(song):
    url = song.get("spotify_url", "") or ""
    if "/track/" in url:
        return url.split("/track/")[-1].split("?")[0].strip()
    return ""


def decorate_song(song, score, behavioral_fit=None, match_pct=None):
    track_id = _extract_track_id(song)
    if match_pct is not None:
        display_match = max(1, min(99, int(round(match_pct))))
    else:
        display_match = max(1, min(99, int(score * 100)))

    return {
        **song,
        "raw_score": score,
        "match": display_match,
        "behavioral_fit": (
            int(round(behavioral_fit * 100)) if behavioral_fit is not None else None
        ),
        "color": GENRE_COLORS.get(song["genre"], DEFAULT_COLOR),
        "tempo_bpm": int(round(float(song.get("tempo") or 0.0))),
        "duration_label": duration_label(song.get("duration_ms") or 0),
        "loudness_db": round(float(song.get("loudness") or 0.0), 1),
        "speechiness_pct": int(round(float(song.get("speechiness") or 0.0) * 100)),
        "liveness_pct": int(round(float(song.get("liveness") or 0.0) * 100)),
        "spotify_embed_url": (
            f"https://open.spotify.com/embed/track/{track_id}?utm_source=generator&theme=0"
            if track_id
            else ""
        ),
    }
