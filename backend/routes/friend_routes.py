from flask import flash, redirect, request, session, url_for

from models.database import FriendRequest, User, db


def register_collaborator_routes(app):
    @app.route("/collaborators/request", methods=["POST"])
    def send_collaborator_request():
        if "email" not in session:
            return redirect(url_for("home"))

        current_user = User.query.filter_by(username=session["email"]).first()
        target_email = request.form.get("collaborator_email", "").strip().lower()

        if not current_user or not target_email:
            flash("Enter a valid email address.", "error")
            return redirect(url_for("dashboard"))

        if target_email == current_user.username:
            flash("You cannot send a collaborator invitation to yourself.", "error")
            return redirect(url_for("dashboard"))

        target_user = User.query.filter_by(username=target_email).first()
        if not target_user:
            flash("No account exists for that email address.", "error")
            return redirect(url_for("dashboard"))

        existing_request = FriendRequest.query.filter(
            (
                (FriendRequest.sender_id == current_user.id)
                & (FriendRequest.receiver_id == target_user.id)
            )
            | (
                (FriendRequest.sender_id == target_user.id)
                & (FriendRequest.receiver_id == current_user.id)
            )
        ).first()

        if existing_request:
            if existing_request.status == "accepted":
                flash("You are already collaborators with this user.", "error")
            elif existing_request.status == "pending":
                flash(
                    "A collaborator invitation already exists between you and this user.",
                    "error",
                )
            else:
                existing_request.sender_id = current_user.id
                existing_request.receiver_id = target_user.id
                existing_request.status = "pending"
                db.session.commit()
                flash("Collaborator invitation sent.", "success")
            return redirect(url_for("dashboard"))

        db.session.add(
            FriendRequest(
                sender_id=current_user.id, receiver_id=target_user.id, status="pending"
            )
        )
        db.session.commit()
        flash("Collaborator invitation sent.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/collaborators/<int:request_id>/accept", methods=["POST"])
    def accept_collaborator_request(request_id):
        if "email" not in session:
            return redirect(url_for("home"))

        current_user = User.query.filter_by(username=session["email"]).first()
        collaborator_request = FriendRequest.query.filter_by(
            id=request_id,
            receiver_id=current_user.id if current_user else None,
            status="pending",
        ).first()

        if not collaborator_request:
            flash("That collaborator invitation is no longer available.", "error")
            return redirect(url_for("dashboard"))

        collaborator_request.status = "accepted"
        db.session.commit()
        flash("Collaborator invitation accepted.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/collaborators/<int:request_id>/decline", methods=["POST"])
    def decline_collaborator_request(request_id):
        if "email" not in session:
            return redirect(url_for("home"))

        current_user = User.query.filter_by(username=session["email"]).first()
        collaborator_request = FriendRequest.query.filter_by(
            id=request_id,
            receiver_id=current_user.id if current_user else None,
            status="pending",
        ).first()

        if not collaborator_request:
            flash("That collaborator invitation is no longer available.", "error")
            return redirect(url_for("dashboard"))

        collaborator_request.status = "declined"
        db.session.commit()
        flash("Collaborator invitation declined.", "success")
        return redirect(url_for("dashboard"))
