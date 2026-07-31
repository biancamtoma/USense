import os
import json
import math

# Load pre-trained coefficients
_dir = os.path.dirname(os.path.abspath(__file__))
COEFF_PATH = os.path.join(_dir, "..", "data", "lr_coefficients.json")

_MODEL_PARAMS = None


def clear_model_cache():
    global _MODEL_PARAMS
    _MODEL_PARAMS = None


def _load_model():
    global _MODEL_PARAMS
    if _MODEL_PARAMS is not None:
        return _MODEL_PARAMS

    if os.path.exists(COEFF_PATH):
        try:
            with open(COEFF_PATH, "r") as f:
                _MODEL_PARAMS = json.load(f)
        except Exception:
            pass

    # Fallback to default calibrated values if file not found or corrupted
    if not _MODEL_PARAMS:
        _MODEL_PARAMS = {
            "intercept": -1.58,
            "coefficients": {
                "cosine_similarity": 0.85,
                "genre_match": 1.10,
                "artist_match": 0.50,
                "danceability": 0.35,
                "energy": 0.20,
                "valence": 0.15,
                "tempo": 0.10,
                "acousticness": -0.10,
                "instrumentalness": 0.05,
                "speechiness": 0.05,
            },
        }
    return _MODEL_PARAMS


def predict_ad_completion_probability(song, prefs, brief_score, liked_artists=None):
    """
    Predicts the probability of a song achieving a completion rate > 70% in a campaign.
    Uses the trained Logistic Regression model coefficients and StandardScaler parameter scaling.
    """
    params = _load_model()
    intercept = params["intercept"]
    coefs = params["coefficients"]
    scaler = params.get("scaler", {})
    means = scaler.get("mean", {})
    scales = scaler.get("scale", {})

    # 1. Cosine similarity from recommender
    cos_sim = float(brief_score or 0.0)

    # 2. Genre match (1.0 if song's genre is in user target genres, else 0.0)
    genre_match = 0.0
    song_genre = str(song.get("genre", "")).strip().lower()
    if prefs and getattr(prefs, "genres", None):
        try:
            target_genres = json.loads(prefs.genres)
            if song_genre in [g.strip().lower() for g in target_genres]:
                genre_match = 1.0
        except (ValueError, TypeError):
            pass

    # 3. Artist match (1.0 if artist matches any user-liked/room-pinned artist)
    artist_match = 0.0
    song_artist = str(song.get("artistName", "")).strip().lower()
    if liked_artists and song_artist in [a.strip().lower() for a in liked_artists]:
        artist_match = 1.0

    # 4. Audio features
    danceability = float(song.get("danceability") or 0.5)
    energy = float(song.get("energy") or 0.5)
    valence = float(song.get("valence") or 0.5)
    tempo = float(song.get("tempo") or 120.0)
    acousticness = float(song.get("acousticness") or 0.5)
    instrumentalness = float(song.get("instrumentalness") or 0.0)
    speechiness = float(song.get("speechiness") or 0.05)

    # Pack values into dictionary to scale them
    raw_feats = {
        "cosine_similarity": cos_sim,
        "genre_match": genre_match,
        "artist_match": artist_match,
        "danceability": danceability,
        "energy": energy,
        "valence": valence,
        "tempo": tempo,
        "acousticness": acousticness,
        "instrumentalness": instrumentalness,
        "speechiness": speechiness,
    }

    # Standardize features using the scaler parameters exported from training
    scaled_feats = {}
    for name, val in raw_feats.items():
        mean = means.get(name, 0.0)
        scale = scales.get(name, 1.0)
        scaled_feats[name] = (val - mean) / (scale if scale > 0 else 1.0)

    # Logit dot product calculation
    z = intercept + sum(coefs.get(name, 0.0) * scaled_feats[name] for name in raw_feats)

    # Sigmoid function
    probability = 1.0 / (1.0 + math.exp(-z))
    return probability


if __name__ == "__main__":
    import pandas as pd

    # Locate dataset path relative to this script
    _dir = os.path.dirname(os.path.abspath(__file__))
    dataset_path = os.path.join(_dir, "..", "data", "Spotify_Song_Attributes.csv")

    if os.path.exists(dataset_path):
        print(f"Loading real songs from dataset: {dataset_path}")
        df = pd.read_csv(dataset_path).dropna(
            subset=["trackName", "artistName", "danceability", "energy", "valence", "tempo", "acousticness", "instrumentalness", "speechiness"]
        )
        
        # Take 5 sample songs across the catalog
        samples = df.sample(n=5, random_state=42)
        
        print("\n--- Running Predictions on Real Dataset Songs ---")
        for idx, row in samples.iterrows():
            song = {
                "trackName": row["trackName"],
                "artistName": row["artistName"],
                "genre": row["genre"] if pd.notna(row["genre"]) else "Pop",
                "danceability": float(row["danceability"]),
                "energy": float(row["energy"]),
                "valence": float(row["valence"]),
                "tempo": float(row["tempo"]),
                "acousticness": float(row["acousticness"]),
                "instrumentalness": float(row["instrumentalness"]),
                "speechiness": float(row["speechiness"]),
            }
            
            # Predict with dummy preferences and brief_score (e.g. 0.85 brief score)
            prob = predict_ad_completion_probability(song, prefs=None, brief_score=0.85)
            print(f"Track: {song['trackName']} | Artist: {song['artistName']}")
            print(f"  Danceability: {song['danceability']:.3f} | Energy: {song['energy']:.3f} | Tempo: {song['tempo']:.1f} BPM")
            print(f"  Predicted Ad Completion Probability: {prob * 100:.2f}%")
            print("-" * 50)
    else:
        print(f"Dataset not found at {dataset_path}")
