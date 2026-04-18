from flask import flash, redirect, request, session, url_for

from models.database import FriendMessage, User, db
from services.social_service import are_friends



def register_social_routes(app):
    @app.route("/messages/send", methods=["POST"])
    def send_friend_message():
        if "email" not in session:
            return redirect(url_for("home"))

        current_user = User.query.filter_by(username=session["email"]).first()
        friend_id = request.form.get("friend_id", type=int)
        body = request.form.get("body", "").strip()

        if not current_user or not friend_id or not body:
            flash("Write a message before sending.", "error")
            return redirect(url_for("dashboard"))

        if not are_friends(current_user.id, friend_id):
            flash("You can only chat with accepted friends.", "error")
            return redirect(url_for("dashboard"))

        db.session.add(FriendMessage(sender_id=current_user.id, receiver_id=friend_id, body=body[:500]))
        db.session.commit()
        flash("Message sent.", "success")
        return redirect(url_for("dashboard"))