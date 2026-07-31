import pandas as pd
import numpy as np

CSV_PATH = (
    r"d:\Anul 3_CSIE\USense_from_scratch\backend\data\Spotify_Song_Attributes.csv"
)


def analyze_genre_imputation():
    df = pd.read_csv(CSV_PATH)

    # Drop exact row duplicates first
    df = df.drop_duplicates()

    total_rows = len(df)
    missing_genres_before = df["genre"].isnull().sum()
    print(f"Total unique rows: {total_rows}")
    print(
        f"Missing genres before imputation: {missing_genres_before} ({missing_genres_before/total_rows:.2%})"
    )

    # Create artist to genre map (most frequent genre per artist)
    artist_genres = (
        df.dropna(subset=["genre"])
        .groupby("artistName")["genre"]
        .agg(lambda x: x.mode()[0] if not x.empty else None)
        .to_dict()
    )

    # Try imputing
    df_imputed = df.copy()
    df_imputed["genre"] = df_imputed.apply(
        lambda row: (
            artist_genres.get(row["artistName"], np.nan)
            if pd.isnull(row["genre"])
            else row["genre"]
        ),
        axis=1,
    )

    missing_genres_after = df_imputed["genre"].isnull().sum()
    print(
        f"Missing genres after artist-based imputation: {missing_genres_after} ({missing_genres_after/total_rows:.2%})"
    )
    print(
        f"Successfully imputed {missing_genres_before - missing_genres_after} genres."
    )


if __name__ == "__main__":
    analyze_genre_imputation()
