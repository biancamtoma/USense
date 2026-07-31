import pandas as pd
import numpy as np
import os

CSV_PATH = (
    r"d:\Anul 3_CSIE\USense_from_scratch\backend\data\Spotify_Song_Attributes.csv"
)


def analyze_dataset():
    if not os.path.exists(CSV_PATH):
        print(f"File not found: {CSV_PATH}")
        return

    df = pd.read_csv(CSV_PATH)
    print("--- Dataset Shape ---")
    print(df.shape)

    print("\n--- Columns ---")
    print(df.columns.tolist())

    print("\n--- Missing Values ---")
    print(df.isnull().sum())

    print("\n--- Duplicate Rows (complete duplicates) ---")
    print(f"Count of duplicate rows: {df.duplicated().sum()}")

    print("\n--- Duplicate Songs (same trackName and artistName) ---")
    if "trackName" in df.columns and "artistName" in df.columns:
        dup_songs = df.duplicated(subset=["trackName", "artistName"]).sum()
        print(f"Count of duplicate tracks: {dup_songs}")

    print("\n--- Unique Values ---")
    for col in df.columns:
        print(f"{col}: {df[col].nunique()} unique values")

    print("\n--- Basic Numeric Stats ---")
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    print(df[numeric_cols].describe().to_string())

    print("\n--- Out of Range Audio Features (Expected 0 to 1) ---")
    audio_features = [
        "danceability",
        "energy",
        "valence",
        "acousticness",
        "instrumentalness",
        "speechiness",
        "liveness",
    ]
    for feat in audio_features:
        if feat in df.columns:
            oob = df[(df[feat] < 0) | (df[feat] > 1)]
            print(f"{feat}: {len(oob)} rows outside [0, 1] range")
            if len(oob) > 0:
                print(oob[[feat, "trackName", "artistName"]].head(3))

    print("\n--- Tempo and Loudness ---")
    if "tempo" in df.columns:
        print(f"Tempo < 0: {len(df[df['tempo'] < 0])}")
        print(f"Tempo == 0: {len(df[df['tempo'] == 0])}")
    if "loudness" in df.columns:
        print(f"Loudness > 0: {len(df[df['loudness'] > 0])}")


if __name__ == "__main__":
    analyze_dataset()
