from models.database import FavoriteRecommendation


def _favorite_key(track_name, artist_name):
    return f"{track_name.strip().lower()}||{artist_name.strip().lower()}"


def get_favorite_recommendations(user):
    if not user:
        return []

    favorites = (
        FavoriteRecommendation.query.filter_by(user_id=user.id)
        .order_by(FavoriteRecommendation.created_at.desc())
        .all()
    )

    # Dynamically fill in missing spotify_urls from ALL_SONGS catalog
    from services.song_service import ALL_SONGS
    song_map = {}
    for song in ALL_SONGS:
        k = f"{song['trackName'].strip().lower()}|||{song['artistName'].strip().lower()}"
        song_map[k] = song.get("spotify_url")

    for fav in favorites:
        if not fav.spotify_url:
            k = f"{fav.track_name.strip().lower()}|||{fav.artist_name.strip().lower()}"
            fav.spotify_url = song_map.get(k)

    return favorites


def get_favorite_recommendation_keys(user):
    favorites = get_favorite_recommendations(user)
    return {_favorite_key(item.track_name, item.artist_name) for item in favorites}
