import pandas as pd
import numpy as np
import json
import os
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score

# Paths
_dir = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(_dir, "Spotify_Song_Attributes.csv")
output_json_path = os.path.join(_dir, "lr_coefficients.json")


def get_cosine_similarity(vec_a, vec_b):
    dot = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def train_model():
    print("Loading song dataset...")
    df = pd.read_csv(csv_path)

    # Drop rows missing critical features
    df = df.dropna(
        subset=[
            "msPlayed",
            "duration_ms",
            "danceability",
            "energy",
            "valence",
            "tempo",
            "acousticness",
            "instrumentalness",
            "speechiness",
        ]
    )
    df = df[df["duration_ms"] > 0]

    # Label is 1 if msPlayed / duration_ms > 0.7, else 0
    ratios = df["msPlayed"] / df["duration_ms"]
    df["label"] = (ratios > 0.7).astype(int)

    # Load dynamic user feedback from database
    db_records = []
    
    # 1. Try using Flask context first
    try:
        from flask import current_app
        if current_app:
            print("Detected active Flask application context. Querying database via SQLAlchemy ORM...")
            from models.database import SongStatus, FavoriteRecommendation, UserInteractionLog
            
            # Query song statuses (approved/sent_to_client -> 1, rejected -> 0)
            statuses = SongStatus.query.all()
            for s in statuses:
                if s.status in ("approved", "sent_to_client"):
                    db_records.append({"track_key": s.track_key, "label": 1})
                elif s.status == "rejected":
                    db_records.append({"track_key": s.track_key, "label": 0})
            
            # Query favorites (favorited -> 1)
            favs = FavoriteRecommendation.query.all()
            for f in favs:
                tk = f"{f.track_name}|||{f.artist_name}"
                db_records.append({"track_key": tk, "label": 1})

            # Query interaction logs (play -> 1, skip -> 0)
            logs = UserInteractionLog.query.all()
            for l in logs:
                tk = f"{l.track_name}|||{l.artist_name}"
                if l.action == "play":
                    db_records.append({"track_key": tk, "label": 1})
                elif l.action == "skip":
                    db_records.append({"track_key": tk, "label": 0})
    except Exception as e:
        print("Flask context query failed or inactive. Checking direct file connection...", e)

    # 2. Standalone fallback via raw sqlite3
    if not db_records:
        import sqlite3
        # Look for user.db relative to backend or current directories
        db_paths = [
            os.path.join(_dir, "..", "instance", "user.db"),
            os.path.join(_dir, "instance", "user.db"),
            "instance/user.db",
            "user.db"
        ]
        db_path = None
        for p in db_paths:
            if os.path.exists(p):
                db_path = p
                break
        
        if db_path:
            print(f"Direct connection found at '{db_path}'. Querying user.db file...")
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Check if song_status table exists and query it
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='song_status'")
                if cursor.fetchone():
                    cursor.execute("SELECT track_key, status FROM song_status")
                    for tk, status in cursor.fetchall():
                        if status in ("approved", "sent_to_client"):
                            db_records.append({"track_key": tk, "label": 1})
                        elif status == "rejected":
                            db_records.append({"track_key": tk, "label": 0})
                
                # Check if favorite_recommendation table exists and query it
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='favorite_recommendation'")
                if cursor.fetchone():
                    cursor.execute("SELECT track_name, artist_name FROM favorite_recommendation")
                    for name, artist in cursor.fetchall():
                        tk = f"{name}|||{artist}"
                        db_records.append({"track_key": tk, "label": 1})
                
                # Check if user_interaction_log table exists and query it
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_interaction_log'")
                if cursor.fetchone():
                    cursor.execute("SELECT track_name, artist_name, action FROM user_interaction_log")
                    for name, artist, action in cursor.fetchall():
                        tk = f"{name}|||{artist}"
                        if action == "play":
                            db_records.append({"track_key": tk, "label": 1})
                        elif action == "skip":
                            db_records.append({"track_key": tk, "label": 0})
                conn.close()
            except Exception as e:
                print("Direct sqlite3 query failed:", e)

    # 3. Map database records to the song catalog audio features
    new_rows = []
    if db_records:
        # Build lookup dictionary mapping track_key to its row copy (stripping quote formatting)
        song_pool = {}
        for idx, row in df.iterrows():
            t_name = str(row["trackName"]).replace('"', '').replace("'", "").lower().strip()
            t_art = str(row["artistName"]).replace('"', '').replace("'", "").lower().strip()
            tk = f"{t_name}|||{t_art}"
            song_pool[tk] = row

        for rec in db_records:
            rec_tk = str(rec["track_key"]).replace('"', '').replace("'", "").lower().strip()
            if rec_tk in song_pool:
                orig_row = song_pool[rec_tk].copy()
                orig_row["label"] = rec["label"]
                new_rows.append(orig_row)
                
        if new_rows:
            df_new = pd.DataFrame(new_rows)
            df = pd.concat([df, df_new], ignore_index=True)
            print(f"Successfully Injected {len(new_rows)} live database feedback records into model training dataset.")

    # Group by track to prevent duplicate track leakage (stripping quote formatting)
    clean_names = df["trackName"].astype(str).str.replace('"', '').str.replace("'", "").str.lower().str.strip()
    clean_artists = df["artistName"].astype(str).str.replace('"', '').str.replace("'", "").str.lower().str.strip()
    df["track_group"] = clean_names + "|||" + clean_artists

    # 1. Restructure Split: Group split by track to prevent leakage
    from sklearn.model_selection import GroupShuffleSplit
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(gss.split(df, groups=df["track_group"]))

    train_df = df.iloc[train_idx].copy()
    test_df = df.iloc[test_idx].copy()

    # 2. Compute Popularity Score on the training set ONLY
    # Use average msPlayed per track to align training and runtime scales
    print("Calculating popularity scores...")
    track_pop = (
        train_df.groupby(["trackName", "artistName"])["msPlayed"].mean().reset_index()
    )
    track_pop.rename(columns={"msPlayed": "popularity_score"}, inplace=True)

    train_df = train_df.merge(track_pop, on=["trackName", "artistName"], how="left")
    test_df = test_df.merge(track_pop, on=["trackName", "artistName"], how="left")

    # Impute unseen test track popularity scores using training median
    global_median_pop = train_df["msPlayed"].median()
    train_df["popularity_score"] = train_df["popularity_score"].fillna(global_median_pop)
    test_df["popularity_score"] = test_df["popularity_score"].fillna(global_median_pop)

    # 3. Compute global user preferences on the training set ONLY
    print("Computing deterministic user preferences from training liked songs...")
    liked_songs_train = train_df[train_df["label"] == 1]

    # Meaningful fixed user profile vector (mean of 5 audio features for liked training songs)
    user_profile_5d = liked_songs_train[
        ["danceability", "energy", "valence", "acousticness", "instrumentalness"]
    ].mean().to_numpy()
    print(f"Derived fixed user profile 5D: {user_profile_5d}")

    # Preferred genres based on training stats (top 15 genres by number of liked songs)
    genre_likes = liked_songs_train["genre"].dropna().str.strip().str.lower()
    top_genres = set(genre_likes.value_counts().head(15).index)
    print(f"Derived target genres count: {len(top_genres)}")

    # Preferred artists based on training stats (top 50 artists by number of liked songs)
    artist_likes = liked_songs_train["artistName"].dropna().str.strip().str.lower()
    top_artists = set(artist_likes.value_counts().head(50).index)
    print(f"Derived target artists count: {len(top_artists)}")

    # Helper function to engineer features post-split
    def extract_features(data_df):
        features_list = []
        for idx, row in data_df.iterrows():
            song_audio_5d = np.array(
                [
                    float(row["danceability"]),
                    float(row["energy"]),
                    float(row["valence"]),
                    float(row["acousticness"]),
                    float(row["instrumentalness"]),
                ]
            )

            # Cosine similarity against training user profile
            cos_sim = get_cosine_similarity(song_audio_5d, user_profile_5d)

            # Genre match against training top genres
            song_genre = str(row["genre"]).strip().lower()
            genre_match = 1.0 if song_genre in top_genres else 0.0

            # Artist match against training top artists
            song_artist = str(row["artistName"]).strip().lower()
            artist_match = 1.0 if song_artist in top_artists else 0.0

            feat = [
                cos_sim,
                genre_match,
                artist_match,
                float(row["danceability"]),
                float(row["energy"]),
                float(row["valence"]),
                float(row["tempo"]),
                float(row["acousticness"]),
                float(row["instrumentalness"]),
                float(row["speechiness"]),
            ]
            features_list.append(feat)
        return np.array(features_list)

    print("Engineering training features...")
    X_train = extract_features(train_df)
    y_train = train_df["label"].to_numpy()

    print("Engineering test features...")
    X_test = extract_features(test_df)
    y_test = test_df["label"].to_numpy()

    # Scale features using StandardScaler
    print("Normalizing features...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    print("Training Logistic Regression model with solver='liblinear' and balanced class weights...")
    model = LogisticRegression(class_weight="balanced", solver="liblinear", max_iter=1000)
    model.fit(X_train_scaled, y_train)

    # Evaluate
    y_pred = model.predict(X_test_scaled)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred)
    recall = recall_score(y_test, y_pred)
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)

    from sklearn.metrics import confusion_matrix, classification_report
    cm = confusion_matrix(y_test, y_pred)
    cr = classification_report(y_test, y_pred, zero_division=0)

    # Format Confusion Matrix nicely
    cm_str = f"               Predicted Neg    Predicted Pos\n" \
             f"Actual Neg         {cm[0][0]:<12} {cm[0][1]:<12}\n" \
             f"Actual Pos         {cm[1][0]:<12} {cm[1][1]:<12}"

    print("Model Evaluation:")
    print(f"  Accuracy:  {acc:.4f}")
    print(f"  Precision: {prec:.4f}")
    print(f"  Recall:    {rec:.4f}")
    print("\nConfusion Matrix:")
    print(cm_str)
    print("\nClassification Report:")
    print(cr)

    # Export parameters & scaler means/scales
    feature_names = [
        "cosine_similarity",
        "genre_match",
        "artist_match",
        "danceability",
        "energy",
        "valence",
        "tempo",
        "acousticness",
        "instrumentalness",
        "speechiness",
    ]

    coefficients = {
        name: float(coef) for name, coef in zip(feature_names, model.coef_[0])
    }
    scaler_mean = {name: float(m) for name, m in zip(feature_names, scaler.mean_)}
    scaler_scale = {name: float(s) for name, s in zip(feature_names, scaler.scale_)}

    model_params = {
        "intercept": float(model.intercept_[0]),
        "coefficients": coefficients,
        "scaler": {"mean": scaler_mean, "scale": scaler_scale},
        "metrics": {
            "accuracy": float(acc),
            "precision": float(prec),
            "recall": float(rec),
            "confusion_matrix": cm_str,
            "classification_report": cr,
        },
    }

    with open(output_json_path, "w") as f:
        json.dump(model_params, f, indent=4)

    print(
        f"Successfully saved model parameters and scaling vectors to: {output_json_path}"
    )

    # Clear the in-memory predictor cache to force reloading of updated JSON parameters
    try:
        from services.retention_predictor import clear_model_cache
        clear_model_cache()
        print("Model cache cleared successfully.")
    except Exception as e:
        print("Could not clear model cache:", e)

    return model_params


if __name__ == "__main__":
    train_model()
