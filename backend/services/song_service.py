import csv
import json
import os
import colorsys

CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "Spotify_Song_Attributes.csv"
)
DEFAULT_COLOR = "#64748b"

PREFERENCE_FEATURES = (
    "danceability",
    "energy",
    "valence",
    "acousticness",
    "instrumentalness",
)
PREFERENCE_FEATURE_UI = {
    "danceability": (
        "Campaign Momentum",
        "How much groove and movement should shape campaign fit.",
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
}


def _spotify_track_url(row):
    track_id = (row.get("id") or "").strip()
    if track_id:
        return f"https://open.spotify.com/track/{track_id}"

    uri = (row.get("uri") or "").strip()
    if uri.startswith("spotify:track:"):
        return f"https://open.spotify.com/track/{uri.split(':')[-1]}"

    return (row.get("track_href") or "").strip()


def _build_genre_color(genre):
    if not genre:
        return DEFAULT_COLOR
    index = ALL_GENRES.index(genre) if genre in ALL_GENRES else 0
    hue = (index * 137.508) % 360 / 360.0
    saturation = 0.72
    lightness = 0.48
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    red = int(red * 255)
    green = int(green * 255)
    blue = int(blue * 255)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _build_genre_colors(genres):
    return {genre: _build_genre_color(genre) for genre in genres}


def _build_audio_features(columns):
    features = []
    for feature in PREFERENCE_FEATURES:
        if feature not in columns:
            continue
        label, desc = PREFERENCE_FEATURE_UI[feature]
        features.append({"key": f"pref_{feature}", "label": label, "desc": desc})
    return features


def _load_csv():
    raw_rows = []
    columns = []

    if not os.path.exists(CSV_PATH):
        return [], []

    try:
        with open(CSV_PATH, encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            for r in reader:
                raw_rows.append(r)
    except Exception:
        return [], []

    # 1. First Pass: Compute Medians and Artist Genres
    import statistics
    from collections import Counter

    tempos = []
    durations = []
    loudnesses = []
    artist_genres = {}

    for r in raw_rows:
        artist = (r.get("artistName") or "").strip().lower()
        genre = (r.get("genre") or "").strip()

        # Track artist genres
        if artist and genre:
            artist_genres.setdefault(artist, []).append(genre)

        # Track valid numeric values for median calculation
        try:
            t_val = r.get("tempo")
            if t_val:
                t = float(t_val)
                if t > 0:
                    tempos.append(t)
        except (ValueError, TypeError):
            pass

        try:
            dur_val = r.get("duration_ms") or r.get("msPlayed")
            if dur_val:
                dur = float(dur_val)
                if dur > 0:
                    durations.append(dur)
        except (ValueError, TypeError):
            pass

        try:
            loud_val = r.get("loudness")
            if loud_val:
                loud = float(loud_val)
                loudnesses.append(loud)
        except (ValueError, TypeError):
            pass

    # Compute actual medians or standard defaults
    med_tempo = statistics.median(tempos) if tempos else 119.82
    med_duration = int(statistics.median(durations)) if durations else 194286
    med_loudness = statistics.median(loudnesses) if loudnesses else -7.218

    # Compute artist mode genres (most frequent non-empty genre per artist)
    artist_modes = {}
    for artist, g_list in artist_genres.items():
        if g_list:
            most_common = Counter(g_list).most_common(1)[0][0]
            artist_modes[artist] = most_common

    # 2. Second Pass: Filter, De-duplicate, Impute, and Standardize
    songs = []
    seen_tracks = set()  # (trackName_lower, artistName_lower)

    for r in raw_rows:
        try:
            track_name = (r.get("trackName") or "").strip()
            artist_name = (r.get("artistName") or "").strip()
            if not track_name or not artist_name:
                continue

            track_url = _spotify_track_url(r)
            if not track_url:
                continue

            # De-duplication key
            dup_key = (track_name.lower(), artist_name.lower())
            if dup_key in seen_tracks:
                continue

            # Check if all major audio features are missing/NaN
            # If danceability, energy, and valence are all missing, skip the track (it lacks fingerprint)
            if (
                not r.get("danceability")
                and not r.get("energy")
                and not r.get("valence")
            ):
                continue

            # Helper to parse and clip audio features to [0.0, 1.0]
            def parse_audio_feature(val):
                if val is None or str(val).strip() == "":
                    return None
                try:
                    parsed = float(val)
                    return max(0.0, min(1.0, parsed))
                except (ValueError, TypeError):
                    return None

            danceability = parse_audio_feature(r.get("danceability"))
            energy = parse_audio_feature(r.get("energy"))
            valence = parse_audio_feature(r.get("valence"))
            acousticness = parse_audio_feature(r.get("acousticness"))
            instrumentalness = parse_audio_feature(r.get("instrumentalness"))
            speechiness = parse_audio_feature(r.get("speechiness"))
            liveness = parse_audio_feature(r.get("liveness"))

            # Tempo parsing & imputation
            try:
                t_val = r.get("tempo")
                if t_val is None or str(t_val).strip() == "":
                    tempo = None
                else:
                    tempo = float(t_val)
                    if tempo <= 0:
                        tempo = None
            except (ValueError, TypeError):
                tempo = None

            # Loudness parsing & imputation
            try:
                loud_val = r.get("loudness")
                if loud_val is None or str(loud_val).strip() == "":
                    loudness = None
                else:
                    loudness = float(loud_val)
                    # Clip loudness to standard decibel bounds
                    loudness = max(-60.0, min(6.0, loudness))
            except (ValueError, TypeError):
                loudness = None

            # Playtime parsing
            try:
                ms_played = float(r.get("msPlayed") or 0)
            except (ValueError, TypeError):
                ms_played = 0.0

            # Duration parsing & imputation
            try:
                dur_val = r.get("duration_ms") or r.get("msPlayed")
                if dur_val is None or str(dur_val).strip() == "":
                    duration_ms = None
                else:
                    duration_ms = int(float(dur_val))
                    if duration_ms <= 0:
                        duration_ms = None
            except (ValueError, TypeError):
                duration_ms = None

            # Smart Genre Imputation
            genre = (r.get("genre") or "").strip()
            if not genre:
                genre = artist_modes.get(artist_name.lower(), "Unknown")

            track_id = ""
            if track_url and "/track/" in track_url:
                track_id = track_url.split("/track/")[-1].split("?")[0].strip()
            spotify_embed_url = (
                f"https://open.spotify.com/embed/track/{track_id}?utm_source=generator&theme=0"
                if track_id
                else ""
            )

            songs.append(
                {
                    "trackName": track_name,
                    "artistName": artist_name,
                    "genre": genre,
                    "danceability": danceability,
                    "energy": energy,
                    "valence": valence,
                    "tempo": tempo,
                    "acousticness": acousticness,
                    "instrumentalness": instrumentalness,
                    "loudness": loudness,
                    "speechiness": speechiness,
                    "liveness": liveness,
                    "ms_played": ms_played,
                    "duration_ms": duration_ms,
                    "spotify_url": track_url,
                    "spotify_embed_url": spotify_embed_url,
                    "id": (r.get("id") or "").strip(),
                    "uri": (r.get("uri") or "").strip(),
                }
            )

            seen_tracks.add(dup_key)

        except Exception:
            continue

    return songs, columns


ALL_SONGS, CSV_COLUMNS = _load_csv()
ALL_GENRES = sorted({song["genre"] for song in ALL_SONGS if song.get("genre")})
AVAILABLE_GENRES = ALL_GENRES
GENRE_COLORS = _build_genre_colors(ALL_GENRES)
AUDIO_FEATURES = _build_audio_features(CSV_COLUMNS)


def get_saved_genres(prefs):
    return json.loads(prefs.genres) if prefs and prefs.genres else []
