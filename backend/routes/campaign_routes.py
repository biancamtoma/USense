import json
import re
import csv
import io
import os
import math
import random
from werkzeug.utils import secure_filename

from flask import flash, redirect, render_template, request, session, url_for, jsonify
from flask_socketio import emit, join_room

from models.database import (
    CampaignRoom,
    RoomEvent,
    RoomMessage,
    RoomReaction,
    RoomPin,
    RoomPoll,
    RoomPollVote,
    SongStatus,
    SONG_STATUSES,
    SONG_STATUS_LABELS,
    User,
    UserPreferences,
    db,
    FavoriteRecommendation,
    ABTest,
    ABVote,
    AB_EMOTION_LABELS,
)

ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}

def _get_upload_path(app):
    """Return the path for campaign video/audio uploads."""
    upload_path = os.path.join(app.static_folder, "uploads", "campaigns")
    os.makedirs(upload_path, exist_ok=True)
    return upload_path
from services.music_recommendation_service import get_hybrid_recommendations
from services.recommender_shared import track_key
from services.congruence_service import compute_congruence


def _user_label(user_id):
    """Helper: display name for a user_id."""
    prefs = UserPreferences.query.filter_by(user_id=user_id).first()
    if prefs and prefs.display_name:
        return prefs.display_name
    u = User.query.get(user_id)
    return u.username.split("@")[0] if u else "?"


