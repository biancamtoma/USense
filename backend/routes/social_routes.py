from flask import flash, redirect, request, session, url_for

from models.database import FriendMessage, User, db
from services.social_service import are_collaborators


def register_social_routes(app, socketio=None):
    @app.route("/messages/send", methods=["POST"])
    def send_collaborator_message():
        if "email" not in session:
            return redirect(url_for("home"))

        current_user = User.query.filter_by(username=session["email"]).first()
        collaborator_id = request.form.get("collaborator_id", type=int)
        body = request.form.get("body", "").strip()

        if not current_user or not collaborator_id or not body:
            flash("Write a message before sending.", "error")
            return redirect(url_for("dashboard"))

        if not are_collaborators(current_user.id, collaborator_id):
            flash("You can only chat with accepted collaborators.", "error")
            return redirect(url_for("dashboard"))

        trimmed_body = body[:500]
        message = FriendMessage(
            sender_id=current_user.id, receiver_id=collaborator_id, body=trimmed_body
        )
        db.session.add(message)
        db.session.commit()

        if socketio:
            sender_label = current_user.username.split("@")[0]
            socketio.emit(
                "chat:new_message",
                {
                    "collaborator_id": collaborator_id,
                    "body": trimmed_body,
                    "direction": "You",
                    "sender_id": current_user.id,
                    "receiver_id": collaborator_id,
                    "sender_label": sender_label,
                    "message_id": message.id,
                },
                room=f"user_{current_user.id}",
            )
            socketio.emit(
                "chat:new_message",
                {
                    "collaborator_id": current_user.id,
                    "body": trimmed_body,
                    "direction": sender_label,
                    "sender_id": current_user.id,
                    "receiver_id": collaborator_id,
                    "sender_label": sender_label,
                    "message_id": message.id,
                },
                room=f"user_{collaborator_id}",
            )

        flash("Message sent.", "success")
        return redirect(url_for("dashboard"))
