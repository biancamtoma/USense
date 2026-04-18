from flask import flash, redirect, request, session, url_for

from models.database import FavoriteRecommendation, User, db


def register_recommendation_routes(app):
    @app.route("/recommendations/favorites/add", methods=["POST"])
    def add_favorite_recommendation():
        if "email" not in session:
            return redirect(url_for("home"))

        current_user = User.query.filter_by(username=session["email"]).first()
        if not current_user:
            return redirect(url_for("home"))

        track_name = request.form.get("track_name", "").strip()
        artist_name = request.form.get("artist_name", "").strip()
        genre = request.form.get("genre", "").strip() or None
        spotify_url = request.form.get("spotify_url", "").strip() or None
        color = request.form.get("color", "").strip() or None
        source_type = request.form.get("source_type", "").strip() or None
        source_label = request.form.get("source_label", "").strip() or None

        if not track_name or not artist_name:
            flash("Could not save favorite: missing song details.", "error")
            return redirect(url_for("dashboard"))

        match_score_raw = request.form.get("match_score", "").strip()
        taste_match_raw = request.form.get("taste_match", "").strip()
        try:
            match_score = int(match_score_raw) if match_score_raw else None
        except ValueError:
            match_score = None

        try:
            taste_match = int(taste_match_raw) if taste_match_raw else None
        except ValueError:
            taste_match = None

        existing = FavoriteRecommendation.query.filter_by(
            user_id=current_user.id,
            track_name=track_name,
            artist_name=artist_name,
        ).first()

        if existing:
            flash("This recommendation is already in your favorites.", "success")
            return redirect(url_for("dashboard"))

        db.session.add(
            FavoriteRecommendation(
                user_id=current_user.id,
                track_name=track_name,
                artist_name=artist_name,
                genre=genre,
                spotify_url=spotify_url,
                color=color,
                match_score=match_score,
                source_type=source_type,
                source_label=source_label,
                taste_match=taste_match,
            )
        )
        db.session.commit()

        flash("Recommendation saved to favorites.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/recommendations/favorites/<int:favorite_id>/remove", methods=["POST"])
    def remove_favorite_recommendation(favorite_id):
        if "email" not in session:
            return redirect(url_for("home"))

        current_user = User.query.filter_by(username=session["email"]).first()
        if not current_user:
            return redirect(url_for("home"))

        favorite = FavoriteRecommendation.query.filter_by(
            id=favorite_id,
            user_id=current_user.id,
        ).first()

        if not favorite:
            flash("Favorite not found.", "error")
            return redirect(url_for("favorites"))

        db.session.delete(favorite)
        db.session.commit()
        flash("Removed from favorites.", "success")
        return redirect(url_for("favorites"))