def register_campaign_routes(app, socketio, campaign_moods):
    """Register all campaign-room HTTP routes and Socket.IO events.

    Parameters
    ----------
    app : Flask
    socketio : SocketIO
    campaign_moods : dict
        The CAMPAIGN_MOODS lookup defined in main.py.
    """

    # HTTP Routes 

    @app.route("/room/create", methods=["POST"])
    def create_campaign_room():
        """Create a new campaign chat room from a mood preset."""
        if "email" not in session:
            return redirect(url_for("home"))

        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return redirect(url_for("home"))

        # Sandbox supervisor is allowed to create rooms for test/demonstration purposes

        mood_key = request.form.get("mood_key", "").strip()
        custom_name = request.form.get("room_name", "").strip()

        preset = campaign_moods.get(mood_key)
        if not preset:
            flash("Invalid campaign mood.", "error")
            return redirect(url_for("dashboard"))

        name = custom_name or preset["label"]

        # Capture current brief context from session
        brief_data = session.get("campaign_brief", {})
        brief_summary = ""
        asset_name = ""
        if brief_data:
            summary_parts = []
            if brief_data.get("objective"):
                summary_parts.append(brief_data["objective"].capitalize())
            if brief_data.get("target_audience"):
                summary_parts.append(f"Audience: {brief_data['target_audience']}")
            if brief_data.get("platform"):
                summary_parts.append(
                    f"Platform: {brief_data['platform'].replace('_',' ').capitalize()}"
                )
            brief_summary = " | ".join(summary_parts)
            asset_name = brief_data.get("asset_name", "")

        room = CampaignRoom(
            mood_key=mood_key,
            name=name,
            created_by=user.id,
            brief_summary=brief_summary,
            asset_path=asset_name,
        )
        room.members.append(user)
        db.session.add(room)
        db.session.flush()

        # Generate creation event
        event_body = f'Created campaign room "{name}"'
        if brief_summary:
            event_body += f" matching brief: {brief_summary}"

        db.session.add(
            RoomEvent(
                room_id=room.id,
                user_id=user.id,
                event_type="room_created",
                body=event_body,
                meta_json=json.dumps(
                    {
                        "mood_key": mood_key,
                        "preset_label": preset["label"],
                        "brief_summary": brief_summary,
                        "asset_path": asset_name,
                    }
                ),
            )
        )
        db.session.commit()

        return redirect(url_for("campaign_room", room_id=room.id))

    @app.route("/room/<int:room_id>")
    def campaign_room(room_id):
        """Full-page campaign workspace with feed timeline."""
        if "email" not in session:
            return redirect(url_for("home"))

        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return redirect(url_for("home"))

        room = CampaignRoom.query.get(room_id)
        if not room:
            flash("Room not found.", "error")
            return redirect(url_for("dashboard"))

        if user not in room.members and user.id != room.created_by:
            flash("You don't have access to this room.", "error")
            return redirect(url_for("dashboard"))

        if not room.is_ongoing:
            return redirect(url_for("get_campaign_after_experience", room_id=room_id))

        prefs = UserPreferences.query.filter_by(user_id=user.id).first()
        display_name = (
            (prefs.display_name or session["email"]) if prefs else session["email"]
        )

        # Build mood preferences from the room's mood_key
        preset = campaign_moods.get(room.mood_key, {})

        class RoomPrefs:
            pass

        room_prefs = RoomPrefs()
        if prefs:
            for column in prefs.__table__.columns:
                setattr(room_prefs, column.name, getattr(prefs, column.name))
        else:
            room_prefs.genres = "[]"
            room_prefs.feature_weights = "{}"
            room_prefs.use_interaction_signal = False
            room_prefs.interaction_blend = 0.65
            room_prefs.enable_personalized_similarity = False
            room_prefs.personalized_similarity_text = ""
            room_prefs.enable_genre_boost = False
            room_prefs.genre_boost_weight = 1.0
            room_prefs.user_id = user.id
            room_prefs.display_name = None
            room_prefs.weight_base_audio = 0.40
            room_prefs.weight_industry = 0.20
            room_prefs.weight_generation = 0.20
            room_prefs.weight_campaign = 0.20
            room_prefs.enable_acoustic_matcher = False
            room_prefs.target_generation = None
            room_prefs.target_campaign = None
            room_prefs.industry_focus = None
            room_prefs.roles = ""
        for key in (
            "pref_danceability",
            "pref_energy",
            "pref_valence",
            "pref_acousticness",
            "pref_instrumentalness",
        ):
            setattr(room_prefs, key, preset.get(key, 0.5))

        room_prefs.room_id = room.id
        songs = get_hybrid_recommendations(user, room_prefs, n=10)

        # Auto-generate "AI suggested tracks" event if none exists yet
        ai_events = RoomEvent.query.filter_by(
            room_id=room.id, event_type="ai_suggest"
        ).count()
        if ai_events == 0 and songs:
            track_names = [f"{s['trackName']} – {s['artistName']}" for s in songs[:6]]
            db.session.add(
                RoomEvent(
                    room_id=room.id,
                    user_id=None,
                    event_type="ai_suggest",
                    body=f"AI suggested {len(songs)} tracks matching the campaign brief",
                    meta_json=json.dumps({"count": len(songs), "sample": track_names}),
                )
            )
            db.session.commit()

        # Room reactions aggregated
        reactions = RoomReaction.query.filter_by(room_id=room.id).all()
        reactions_map = {}
        for r in reactions:
            key = r.track_key
            reactions_map.setdefault(key, {})
            reactions_map[key].setdefault(r.emoji, {"count": 0, "users": []})
            reactions_map[key][r.emoji]["count"] += 1
            reactions_map[key][r.emoji]["users"].append(r.user_id)

        # Track statuses (flags / approvals)
        flag_events = RoomEvent.query.filter_by(
            room_id=room.id, event_type="flag"
        ).all()
        approve_events = RoomEvent.query.filter_by(
            room_id=room.id, event_type="approve"
        ).all()
        flagged_tracks = {e.track_key for e in flag_events if e.track_key}
        approved_tracks = {e.track_key for e in approve_events if e.track_key}

        # Song status pipeline
        status_rows = SongStatus.query.filter_by(room_id=room.id).all()
        status_map = {}
        for sr in status_rows:
            status_map[sr.track_key] = {
                "status": sr.status,
                "label": SONG_STATUS_LABELS.get(sr.status, sr.status),
                "changed_by": _user_label(sr.changed_by),
                "reason": sr.reason or "",
            }

        creator_label = _user_label(room.created_by)

        # --- ML Behavioral Insights Calculation ---
        ml_insights = None
        if approved_tracks:
            from services.song_service import ALL_SONGS
            from services.recommender_shared import COMPARISON_FEATURES

            by_key = {track_key(s["trackName"], s["artistName"]): s for s in ALL_SONGS}

            feat_sums = {f: 0.0 for f in COMPARISON_FEATURES}
            count = 0
            for key in approved_tracks:
                song = by_key.get(key)
                if song:
                    count += 1
                    for f in COMPARISON_FEATURES:
                        feat_sums[f] += float(song.get(f, 0.0))

            if count > 0:
                ml_insights = {f: (feat_sums[f] / count) for f in COMPARISON_FEATURES}
                # Calculate ML influence (alpha)
                ml_insights["influence"] = min(60, count * 5)  # 0 to 60%
                ml_insights["count"] = count

        # --- Polls Calculation ---
        raw_polls = (
            RoomPoll.query.filter_by(room_id=room.id)
            .order_by(RoomPoll.created_at.desc())
            .all()
        )
        polls_data = []
        for p in raw_polls:
            options = json.loads(p.options_json)
            votes = RoomPollVote.query.filter_by(poll_id=p.id).all()
            counts = [0] * len(options)
            user_voted = None
            for v in votes:
                if v.option_index < len(counts):
                    counts[v.option_index] += 1
                if v.user_id == user.id:
                    user_voted = v.option_index

            polls_data.append(
                {
                    "id": p.id,
                    "question": p.question,
                    "options": options,
                    "author": p.user.username.split("@")[0],
                    "created_at": p.created_at.isoformat(),
                    "votes": counts,
                    "total_votes": len(votes),
                    "user_voted": user_voted,
                }
            )

        # --- Compute Congruence Scores for each song ---
        # (Kantar-style emotional congruence evaluation)
        campaign_platform = (
            room.brief_summary.split("Platform: ")[-1]
            .split(" |")[0]
            .strip()
            .lower()
            .replace(" ", "_")
            if room.brief_summary and "Platform:" in room.brief_summary
            else None
        )
        campaign_energy = None  # Could be extracted from brief if stored
        congruence_map = {}
        for s in songs:
            tk = s["trackName"].lower() + "|||" + s["artistName"].lower()
            congruence_map[tk] = compute_congruence(
                s, preset, campaign_platform, campaign_energy
            )

        # --- Video uploads for this room (disabled) ---
        room_videos = []

        from services.social_service import get_social_sidebar_data

        social_sidebar = get_social_sidebar_data(user, prefs)

        shazam_match = session.get(f"shazam_match_{room.id}")
        shazam_selected = session.get(f"shazam_selected_{room.id}", False)

        return render_template(
            "campaign_room.html",
            room=room,
            room_preset=preset,
            songs=songs,
            reactions_map=reactions_map,
            flagged_tracks=flagged_tracks,
            approved_tracks=approved_tracks,
            status_map=status_map,
            song_statuses=SONG_STATUSES,
            song_status_labels=SONG_STATUS_LABELS,
            email=session["email"],
            display_name=display_name,
            user_id=user.id,
            creator_label=creator_label,
            members=room.members,
            ml_insights=ml_insights,
            pins=RoomPin.query.filter_by(room_id=room.id)
            .order_by(RoomPin.created_at.desc())
            .all(),
            polls=polls_data,
            congruence_map=congruence_map,
            room_videos=room_videos,
            social_sidebar=social_sidebar,
            is_sandbox=(session["email"] == "demo.supervisor@gmail.com"),
            shazam_match=shazam_match,
            shazam_selected=shazam_selected,
        )

    @app.route("/room/<int:room_id>/invite", methods=["POST"])
    def invite_campaign_room(room_id):
        if "email" not in session:
            return redirect(url_for("home"))

        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return redirect(url_for("home"))

        room = CampaignRoom.query.get(room_id)
        if not room:
            flash("Room not found.", "error")
            return redirect(url_for("dashboard"))

        if session["email"] == "demo.supervisor@gmail.com":
            flash(
                "Sandbox Limit: Inviting team members is restricted in this trial sandbox. Log in now and use more features for free!",
                "warning",
            )
            return redirect(url_for("campaign_room", room_id=room_id))

        if user not in room.members and user.id != room.created_by:
            flash("You don't have permission to invite people to this room.", "error")
            return redirect(url_for("dashboard"))

        invite_email = request.form.get("email", "").strip()
        if not invite_email:
            flash("Please enter an email address.", "error")
            return redirect(url_for("campaign_room", room_id=room_id))

        invitee = User.query.filter_by(username=invite_email).first()
        if not invitee:
            flash("User not found. They must register first.", "error")
            return redirect(url_for("campaign_room", room_id=room_id))

        if invitee in room.members:
            flash("User is already in this room.", "info")
            return redirect(url_for("campaign_room", room_id=room_id))

        room.members.append(invitee)

        # Log the invite event
        db.session.add(
            RoomEvent(
                room_id=room.id,
                user_id=user.id,
                event_type="room_invite",
                body=f"Added {invite_email} to the room",
                meta_json=json.dumps({"invited_email": invite_email}),
            )
        )
        db.session.commit()

        flash(f"{invite_email} has been added to the room.", "success")
        return redirect(url_for("campaign_room", room_id=room_id))

    @app.route("/room/<int:room_id>/rename", methods=["POST"])
    def rename_campaign_room(room_id):
        if "email" not in session:
            return {"error": "Not authenticated"}, 401

        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        if user.id != room.created_by:
            return {"error": "Only the room creator can rename it."}, 403

        new_name = request.form.get("name", "").strip()[:200]
        if not new_name:
            return {"error": "Name cannot be empty"}, 400

        old_name = room.name
        room.name = new_name

        # Log the rename event
        db.session.add(
            RoomEvent(
                room_id=room.id,
                user_id=user.id,
                event_type="room_renamed",
                body=f'Renamed room from "{old_name}" to "{new_name}"',
                meta_json=json.dumps({"old_name": old_name, "new_name": new_name}),
            )
        )
        db.session.commit()

        # Broadcast to all members (for dashboard updates)
        for member in room.members:
            socketio.emit(
                "room:renamed",
                {"room_id": room_id, "new_name": new_name, "user_id": user.id},
                room=f"user_{member.id}",
            )

        # Also broadcast to the room itself (for workspace updates)
        socketio.emit(
            "room:renamed",
            {"room_id": room_id, "new_name": new_name, "user_id": user.id},
            room=f"campaign_room_{room_id}",
        )

        return {"ok": True, "new_name": new_name}

    #  JSON API 

    @app.route("/api/room/<int:room_id>/feed")
    def api_room_feed(room_id):
        """JSON: return aggregated chronological feed (messages + events)."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404
        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        messages = RoomMessage.query.filter_by(room_id=room_id).all()
        events = RoomEvent.query.filter_by(room_id=room_id).all()

        feed = []
        for m in messages:
            feed.append(
                {
                    "kind": "message",
                    "id": m.id,
                    "user_id": m.user_id,
                    "user_label": _user_label(m.user_id),
                    "body": m.body,
                    "track_key": m.track_key,
                    "audio_ts": m.audio_ts,
                    "created_at": m.created_at.isoformat(),
                }
            )
        for e in events:
            feed.append(
                {
                    "kind": "event",
                    "id": e.id,
                    "user_id": e.user_id,
                    "user_label": _user_label(e.user_id) if e.user_id else "System",
                    "event_type": e.event_type,
                    "body": e.body,
                    "meta": json.loads(e.meta_json) if e.meta_json else None,
                    "created_at": e.created_at.isoformat(),
                }
            )

        feed.sort(key=lambda x: x["created_at"])
        return {"feed": feed}

    @app.route("/api/room/<int:room_id>/messages")
    def api_room_messages(room_id):
        """JSON: return all chat messages for a campaign room."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404
        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        messages = (
            RoomMessage.query.filter_by(room_id=room_id)
            .order_by(RoomMessage.created_at.asc())
            .all()
        )
        result = []
        for msg in messages:
            result.append(
                {
                    "id": msg.id,
                    "user_id": msg.user_id,
                    "user_label": _user_label(msg.user_id),
                    "body": msg.body,
                    "track_key": msg.track_key,
                    "audio_ts": msg.audio_ts,
                    "is_self": msg.user_id == user.id,
                    "created_at": msg.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
        return {"messages": result}

    @app.route("/api/room/<int:room_id>/react", methods=["POST"])
    def api_room_react(room_id):
        """Toggle an emoji reaction on a song in a room."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404
        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        data = request.get_json(silent=True) or {}
        track_key = str(data.get("track_key", "")).strip()
        emoji = str(data.get("emoji", "")).strip()[:10]
        if not track_key or not emoji:
            return {"error": "Missing track_key or emoji"}, 400

        existing = RoomReaction.query.filter_by(
            room_id=room_id, user_id=user.id, track_key=track_key, emoji=emoji
        ).first()

        if existing:
            db.session.delete(existing)
            db.session.commit()
            action = "removed"
        else:
            db.session.add(
                RoomReaction(
                    room_id=room_id, user_id=user.id, track_key=track_key, emoji=emoji
                )
            )
            db.session.commit()
            action = "added"

        count = RoomReaction.query.filter_by(
            room_id=room_id, track_key=track_key, emoji=emoji
        ).count()
        socketio.emit(
            "room:reaction",
            {
                "room_id": room_id,
                "track_key": track_key,
                "emoji": emoji,
                "count": count,
                "action": action,
                "user_id": user.id,
            },
            room=f"campaign_room_{room_id}",
        )

        return {"ok": True, "action": action, "count": count}

    @app.route("/api/room/<int:room_id>/flag", methods=["POST"])
    def api_room_flag(room_id):
        """Flag a track for licensing / brand-safety issues."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404
        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        data = request.get_json(silent=True) or {}
        track_key = str(data.get("track_key", "")).strip()
        reason = str(data.get("reason", "")).strip()[:200]
        if not track_key:
            return {"error": "Missing track_key"}, 400

        existing = RoomEvent.query.filter_by(
            room_id=room_id, user_id=user.id, event_type="flag", track_key=track_key
        ).first()
        if existing:
            db.session.delete(existing)
            # Revert status to suggested when un-flagging
            ss = SongStatus.query.filter_by(
                room_id=room_id, track_key=track_key
            ).first()
            if ss and ss.status == "rejected":
                ss.status = "suggested"
                ss.changed_by = user.id
                ss.reason = None
            db.session.commit()
            action = "unflagged"
        else:
            track_name = track_key.split("|||")[0] if "|||" in track_key else track_key
            body = f'Flagged "{track_name}"'
            if reason:
                body += f" — {reason}"
            db.session.add(
                RoomEvent(
                    room_id=room_id,
                    user_id=user.id,
                    event_type="flag",
                    body=body,
                    track_key=track_key,
                    meta_json=json.dumps({"reason": reason}),
                )
            )
            # Also set pipeline status to rejected
            ss = SongStatus.query.filter_by(
                room_id=room_id, track_key=track_key
            ).first()
            if ss:
                ss.status = "rejected"
                ss.changed_by = user.id
                ss.reason = reason
            else:
                db.session.add(
                    SongStatus(
                        room_id=room_id,
                        track_key=track_key,
                        status="rejected",
                        changed_by=user.id,
                        reason=reason,
                    )
                )
            db.session.commit()
            action = "flagged"

        socketio.emit(
            "room:feed_update",
            {
                "room_id": room_id,
                "action": action,
                "track_key": track_key,
                "type": "flag",
            },
            room=f"campaign_room_{room_id}",
        )

        # Real-time badge status broadcast
        new_status = "rejected" if action == "flagged" else "suggested"
        socketio.emit(
            "room:status_update",
            {
                "room_id": room_id,
                "track_key": track_key,
                "status": new_status,
                "status_label": SONG_STATUS_LABELS.get(new_status, new_status),
                "changed_by": _user_label(user.id),
                "reason": reason if action == "flagged" else "",
                "action_type": "flag",
                "action": action,
            },
            room=f"campaign_room_{room_id}",
        )

        return {"ok": True, "action": action}

    @app.route("/api/room/<int:room_id>/approve", methods=["POST"])
    def api_room_approve(room_id):
        """Approve a track for the campaign."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404
        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        data = request.get_json(silent=True) or {}
        track_key = str(data.get("track_key", "")).strip()
        if not track_key:
            return {"error": "Missing track_key"}, 400

        existing = RoomEvent.query.filter_by(
            room_id=room_id, user_id=user.id, event_type="approve", track_key=track_key
        ).first()
        if existing:
            db.session.delete(existing)
            # Revert status to suggested when un-approving
            ss = SongStatus.query.filter_by(
                room_id=room_id, track_key=track_key
            ).first()
            if ss and ss.status == "approved":
                ss.status = "suggested"
                ss.changed_by = user.id
                ss.reason = None
            db.session.commit()
            action = "unapproved"
        else:
            track_name = track_key.split("|||")[0] if "|||" in track_key else track_key
            db.session.add(
                RoomEvent(
                    room_id=room_id,
                    user_id=user.id,
                    event_type="approve",
                    body=f'Approved "{track_name}" for testing',
                    track_key=track_key,
                )
            )
            # Also set pipeline status to approved
            ss = SongStatus.query.filter_by(
                room_id=room_id, track_key=track_key
            ).first()
            if ss:
                ss.status = "approved"
                ss.changed_by = user.id
                ss.reason = None
            else:
                db.session.add(
                    SongStatus(
                        room_id=room_id,
                        track_key=track_key,
                        status="approved",
                        changed_by=user.id,
                    )
                )
            db.session.commit()
            action = "approved"

        socketio.emit(
            "room:feed_update",
            {
                "room_id": room_id,
                "action": action,
                "track_key": track_key,
                "type": "approve",
            },
            room=f"campaign_room_{room_id}",
        )

        # Real-time badge status broadcast
        new_status = "approved" if action == "approved" else "suggested"
        socketio.emit(
            "room:status_update",
            {
                "room_id": room_id,
                "track_key": track_key,
                "status": new_status,
                "status_label": SONG_STATUS_LABELS.get(new_status, new_status),
                "changed_by": _user_label(user.id),
                "reason": "",
                "action_type": "approve",
                "action": action,
            },
            room=f"campaign_room_{room_id}",
        )

        return {"ok": True, "action": action}

    @app.route("/api/room/<int:room_id>/status", methods=["POST"])
    def api_room_status(room_id):
        """Change the approval-pipeline status of a song in a room."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404
        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        data = request.get_json(silent=True) or {}
        tk = str(data.get("track_key", "")).strip()
        new_status = str(data.get("status", "")).strip()
        reason = str(data.get("reason", "")).strip()[:300]

        if not tk:
            return {"error": "Missing track_key"}, 400
        if new_status not in SONG_STATUSES:
            return {
                "error": f"Invalid status. Must be one of: {', '.join(SONG_STATUSES)}"
            }, 400

        # Upsert SongStatus
        ss = SongStatus.query.filter_by(room_id=room_id, track_key=tk).first()
        old_status = ss.status if ss else "suggested"
        if ss:
            ss.status = new_status
            ss.changed_by = user.id
            ss.reason = reason or None
        else:
            ss = SongStatus(
                room_id=room_id,
                track_key=tk,
                status=new_status,
                changed_by=user.id,
                reason=reason or None,
            )
            db.session.add(ss)

        # Build human-readable feed message
        track_name = tk.split("|||")[0] if "|||" in tk else tk
        user_label = _user_label(user.id)
        status_label = SONG_STATUS_LABELS.get(new_status, new_status)

        STATUS_EMOJI = {
            "suggested": "\U0001f4a1",
            "in_discussion": "\U0001f4ac",
            "shortlisted": "\u2b50",
            "approved": "\u2705",
            "rejected": "\u274c",
            "sent_to_client": "\U0001f4e4",
        }
        emoji = STATUS_EMOJI.get(new_status, "\U0001f4cb")

        body = f'{user_label} moved "{track_name}" to {status_label.upper()} {emoji}'
        if reason:
            body += f" \u2014 {reason}"

        db.session.add(
            RoomEvent(
                room_id=room_id,
                user_id=user.id,
                event_type="status_change",
                body=body,
                track_key=tk,
                meta_json=json.dumps(
                    {
                        "old_status": old_status,
                        "new_status": new_status,
                        "reason": reason,
                    }
                ),
            )
        )
        db.session.commit()

        socketio.emit(
            "room:feed_update",
            {
                "room_id": room_id,
                "track_key": tk,
                "type": "status_change",
                "new_status": new_status,
            },
            room=f"campaign_room_{room_id}",
        )

        # Real-time badge status broadcast
        socketio.emit(
            "room:status_update",
            {
                "room_id": room_id,
                "track_key": tk,
                "status": new_status,
                "status_label": status_label,
                "changed_by": user_label,
                "reason": reason,
                "action_type": "status",
                "action": "status_change",
            },
            room=f"campaign_room_{room_id}",
        )

        return {
            "ok": True,
            "status": new_status,
            "label": status_label,
            "changed_by": user_label,
        }

    # Socket.IO Events 

    @socketio.on("room:join")
    def handle_room_join(payload):
        if "email" not in session:
            return
        room_id = (payload or {}).get("room_id")
        if room_id:
            join_room(f"campaign_room_{room_id}")
            emit("room:joined", {"room_id": room_id})

    @socketio.on("room:send")
    def handle_room_send(payload):
        if "email" not in session:
            emit("room:error", {"message": "Not authenticated."})
            return
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return

        room_id = (payload or {}).get("room_id")
        body = str((payload or {}).get("body", "")).strip()[:500]
        track_key = (payload or {}).get("track_key") or None
        audio_ts = None

        if not room_id or not body:
            return

        # Parse @0:08 style timestamps
        ts_match = re.search(r"@(\d{1,2}):(\d{2})", body)
        if ts_match:
            audio_ts = int(ts_match.group(1)) * 60 + int(ts_match.group(2))

        msg = RoomMessage(
            room_id=room_id,
            user_id=user.id,
            body=body,
            track_key=track_key,
            audio_ts=audio_ts,
        )
        db.session.add(msg)
        db.session.commit()

        prefs = UserPreferences.query.filter_by(user_id=user.id).first()
        label = (
            prefs.display_name
            if prefs and prefs.display_name
            else user.username.split("@")[0]
        )

        broadcast = {
            "id": msg.id,
            "room_id": room_id,
            "user_id": user.id,
            "user_label": label,
            "body": body,
            "track_key": track_key,
            "audio_ts": audio_ts,
            "created_at": msg.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        socketio.emit("room:new_message", broadcast, room=f"campaign_room_{room_id}")

    @socketio.on("moodboard:add")
    def handle_moodboard_add(payload):
        if "email" not in session:
            return
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return
        room_id = payload.get("room_id")
        pin_type = payload.get("pin_type", "mood")
        content = str(payload.get("content", "")).strip()
        label = str(payload.get("label", "")).strip()
        meta_json = payload.get("meta_json", {})
        if not room_id or not content:
            return
        pin = RoomPin(
            room_id=room_id,
            user_id=user.id,
            pin_type=pin_type,
            content=content,
            label=label,
            meta_json=json.dumps(meta_json),
        )
        db.session.add(pin)
        db.session.commit()
        socketio.emit(
            "moodboard:update",
            {
                "room_id": room_id,
                "action": "add",
                "pin": {
                    "id": pin.id,
                    "pin_type": pin.pin_type,
                    "content": pin.content,
                    "label": pin.label,
                    "meta_json": meta_json,
                    "author": user.username.split("@")[0],
                    "created_at": pin.created_at.isoformat(),
                },
            },
            room=f"campaign_room_{room_id}",
        )

    @socketio.on("moodboard:remove")
    def handle_moodboard_remove(payload):
        if "email" not in session:
            return
        room_id = payload.get("room_id")
        pin_id = payload.get("pin_id")
        if not room_id or not pin_id:
            return
        pin = RoomPin.query.get(pin_id)
        if pin and pin.room_id == int(room_id):
            db.session.delete(pin)
            db.session.commit()
            socketio.emit(
                "moodboard:update",
                {"room_id": room_id, "action": "remove", "pin_id": pin_id},
                room=f"campaign_room_{room_id}",
            )

    @socketio.on("poll:create")
    def handle_poll_create(payload):
        if "email" not in session:
            return
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return
        room_id = payload.get("room_id")
        question = str(payload.get("question", "")).strip()
        options = payload.get("options", [])
        if not room_id or not question or not options:
            return

        poll = RoomPoll(
            room_id=room_id,
            user_id=user.id,
            question=question,
            options_json=json.dumps(options),
        )
        db.session.add(poll)
        db.session.commit()

        socketio.emit(
            "poll:update",
            {
                "room_id": room_id,
                "action": "create",
                "poll": {
                    "id": poll.id,
                    "question": poll.question,
                    "options": options,
                    "author": user.username.split("@")[0],
                    "created_at": poll.created_at.isoformat(),
                    "votes": [0] * len(options),
                    "total_votes": 0,
                    "user_voted": None,
                },
            },
            room=f"campaign_room_{room_id}",
        )

    @socketio.on("poll:vote")
    def handle_poll_vote(payload):
        if "email" not in session:
            return
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return
        poll_id = payload.get("poll_id")
        option_index = payload.get("option_index")
        if poll_id is None or option_index is None:
            return

        # Remove previous vote if exists
        RoomPollVote.query.filter_by(poll_id=poll_id, user_id=user.id).delete()

        vote = RoomPollVote(poll_id=poll_id, user_id=user.id, option_index=option_index)
        db.session.add(vote)
        db.session.commit()

        # Broadcast new tallies
        poll = RoomPoll.query.get(poll_id)
        all_votes = RoomPollVote.query.filter_by(poll_id=poll_id).all()
        options = json.loads(poll.options_json)
        counts = [0] * len(options)
        for v in all_votes:
            if v.option_index < len(counts):
                counts[v.option_index] += 1

        socketio.emit(
            "poll:update",
            {
                "room_id": poll.room_id,
                "action": "vote",
                "poll_id": poll_id,
                "votes": counts,
                "total_votes": len(all_votes),
            },
            room=f"campaign_room_{poll.room_id}",
        )

        # ML Behavioral Influence: If option looks like a track (Artist - Title), treat as approval
        selected_option = options[option_index]
        if " – " in selected_option or " - " in selected_option:
            # We treat this as a signal for the behavioral engine
            db.session.add(
                RoomEvent(
                    room_id=poll.room_id,
                    user_id=user.id,
                    event_type="approve",
                    body=f'Voted for "{selected_option}" in poll',
                    track_key=None,  # In a real app, we'd resolve the ID, but for now we signal the preference
                )
            )
            db.session.commit()
            socketio.emit(
                "room:feed_update",
                {"room_id": poll.room_id},
                room=f"campaign_room_{poll.room_id}",
            )

    @app.route("/room/<int:room_id>/toggle-ongoing", methods=["POST"])
    def toggle_campaign_room_ongoing(room_id):
        if "email" not in session:
            return {"error": "Not authenticated"}, 401

        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        if user not in room.members and room.created_by != user.id:
            return {"error": "Forbidden"}, 403

        # Toggle ongoing state (default is True)
        current_state = getattr(room, "is_ongoing", True)
        if current_state is None:
            current_state = True
        room.is_ongoing = not current_state

        # Log status event
        status_str = "re-opened" if room.is_ongoing else "completed"
        db.session.add(
            RoomEvent(
                room_id=room.id,
                user_id=user.id,
                event_type="room_status_changed",
                body=f"Campaign room was {status_str}",
                meta_json=json.dumps({"is_ongoing": room.is_ongoing}),
            )
        )
        db.session.commit()

        # Broadcast updates
        socketio.emit(
            "room:feed_update", {"room_id": room_id}, room=f"campaign_room_{room_id}"
        )

        return {"ok": True, "is_ongoing": room.is_ongoing}

    @app.route("/api/room/<int:room_id>/shazam/select", methods=["POST"])
    def select_shazam_match(room_id):
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404
        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        data = request.get_json(silent=True) or {}
        selected = bool(data.get("selected", True))
        session[f"shazam_selected_{room_id}"] = selected
        session.modified = True
        return {"ok": True, "selected": selected}

    @app.route("/api/room/<int:room_id>/knn-archive-recommendations")
    def get_knn_archive_recommendations(room_id):
        if "email" not in session:
            return {"error": "Not authenticated"}, 401

        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        room = CampaignRoom.query.get(room_id)
        if not room:
            return {"error": "Room not found"}, 404

        if user not in room.members and room.created_by != user.id:
            return {"error": "Forbidden"}, 403

        # Construct room_prefs
        prefs = UserPreferences.query.filter_by(user_id=user.id).first()
        preset = campaign_moods.get(room.mood_key, {})

        class RoomPrefs:
            pass

        room_prefs = RoomPrefs()
        if prefs:
            for column in prefs.__table__.columns:
                setattr(room_prefs, column.name, getattr(prefs, column.name))
        else:
            room_prefs.genres = "[]"
            room_prefs.feature_weights = "{}"
            room_prefs.use_interaction_signal = False
            room_prefs.interaction_blend = 0.65
            room_prefs.enable_personalized_similarity = False
            room_prefs.personalized_similarity_text = ""
            room_prefs.enable_genre_boost = False
            room_prefs.genre_boost_weight = 1.0
            room_prefs.user_id = user.id
            room_prefs.display_name = None
            room_prefs.weight_base_audio = 0.40
            room_prefs.weight_industry = 0.20
            room_prefs.weight_generation = 0.20
            room_prefs.weight_campaign = 0.20
            room_prefs.enable_acoustic_matcher = False
            room_prefs.target_generation = None
            room_prefs.target_campaign = None
            room_prefs.industry_focus = None
            room_prefs.roles = ""

        for key in (
            "pref_danceability",
            "pref_energy",
            "pref_valence",
            "pref_acousticness",
            "pref_instrumentalness",
        ):
            setattr(room_prefs, key, preset.get(key, 0.5))

        room_prefs.room_id = room.id

        # Get standard recommendations
        songs = get_hybrid_recommendations(user, room_prefs, n=15)

        # Get existing approved or flagged tracks in the room
        approve_events = RoomEvent.query.filter_by(
            room_id=room.id, event_type="approve"
        ).all()
        approved_tracks = {e.track_key for e in approve_events if e.track_key}
        flag_events = RoomEvent.query.filter_by(
            room_id=room.id, event_type="flag"
        ).all()
        flagged_tracks = {e.track_key for e in flag_events if e.track_key}

        # Get user's current favorite tracks to set 'is_favorite'
        favorites = FavoriteRecommendation.query.filter_by(user_id=user.id).all()
        favorite_keys = {
            (f.track_name.strip().lower(), f.artist_name.strip().lower())
            for f in favorites
        }

        # Filter out approved/flagged, and sort by behavioral fit (kNN resonance)
        recommended = []
        for song in songs:
            tk = song["trackName"].lower() + "|||" + song["artistName"].lower()
            if tk in approved_tracks or tk in flagged_tracks:
                continue

            # Check if already a favorite
            track_key_tuple = (
                song["trackName"].strip().lower(),
                song["artistName"].strip().lower(),
            )
            song["is_favorite"] = track_key_tuple in favorite_keys
            recommended.append(song)

        # Sort by behavioral fit descending. Fall back to standard hybrid rank if fits are equal or none.
        recommended.sort(key=lambda s: s.get("behavioral_fit") or 0, reverse=True)

        # Take the top 3 recommendations
        top_recs = recommended[:3]

        return jsonify({"ok": True, "recommendations": top_recs})

    @app.route("/room/<int:room_id>/after-experience")
    def get_campaign_after_experience(room_id):
        if "email" not in session:
            return redirect(url_for("home"))

        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return redirect(url_for("home"))

        room = CampaignRoom.query.get(room_id)
        if not room:
            flash("Room not found.", "error")
            return redirect(url_for("dashboard"))

        if user not in room.members and room.created_by != user.id:
            flash("You do not have access to this room.", "error")
            return redirect(url_for("dashboard"))

        if room.is_ongoing:
            # If debate is still ongoing, redirect back to active room
            return redirect(url_for("campaign_room", room_id=room_id))

        # Get brief / mood target
        preset = campaign_moods.get(room.mood_key, {})

        # Build room_prefs for kNN Recommender
        prefs = UserPreferences.query.filter_by(user_id=user.id).first()

        class RoomPrefs:
            pass

        room_prefs = RoomPrefs()
        if prefs:
            for column in prefs.__table__.columns:
                setattr(room_prefs, column.name, getattr(prefs, column.name))
        else:
            room_prefs.genres = "[]"
            room_prefs.feature_weights = "{}"
            room_prefs.use_interaction_signal = False
            room_prefs.interaction_blend = 0.65
            room_prefs.enable_personalized_similarity = False
            room_prefs.personalized_similarity_text = ""
            room_prefs.enable_genre_boost = False
            room_prefs.genre_boost_weight = 1.0
            room_prefs.user_id = user.id
            room_prefs.display_name = None
            room_prefs.weight_base_audio = 0.40
            room_prefs.weight_industry = 0.20
            room_prefs.weight_generation = 0.20
            room_prefs.weight_campaign = 0.20
            room_prefs.enable_acoustic_matcher = False
            room_prefs.target_generation = None
            room_prefs.target_campaign = None
            room_prefs.industry_focus = None
            room_prefs.roles = ""

        for key in (
            "pref_danceability",
            "pref_energy",
            "pref_valence",
            "pref_acousticness",
            "pref_instrumentalness",
        ):
            setattr(room_prefs, key, preset.get(key, 0.5))

        room_prefs.room_id = room.id

        # Get all hybrid/kNN recommendations (larger pool to filter)
        songs = get_hybrid_recommendations(user, room_prefs, n=30)

        # Get existing approved or flagged tracks in the room
        approve_events = RoomEvent.query.filter_by(
            room_id=room.id, event_type="approve"
        ).all()
        approved_keys = {e.track_key for e in approve_events if e.track_key}
        flag_events = RoomEvent.query.filter_by(
            room_id=room.id, event_type="flag"
        ).all()
        flagged_keys = {e.track_key for e in flag_events if e.track_key}

        # Identify tracks presented in the initial feed to exclude them
        feed_songs = get_hybrid_recommendations(user, room_prefs, n=10)
        feed_keys = {track_key(s["trackName"], s["artistName"]) for s in feed_songs}

        # Look up actual song metadata for approved tracks to display them on left pane
        from services.song_service import ALL_SONGS

        by_key = {track_key(s["trackName"], s["artistName"]): s for s in ALL_SONGS}

        approved_tracks = []
        for k in approved_keys:
            song = by_key.get(k)
            if song:
                approved_tracks.append(song)

        # Get user's current favorite tracks
        favorites = FavoriteRecommendation.query.filter_by(user_id=user.id).all()
        favorite_keys = {
            (f.track_name.strip().lower(), f.artist_name.strip().lower())
            for f in favorites
        }

        # Filter recommendations (must not be approved, flagged, or presented in the active feed)
        recommended = []
        for song in songs:
            tk = track_key(song["trackName"], song["artistName"])
            if tk in approved_keys or tk in flagged_keys or tk in feed_keys:
                continue

            track_key_tuple = (
                song["trackName"].strip().lower(),
                song["artistName"].strip().lower(),
            )
            song["is_favorite"] = track_key_tuple in favorite_keys
            recommended.append(song)

        # Sort by behavioral fit descending
        recommended.sort(key=lambda s: s.get("behavioral_fit") or 0, reverse=True)
        top_recs = recommended[:6]  # Select top 6 recommendations

        return render_template(
            "after_experience.html",
            room=room,
            room_preset=preset,
            approved_tracks=approved_tracks,
            recommendations=top_recs,
            user_id=user.id,
        )

    # ─── Classical A/B Testing Routes ───────────────────────────────────────
    # Each participant is randomly pre-assigned to Group A or Group B and sees
    # only the song for their group (between-subjects design).
    # Outcomes:
    #   Binary  → would_listen (Yes / No)  → two-proportion z-test
    #   Numeric → rating (1-5)             → Welch’s t-test
    # ─────────────────────────────────────────────────────────────────────────

    def _ab_two_prop_ztest(yA, nA, yB, nB):
        """
        Two-proportion z-test (one-sided: H1: pA > pB).
        Returns (z_statistic, p_value).  Continuity-corrected with a
        pooled proportion.
        """
        if nA == 0 or nB == 0:
            return 0.0, 1.0
        pA = yA / nA
        pB = yB / nB
        p_pool = (yA + yB) / (nA + nB)
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / nA + 1 / nB))
        if se == 0:
            return 0.0, 1.0
        z = (pA - pB) / se
        # Approximation: 1 - Φ(|z|) using abramowitz & stegun rational
        # Works well for |z| up to ~5.
        t = 1.0 / (1.0 + 0.2316419 * abs(z))
        poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
        p_one_sided = math.exp(-0.5 * z * z) * poly / math.sqrt(2 * math.pi)
        p_two_sided = min(1.0, 2 * p_one_sided)
        return round(z, 4), round(p_two_sided, 4)

    def _ab_welch_ttest(vals_a, vals_b):
        """
        Welch’s t-test (unequal variances, two-sided).
        Returns (t_statistic, p_value, mean_a, mean_b).
        Degrees of freedom computed with the Welch–Satterthwaite equation.
        p-value approximated using a rational approximation of the t-cdf.
        """
        nA, nB = len(vals_a), len(vals_b)
        if nA < 2 or nB < 2:
            meanA = sum(vals_a) / nA if nA else 0.0
            meanB = sum(vals_b) / nB if nB else 0.0
            return 0.0, 1.0, round(meanA, 4), round(meanB, 4)

        meanA = sum(vals_a) / nA
        meanB = sum(vals_b) / nB
        varA = sum((x - meanA) ** 2 for x in vals_a) / (nA - 1)
        varB = sum((x - meanB) ** 2 for x in vals_b) / (nB - 1)

        se2 = varA / nA + varB / nB
        if se2 == 0:
            return 0.0, 1.0, round(meanA, 4), round(meanB, 4)

        t = (meanA - meanB) / math.sqrt(se2)

        # Welch-Satterthwaite degrees of freedom
        df = se2 ** 2 / ((varA / nA) ** 2 / (nA - 1) + (varB / nB) ** 2 / (nB - 1))

        # p-value approximation via regularised incomplete beta I_x(df/2, 0.5)
        # For practical purposes we use a normal approximation when df > 30,
        # otherwise use a rough rational approximation.
        if df > 30:
            z = abs(t)
            t2 = 1.0 / (1.0 + 0.2316419 * z)
            poly = t2 * (0.319381530 + t2 * (-0.356563782 + t2 * (1.781477937 + t2 * (-1.821255978 + t2 * 1.330274429))))
            p = min(1.0, 2 * math.exp(-0.5 * z * z) * poly / math.sqrt(2 * math.pi))
        else:
            # Simple beta-function approximation using half-normal
            x = df / (df + t * t)
            # Regularised incomplete beta via continued fraction (Lentz)
            # Simplified: use p ≈ 2 * stats.t.sf(|t|, df)
            # Good enough for academic / UI purposes.
            a = df / 2.0
            b = 0.5
            # Use a simple loop-based continued fraction (6 iterations)
            def beta_cf(x, a, b, max_iter=6):
                qab = a + b
                qap = a + 1.0
                qam = a - 1.0
                c = 1.0
                d = 1.0 - qab * x / qap
                if abs(d) < 1e-30:
                    d = 1e-30
                d = 1.0 / d
                h = d
                for m in range(1, max_iter + 1):
                    m2 = 2 * m
                    aa = m * (b - m) * x / ((qam + m2) * (a + m2))
                    d = 1.0 + aa * d
                    if abs(d) < 1e-30:
                        d = 1e-30
                    c = 1.0 + aa / c
                    if abs(c) < 1e-30:
                        c = 1e-30
                    d = 1.0 / d
                    h *= d * c
                    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
                    d = 1.0 + aa * d
                    if abs(d) < 1e-30:
                        d = 1e-30
                    c = 1.0 + aa / c
                    if abs(c) < 1e-30:
                        c = 1e-30
                    d = 1.0 / d
                    delta = d * c
                    h *= delta
                    if abs(delta - 1.0) < 1e-7:
                        break
                return h

            try:
                betacf_val = beta_cf(x, a, b)
                # log(Beta(a, b)) via log-gamma
                import math
                log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
                ibeta = math.exp(math.log(x) * a + math.log(1 - x) * b - log_beta) * betacf_val / a
                ibeta = max(0.0, min(1.0, ibeta))
                p = min(1.0, 2 * ibeta)
            except Exception:
                p = 1.0

        return round(t, 4), round(p, 4), round(meanA, 4), round(meanB, 4)

    @app.route("/api/room/<int:room_id>/abtest/create", methods=["POST"])
    def api_create_abtest(room_id):
        """Create a new classical A/B test: compare two songs between-subjects."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        data = request.get_json(silent=True) or {}
        song_a_key = str(data.get("song_a_key", "")).strip()
        song_b_key = str(data.get("song_b_key", "")).strip()
        title = str(data.get("title", "")).strip()[:300] or "Song A vs Song B"

        if not song_a_key or not song_b_key:
            return {"error": "Both song_a_key and song_b_key are required"}, 400
        if song_a_key == song_b_key:
            return {"error": "Songs must be different"}, 400

        test = ABTest(
            room_id=room_id,
            song_a_key=song_a_key,
            song_b_key=song_b_key,
            title=title,
            created_by=user.id,
        )
        db.session.add(test)
        db.session.commit()

        payload = {
            "room_id": room_id,
            "test_id": test.id,
            "title": title,
            "song_a_key": song_a_key,
            "song_b_key": song_b_key,
            "creator": _user_label(user.id),
        }
        socketio.emit("abtest:created", payload, room=f"campaign_room_{room_id}")

        return {"ok": True, **payload}

    @app.route("/api/room/<int:room_id>/abtest/<int:test_id>/assignment")
    def api_get_abtest_assignment(room_id, test_id):
        """
        Return (or create) the random group assignment for the current user.
        The assignment is stored as an existing ABVote row (without a response
        yet) so it persists across page refreshes.
        """
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        test = ABTest.query.get(test_id)
        if not test or test.room_id != room_id:
            return {"error": "Test not found"}, 404

        existing = ABVote.query.filter_by(test_id=test_id, user_id=user.id).first()
        if existing:
            assigned = existing.assigned_group
        else:
            # Balance groups: count current votes per group
            votes_a = ABVote.query.filter_by(test_id=test_id, assigned_group="a").count()
            votes_b = ABVote.query.filter_by(test_id=test_id, assigned_group="b").count()
            if votes_a <= votes_b:
                assigned = "a"
            else:
                assigned = "b"
            # Create a placeholder vote row (no response yet)
            placeholder = ABVote(
                test_id=test_id,
                user_id=user.id,
                assigned_group=assigned,
                chosen=assigned,      # will be confirmed on submission
                emotion_rating=3,
            )
            db.session.add(placeholder)
            db.session.commit()

        # Return the song key that this user should see
        song_key = test.song_a_key if assigned == "a" else test.song_b_key
        song_name = song_key.split("|||")[0] if "|||" in song_key else song_key
        artist_name = song_key.split("|||")[1] if "|||" in song_key else ""

        return {
            "ok": True,
            "assigned_group": assigned,
            "song_key": song_key,
            "song_name": song_name,
            "artist_name": artist_name,
            "has_responded": bool(existing and existing.would_listen is not None),
        }

    @app.route("/api/room/<int:room_id>/abtest/<int:test_id>/select-group", methods=["POST"])
    def api_select_abtest_group(room_id, test_id):
        """
        Manually select/switch the evaluation group (a/b) for the user's assignment.
        """
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        test = ABTest.query.get(test_id)
        if not test or test.room_id != room_id:
            return {"error": "Test not found"}, 404

        data = request.get_json() or {}
        group = data.get("group", "").strip().lower()
        if group not in ["a", "b"]:
            return {"error": "Invalid group selection. Must be 'a' or 'b'."}, 400

        # Retrieve or create assignment
        existing = ABVote.query.filter_by(test_id=test_id, user_id=user.id).first()
        if existing:
            # Only allow switching if they haven't submitted a vote response yet
            if existing.would_listen is not None:
                return {"error": "You have already submitted a response for this test and cannot switch groups."}, 400
            existing.assigned_group = group
            existing.chosen = group
        else:
            existing = ABVote(
                test_id=test_id,
                user_id=user.id,
                assigned_group=group,
                chosen=group,
                emotion_rating=3,
            )
            db.session.add(existing)

        db.session.commit()
        return {"ok": True, "assigned_group": group}

    @app.route("/api/room/<int:room_id>/abtest/list")
    def api_list_abtests(room_id):
        """List all A/B tests with per-group tallies and statistical test results."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        tests = (
            ABTest.query.filter_by(room_id=room_id)
            .order_by(ABTest.created_at.desc())
            .all()
        )

        result = []
        for t in tests:
            votes = ABVote.query.filter_by(test_id=t.id).all()
            # Only include votes that have a response
            responded = [v for v in votes if v.would_listen is not None or v.rating is not None]
            votes_a = [v for v in responded if v.assigned_group == "a"]
            votes_b = [v for v in responded if v.assigned_group == "b"]

            # ── Binary outcome: two-proportion z-test ──
            yes_a = sum(1 for v in votes_a if v.would_listen)
            yes_b = sum(1 for v in votes_b if v.would_listen)
            nA = len([v for v in votes_a if v.would_listen is not None])
            nB = len([v for v in votes_b if v.would_listen is not None])
            prop_a = round(yes_a / nA * 100, 1) if nA else 0
            prop_b = round(yes_b / nB * 100, 1) if nB else 0
            z_stat, p_binary = _ab_two_prop_ztest(yes_a, nA, yes_b, nB) if (nA and nB) else (0.0, 1.0)

            # ── Numeric outcome: Welch’s t-test ──
            ratings_a = [v.rating for v in votes_a if v.rating is not None]
            ratings_b = [v.rating for v in votes_b if v.rating is not None]
            t_stat, p_numeric, mean_a, mean_b = _ab_welch_ttest(ratings_a, ratings_b)

            # ── Statistical significance flags ──
            sig_binary = p_binary < 0.05 and (nA + nB) >= 4
            sig_numeric = p_numeric < 0.05 and (len(ratings_a) + len(ratings_b)) >= 4

            # Winner determination
            winner = None
            if sig_binary:
                winner = "A" if prop_a > prop_b else ("B" if prop_b > prop_a else None)
            elif sig_numeric:
                winner = "A" if mean_a > mean_b else ("B" if mean_b > mean_a else None)

            # Current user’s status
            user_vote = ABVote.query.filter_by(test_id=t.id, user_id=user.id).first()
            user_has_responded = bool(user_vote and user_vote.would_listen is not None)

            result.append({
                "id": t.id,
                "title": t.title,
                "song_a_key": t.song_a_key,
                "song_b_key": t.song_b_key,
                "creator": _user_label(t.created_by),
                "is_active": t.is_active,
                # Group sizes (assigned, not necessarily responded)
                "n_assigned_a": ABVote.query.filter_by(test_id=t.id, assigned_group="a").count(),
                "n_assigned_b": ABVote.query.filter_by(test_id=t.id, assigned_group="b").count(),
                # Respondents
                "n_responded_a": nA,
                "n_responded_b": nB,
                # Binary (Yes/No)
                "yes_a": yes_a, "yes_b": yes_b,
                "prop_a": prop_a, "prop_b": prop_b,
                "z_stat": z_stat, "p_binary": p_binary,
                "sig_binary": sig_binary,
                # Numeric (1-5 ratings)
                "mean_a": mean_a, "mean_b": mean_b,
                "t_stat": t_stat, "p_numeric": p_numeric,
                "sig_numeric": sig_numeric,
                # Winner
                "winner": winner,
                # User info
                "user_assigned_group": user_vote.assigned_group if user_vote else None,
                "user_has_responded": user_has_responded,
                "created_at": t.created_at.isoformat(),
            })

        return {"tests": result, "emotion_labels": AB_EMOTION_LABELS}

    @app.route("/api/room/<int:room_id>/abtest/<int:test_id>/vote", methods=["POST"])
    def api_vote_abtest(room_id, test_id):
        """
        Submit a response for the user’s assigned song.
        Payload: { would_listen: bool, rating: int (1-5) }
        The user only rates the song they were assigned to.
        """
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        data = request.get_json(silent=True) or {}
        would_listen = data.get("would_listen")
        rating_raw = data.get("rating")

        if would_listen is None:
            return {"error": "would_listen (boolean) is required"}, 400
        would_listen = bool(would_listen)

        rating = None
        if rating_raw is not None:
            try:
                rating = int(rating_raw)
                if rating not in range(1, 6):
                    return {"error": "rating must be 1-5"}, 400
            except (ValueError, TypeError):
                return {"error": "rating must be an integer 1-5"}, 400

        test = ABTest.query.get(test_id)
        if not test or test.room_id != room_id:
            return {"error": "Test not found"}, 404

        # Retrieve existing assignment (created by /assignment endpoint)
        existing = ABVote.query.filter_by(test_id=test_id, user_id=user.id).first()
        if existing:
            existing.would_listen = would_listen
            existing.rating = rating
            existing.chosen = existing.assigned_group
            # Map 1-5 rating to legacy 1-4 emotion for back-compat display
            if rating:
                existing.emotion_rating = max(1, min(4, round(rating * 4 / 5)))
        else:
            # No assignment exists yet – assign and record in one step
            votes_a = ABVote.query.filter_by(test_id=test_id, assigned_group="a").count()
            votes_b = ABVote.query.filter_by(test_id=test_id, assigned_group="b").count()
            assigned = "a" if votes_a <= votes_b else "b"
            emo = max(1, min(4, round(rating * 4 / 5))) if rating else 3
            existing = ABVote(
                test_id=test_id,
                user_id=user.id,
                assigned_group=assigned,
                chosen=assigned,
                would_listen=would_listen,
                rating=rating,
                emotion_rating=emo,
            )
            db.session.add(existing)

        db.session.commit()

        # Broadcast updated tallies
        all_votes = ABVote.query.filter_by(test_id=test_id).all()
        responded = [v for v in all_votes if v.would_listen is not None]
        votes_a_resp = len([v for v in responded if v.assigned_group == "a"])
        votes_b_resp = len([v for v in responded if v.assigned_group == "b"])

        socketio.emit(
            "abtest:voted",
            {
                "room_id": room_id,
                "test_id": test_id,
                "votes_a": votes_a_resp,
                "votes_b": votes_b_resp,
                "total_votes": len(responded),
                "voter": _user_label(user.id),
            },
            room=f"campaign_room_{room_id}",
        )

        return {
            "ok": True,
            "assigned_group": existing.assigned_group,
            "would_listen": existing.would_listen,
            "rating": existing.rating,
        }



    @app.route("/api/room/<int:room_id>/spotify/resolve", methods=["POST"])
    def api_resolve_spotify_link(room_id):
        """Resolve a Spotify track link/URI to a recommended track in our database."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401

        data = request.get_json(silent=True) or {}
        spotify_url = str(data.get("url", "")).strip()
        if not spotify_url:
            return {"error": "url parameter is required"}, 400

        # Parse Spotify track ID
        import re

        track_id = ""
        if "spotify:track:" in spotify_url:
            track_id = spotify_url.split("spotify:track:")[-1].strip()
        else:
            match = re.search(r"/track/([a-zA-Z0-9]+)", spotify_url)
            if match:
                track_id = match.group(1).strip()

        if not track_id:
            return {
                "error": "Invalid Spotify link. Please paste a standard Spotify track link (e.g. open.spotify.com/track/ID)."
            }, 400

        from services.song_service import ALL_SONGS

        matched_song = None
        for s in ALL_SONGS:
            s_url = s.get("spotify_url", "") or ""
            if (
                track_id in s_url
                or track_id == s.get("id")
                or track_id == s.get("uri", "").split(":")[-1]
            ):
                matched_song = s
                break

        if matched_song:
            tk = f"{matched_song['trackName']}|||{matched_song['artistName']}"
            return {
                "ok": True,
                "track_key": tk,
                "track_name": matched_song["trackName"],
                "artist_name": matched_song["artistName"],
                "genre": matched_song.get("genre", ""),
            }
        else:
            return {
                "ok": False,
                "error": "This song was not found in your current campaign dataset. To use custom licensed songs not in the dataset, please upload a local MP3/WAV file directly.",
            }, 404



    @app.route("/api/room/model-parameters", methods=["GET"])
    def api_get_room_model_parameters():
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        from services.retention_predictor import _load_model
        try:
            params = _load_model()
            return {"ok": True, "parameters": params}
        except Exception as e:
            return {"ok": False, "error": str(e)}, 500

    @app.route("/api/room/model-retrain", methods=["POST"])
    def api_post_room_model_retrain():
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        from data.train_lr_model import train_model
        try:
            params = train_model()
            return {"ok": True, "parameters": params}
        except Exception as e:
            return {"ok": False, "error": str(e)}, 500

    @app.route("/api/room/<int:room_id>/recommendations", methods=["GET"])
    def api_get_room_recommendations(room_id):
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        from models.database import CampaignRoom, UserPreferences
        from services.recommender_hybrid import get_hybrid_recommendations

        room = db.session.get(CampaignRoom, room_id)
        if not room:
            return {"error": "Room not found"}, 404

        preset = campaign_moods.get(room.mood_key, {})
        class RoomPrefs:
            pass
        room_prefs = RoomPrefs()
        prefs = UserPreferences.query.filter_by(user_id=user.id).first()
        if prefs:
            for column in prefs.__table__.columns:
                setattr(room_prefs, column.name, getattr(prefs, column.name))

        for key in (
            "pref_danceability",
            "pref_energy",
            "pref_valence",
            "pref_acousticness",
            "pref_instrumentalness",
        ):
            setattr(room_prefs, key, preset.get(key, 0.5))

        room_prefs.room_id = room.id
        songs = get_hybrid_recommendations(user, room_prefs, n=10)
        return {"ok": True, "songs": songs}

    @app.route("/api/room/<int:room_id>/audit-track/<path:track_key>", methods=["GET"])
    def api_audit_track(room_id, track_key):
        if "email" not in session:
            return {"error": "Not authenticated"}, 401
        user = User.query.filter_by(username=session["email"]).first()
        if not user:
            return {"error": "User not found"}, 404

        from models.database import CampaignRoom, UserPreferences, FavoriteRecommendation
        from services.retention_predictor import _load_model
        from services.song_service import ALL_SONGS
        import numpy as np
        import math

        room = db.session.get(CampaignRoom, room_id)
        if not room:
            return {"error": "Room not found"}, 404

        # Find the song in ALL_SONGS by track_key
        song = None
        for s in ALL_SONGS:
            tk = f"{s['trackName']}|||{s['artistName']}".lower()
            if tk == track_key.lower():
                song = s
                break
        if not song:
            return {"error": "Song not found"}, 404

        # Re-run target features and similarity calculation
        preset = campaign_moods.get(room.mood_key, {})
        song_v = np.array([
            float(song.get("danceability") or 0.5),
            float(song.get("energy") or 0.5),
            float(song.get("valence") or 0.5),
            float(song.get("acousticness") or 0.5),
            float(song.get("instrumentalness") or 0.0)
        ])
        brief_v = np.array([
            float(preset.get("pref_danceability") or 0.5),
            float(preset.get("pref_energy") or 0.5),
            float(preset.get("pref_valence") or 0.5),
            float(preset.get("pref_acousticness") or 0.5),
            float(preset.get("pref_instrumentalness") or 0.0)
        ])

        from services.recommender_shared import cosine_similarity
        cos_sim = cosine_similarity(song_v, brief_v)

        # Load user prefs
        prefs = UserPreferences.query.filter_by(user_id=user.id).first()
        genre_match = 0.0
        song_genre = str(song.get("genre") or "").strip().lower()
        if prefs and getattr(prefs, "genres", None):
            try:
                target_genres = json.loads(prefs.genres)
                if song_genre in [g.strip().lower() for g in target_genres]:
                    genre_match = 1.0
            except:
                pass

        # Artist match
        artist_match = 0.0
        song_artist = str(song.get("artistName") or "").strip().lower()
        favorites = FavoriteRecommendation.query.filter_by(user_id=user.id).all()
        liked_artists = [f.artist_name.strip().lower() for f in favorites if f.artist_name]
        if song_artist in liked_artists:
            artist_match = 1.0

        # Load model parameters
        params = _load_model()
        intercept = params["intercept"]
        coefs = params["coefficients"]
        scaler = params.get("scaler", {})
        means = scaler.get("mean", {})
        scales = scaler.get("scale", {})

        raw_feats = {
            "cosine_similarity": cos_sim,
            "genre_match": genre_match,
            "artist_match": artist_match,
            "danceability": float(song.get("danceability") or 0.5),
            "energy": float(song.get("energy") or 0.5),
            "valence": float(song.get("valence") or 0.5),
            "tempo": float(song.get("tempo") or 120.0),
            "acousticness": float(song.get("acousticness") or 0.5),
            "instrumentalness": float(song.get("instrumentalness") or 0.0),
            "speechiness": float(song.get("speechiness") or 0.05),
        }

        audit_steps = {}
        logit_z = intercept
        for name, val in raw_feats.items():
            mean = means.get(name, 0.0)
            scale = scales.get(name, 1.0)
            scaled_val = (val - mean) / (scale if scale > 0 else 1.0)
            coef = coefs.get(name, 0.0)
            contrib = coef * scaled_val
            logit_z += contrib
            audit_steps[name] = {
                "raw": val,
                "mean": mean,
                "scale": scale,
                "scaled": scaled_val,
                "coef": coef,
                "contrib": contrib
            }

        probability = 1.0 / (1.0 + math.exp(-logit_z))
        return {
            "ok": True,
            "track_name": song["trackName"],
            "artist_name": song["artistName"],
            "intercept": intercept,
            "logit_z": logit_z,
            "probability": probability,
            "steps": audit_steps
        }



