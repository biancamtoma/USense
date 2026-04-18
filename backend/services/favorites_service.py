from models.database import FavoriteRecommendation


def _favorite_key(track_name, artist_name):
    return f"{track_name.strip().lower()}||{artist_name.strip().lower()}"


def get_favorite_recommendations(user):
    if not user:
        return []

    return FavoriteRecommendation.query.filter_by(user_id=user.id).order_by(FavoriteRecommendation.created_at.desc()).all()


def get_favorite_recommendation_keys(user):
    favorites = get_favorite_recommendations(user)
    return {_favorite_key(item.track_name, item.artist_name) for item in favorites}
