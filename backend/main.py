import os
from statistics import pvariance

from flask import Flask, render_template, session, request, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room
import re
import json
from models.database import (
    db,
    User,
    UserPreferences,
    MoodSession,
    FriendMessage,
    CampaignRoom,
    init_db,
    setup_database,
    FavoriteRecommendation,
    ABTest,
    ABVote,
    AB_EMOTION_LABELS,
)

try:
    from routes.friend_routes import register_collaborator_routes
    from routes.recommendation_routes import register_recommendation_routes
    from routes.social_routes import register_social_routes
    from routes.campaign_routes import register_campaign_routes
except ModuleNotFoundError:
    from backend.routes.friend_routes import register_collaborator_routes
    from backend.routes.recommendation_routes import register_recommendation_routes
    from backend.routes.social_routes import register_social_routes
    from backend.routes.campaign_routes import register_campaign_routes
try:
    from data.train_lr_model import train_model
except ModuleNotFoundError:
    from backend.data.train_lr_model import train_model
from services.song_service import (
    AUDIO_FEATURES,
    AVAILABLE_GENRES,
    get_saved_genres,
    ALL_SONGS,
)
from services.favorites_service import (
    get_favorite_recommendation_keys,
    get_favorite_recommendations,
)
from services.mood_translation import build_mood_preferences, parse_creative_notes_nlp
from services.music_recommendation_service import (
    get_feature_weight_controls,
    get_feature_weight_values,
    get_hybrid_recommendations,
)
from services.social_service import (
    get_community_recommendations,
    get_social_sidebar_data,
    get_full_social_data,
    are_collaborators,
)

_backend = os.path.dirname(os.path.abspath(__file__))
_frontend = os.path.join(_backend, "..", "frontend")
app = Flask(
    __name__,
    template_folder=os.path.join(_frontend, "templates"),
    static_folder=os.path.join(_frontend, "static"),
    instance_path=os.path.join(_backend, "instance"),
)
app.secret_key = "your_secret_key"  # what is this
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# config sql alchemy to work with flask
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///user.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = (
    False  # we don't want to track modifications
)

# Performance: cache static files for 1 hour in browser (avoids re-downloading CSS/JS/SVG)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600

# Performance: Jinja2 bytecode cache to avoid re-parsing large templates on every request
import tempfile
from jinja2 import FileSystemBytecodeCache as _JBC
_jinja_cache_dir = os.path.join(_backend, "instance", "__jinja_cache__")
os.makedirs(_jinja_cache_dir, exist_ok=True)
app.jinja_env.auto_reload = app.debug if hasattr(app, "debug") else True
app.jinja_env.bytecode_cache = _JBC(directory=_jinja_cache_dir)

# Timezone synchronization: UTC+3 (EEST)
from datetime import timedelta


@app.template_filter("eest")
def format_eest(dt, fmt="%b %d, %H:%M"):
    if not dt:
        return ""
    # Add 3 hours to UTC stored time
    eest_time = dt + timedelta(hours=3)
    return eest_time.strftime(fmt)


# REGEX validation
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
INVALID_EMAIL_WARNING = (
    "Warning: enter a valid email address (example: name@email.com)."
)


RISK_FEATURE_KEYS = (
    "danceability",
    "energy",
    "valence",
    "acousticness",
    "instrumentalness",
)

# --- Campaign mood presets for marketing teams ---
CAMPAIGN_MOODS = {
    "viral_trend": {
        "label": "Viral & Trendy (TikTok/Reels)",
        "emoji": "📱",
        "color": "#ec4899",
        "desc": "Catchy, fast-paced, high-danceability — perfect for social challenges and fast scroll-stopping.",
        "pref_danceability": 0.95,
        "pref_energy": 0.92,
        "pref_valence": 0.80,
        "pref_acousticness": 0.02,
        "pref_instrumentalness": 0.01,
    },
    "ugc_authentic": {
        "label": "UGC & Authentic",
        "emoji": "🤳",
        "color": "#14b8a6",
        "desc": "Lo-fi, approachable, relatable — feels like a real person made it, great for native social ads.",
        "pref_danceability": 0.60,
        "pref_energy": 0.45,
        "pref_valence": 0.65,
        "pref_acousticness": 0.75,
        "pref_instrumentalness": 0.05,
    },
    "upbeat_launch": {
        "label": "Upbeat Product Launch",
        "emoji": "🚀",
        "color": "#f59e0b",
        "desc": "High energy, positive, danceable — perfect for product reveals and launch videos.",
        "pref_danceability": 0.85,
        "pref_energy": 0.88,
        "pref_valence": 0.82,
        "pref_acousticness": 0.05,
        "pref_instrumentalness": 0.05,
    },
    "corporate_trust": {
        "label": "Corporate Trust",
        "emoji": "🏢",
        "color": "#0891b2",
        "desc": "Clean, professional, mid-energy — investor decks, brand films, B2B ads.",
        "pref_danceability": 0.30,
        "pref_energy": 0.35,
        "pref_valence": 0.55,
        "pref_acousticness": 0.40,
        "pref_instrumentalness": 0.80,
    },
    "summer_campaign": {
        "label": "Summer Campaign",
        "emoji": "☀️",
        "color": "#f97316",
        "desc": "Bright, warm, feel-good — seasonal promos, outdoor lifestyle, travel.",
        "pref_danceability": 0.80,
        "pref_energy": 0.85,
        "pref_valence": 0.90,
        "pref_acousticness": 0.15,
        "pref_instrumentalness": 0.02,
    },
    "holiday_warmth": {
        "label": "Holiday & Warmth",
        "emoji": "🎄",
        "color": "#dc2626",
        "desc": "Nostalgic, acoustic, warm — holiday campaigns, family-oriented brands.",
        "pref_danceability": 0.35,
        "pref_energy": 0.25,
        "pref_valence": 0.70,
        "pref_acousticness": 0.85,
        "pref_instrumentalness": 0.20,
    },
    "luxury_elegance": {
        "label": "Luxury & Elegance",
        "emoji": "💎",
        "color": "#8b5cf6",
        "desc": "Sophisticated, slow, instrumental — premium brands, fashion, fine dining.",
        "pref_danceability": 0.15,
        "pref_energy": 0.20,
        "pref_valence": 0.35,
        "pref_acousticness": 0.70,
        "pref_instrumentalness": 0.90,
    },
    "youth_energy": {
        "label": "Youth & Energy",
        "emoji": "⚡",
        "color": "#ef4444",
        "desc": "Fast, loud, Gen-Z — streetwear, gaming, sports, hype videos.",
        "pref_danceability": 0.90,
        "pref_energy": 0.95,
        "pref_valence": 0.60,
        "pref_acousticness": 0.01,
        "pref_instrumentalness": 0.05,
    },
    "emotional_story": {
        "label": "Emotional Storytelling",
        "emoji": "🎬",
        "color": "#6366f1",
        "desc": "Cinematic, moving, dramatic — brand stories, cause campaigns, documentaries.",
        "pref_danceability": 0.10,
        "pref_energy": 0.25,
        "pref_valence": 0.20,
        "pref_acousticness": 0.75,
        "pref_instrumentalness": 0.65,
    },
    "bold_disruptive": {
        "label": "Bold & Disruptive",
        "emoji": "🔥",
        "color": "#b91c1c",
        "desc": "Aggressive, edgy, loud — challenger brands, tech startups, bold campaigns.",
        "pref_danceability": 0.55,
        "pref_energy": 0.98,
        "pref_valence": 0.10,
        "pref_acousticness": 0.01,
        "pref_instrumentalness": 0.35,
    },
    "calm_professional": {
        "label": "Calm & Professional",
        "emoji": "🍃",
        "color": "#10b981",
        "desc": "Relaxed, focused, clean — explainer videos, SaaS demos, webinars.",
        "pref_danceability": 0.25,
        "pref_energy": 0.20,
        "pref_valence": 0.50,
        "pref_acousticness": 0.55,
        "pref_instrumentalness": 0.85,
    },
}

CAMPAIGN_OBJECTIVES = [
    {
        "value": "awareness",
        "label": "Brand Awareness",
        "hint": "Broad reach, recall, and discovery.",
    },
    {
        "value": "engagement",
        "label": "Social Engagement",
        "hint": "Likes, comments, shares, and viral potential.",
    },
    {
        "value": "ugc",
        "label": "User-Generated Content",
        "hint": "Authentic, relatable, community-driven content.",
    },
    {
        "value": "excitement",
        "label": "Launch Excitement",
        "hint": "High-attention launch energy and momentum.",
    },
    {
        "value": "conversion",
        "label": "Direct Response / Conversion",
        "hint": "Clear action, urgency, and performance marketing.",
    },
    {
        "value": "nostalgia",
        "label": "Nostalgia",
        "hint": "Warm, familiar, and emotionally resonant.",
    },
    {
        "value": "trust",
        "label": "Trust & Authority",
        "hint": "Calm, credible, and brand-safe.",
    },
]

CAMPAIGN_PLATFORMS = [
    {"value": "tiktok", "label": "TikTok"},
    {"value": "instagram_reel", "label": "Instagram Reel"},
    {"value": "youtube_shorts", "label": "YouTube Shorts"},
    {"value": "social_ad", "label": "Social Media Ad (FB/IG/X)"},
    {"value": "web_video", "label": "Web/YouTube Pre-roll Video"},
    {"value": "tv_ad", "label": "Broadcast TV Ad"},
    {"value": "in_store", "label": "In-store Playlist"},
    {"value": "podcast", "label": "Podcast / Audio Ad"},
]

CAMPAIGN_ENERGY_LEVELS = [
    {"value": "viral", "label": "Viral & Fast-paced"},
    {"value": "energetic", "label": "Energetic & Upbeat"},
    {"value": "happy", "label": "Happy & Feel-good"},
    {"value": "relaxed", "label": "Relaxed & Chill"},
    {"value": "emotional", "label": "Emotional & Cinematic"},
]

init_db(app)
register_collaborator_routes(app)
register_recommendation_routes(app)
register_social_routes(app, socketio)
register_campaign_routes(app, socketio, CAMPAIGN_MOODS)


def is_valid_email(value):
    return bool(EMAIL_REGEX.fullmatch(value))


def render_auth_page(
    error=None, success=None, email_value="", register_email_warning=None
):
    return render_template(
        "index.html",
        error=error,
        success=success,
        email_value=email_value,
        register_email_warning=register_email_warning,
    )


# Routes
@app.route("/")
def home():
    return render_auth_page()  # this is in the html


# Login
@app.route("/login", methods=["POST"])  # sending info
def login():
    # collect info from the form
    email = request.form["email"].strip().lower()
    password = request.form["password"]

    if not is_valid_email(email):
        return render_auth_page(error=INVALID_EMAIL_WARNING, email_value=email)

    # Stored in `username` column for DB compatibility.
    user = User.query.filter_by(username=email).first()
    if user and user.check_password(password):  # if these come true
        session["email"] = user.username  # a unique registration session
        return redirect(url_for("dashboard"))  # where we send the user
    else:
        return render_auth_page(error="Invalid email or password", email_value=email)
    # we use an object
    # check if it's in the db/ login

    # otherwise show homepage


# Register
@app.route("/register", methods=["POST"])
def register():
    email = request.form["email"].strip().lower()
    password = request.form["password"]

    if not is_valid_email(email):
        return render_auth_page(error=INVALID_EMAIL_WARNING, email_value=email)

    # Stored in `username` column for DB compatibility.
    user = User.query.filter_by(username=email).first()
    if user:  # if the user is true, already in the db
        return render_auth_page(
            error="Email already registered",
            email_value=email,
            register_email_warning="This email is already taken. Try logging in or use another email.",
        )
    else:
        new_user = User(username=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return render_auth_page(
            success="Account created. Please log in.", email_value=email
        )


def _safe_float(song, key, default=0.0):
    try:
        return float(song.get(key, default))
    except Exception:
        return default


def _compute_demo_breakdown(targets, industry_focus, genre_focus=None):
    # targets: dict of audio feature targets (danceability, energy, tempo, valence)
    # tempo is in BPM (60-200), normalize to 0-1 for distance calculation
    rows = []
    seen_songs = set()  # Track unique songs by (trackName, artistName)
    industry = (industry_focus or "").strip().lower()
    genre = (genre_focus or "").strip().lower()

    for song in ALL_SONGS:
        # Skip duplicate songs
        song_id = (song.get("trackName", ""), song.get("artistName", ""))
        if song_id in seen_songs:
            continue
        seen_songs.add(song_id)

        # Calculate audio feature distance
        audio_vals = []

        # Danceability (0-1)
        if "danceability" in targets:
            s = _safe_float(song, "danceability", 0.5)
            audio_vals.append(max(0.0, 1.0 - abs(s - targets["danceability"])))

        # Energy (0-1)
        if "energy" in targets:
            s = _safe_float(song, "energy", 0.5)
            audio_vals.append(max(0.0, 1.0 - abs(s - targets["energy"])))

        # Tempo (BPM 60-200, normalize to 0-1)
        if "tempo" in targets:
            s = _safe_float(song, "tempo", 120.0)
            # Normalize song tempo to 0-1 scale (60-200 BPM range)
            s_norm = max(0.0, min(1.0, (s - 60) / 140.0))
            t_norm = max(0.0, min(1.0, (targets["tempo"] - 60) / 140.0))
            audio_vals.append(max(0.0, 1.0 - abs(s_norm - t_norm)))

        # Valence (0-1)
        if "valence" in targets:
            s = _safe_float(song, "valence", 0.5)
            audio_vals.append(max(0.0, 1.0 - abs(s - targets["valence"])))

        audience_fit = sum(audio_vals) / (len(audio_vals) or 1)

        # Genre fit: high if genre token appears in song genre
        song_genre = (song.get("genre") or "").lower()
        if genre and genre in song_genre:
            genre_fit = 0.9
        elif genre:
            genre_fit = 0.45
        else:
            genre_fit = 0.6

        # Industry fit: high if industry token appears in song genre
        if industry and industry in song_genre:
            industry_fit = 0.9
        elif industry:
            industry_fit = 0.45
        else:
            industry_fit = 0.6

        # Combined fit: weighted average of all signals
        fit_score = 0.5 * audience_fit + 0.25 * genre_fit + 0.25 * industry_fit
        rows.append(
            {
                "trackName": song.get("trackName"),
                "artistName": song.get("artistName"),
                "genre": song.get("genre"),
                "audience_fit": round(audience_fit, 2),
                "industry_fit": round(industry_fit, 2),
                "fit_score": round(fit_score, 2),
            }
        )

        # Stop once we have enough unique songs
        if len(rows) >= 12:
            break

    rows.sort(key=lambda r: r["fit_score"], reverse=True)  # high fit first
    return rows[:12]





@socketio.on("connect")
def handle_socket_connect():
    if "email" not in session:
        return False

    user = User.query.filter_by(username=session["email"]).first()
    if not user:
        return False

    join_room(f"user_{user.id}")
    emit("chat:connected", {"ok": True, "user_id": user.id})


@socketio.on("chat:send")
def handle_socket_send_message(payload):
    if "email" not in session:
        emit("chat:error", {"message": "Not authenticated."})
        return

    current_user = User.query.filter_by(username=session["email"]).first()
    if not current_user:
        emit("chat:error", {"message": "User not found."})
        return

    try:
        collaborator_id = int((payload or {}).get("collaborator_id"))
    except Exception:
        collaborator_id = None

    body = str((payload or {}).get("body", "")).strip()[:500]
    if not collaborator_id or not body:
        emit("chat:error", {"message": "Write a message before sending."})
        return

    if not are_collaborators(current_user.id, collaborator_id):
        emit(
            "chat:error", {"message": "You can only chat with accepted collaborators."}
        )
        return

    collaborator_user = User.query.get(collaborator_id)
    if not collaborator_user:
        emit("chat:error", {"message": "Recipient not found."})
        return

    message = FriendMessage(
        sender_id=current_user.id, receiver_id=collaborator_id, body=body
    )
    db.session.add(message)
    db.session.commit()

    sender_label = current_user.username.split("@")[0]
    sender_payload = {
        "collaborator_id": collaborator_id,
        "body": body,
        "direction": "You",
        "sender_id": current_user.id,
        "receiver_id": collaborator_id,
        "sender_label": sender_label,
        "message_id": message.id,
    }
    receiver_payload = {
        "collaborator_id": current_user.id,
        "body": body,
        "direction": sender_label,
        "sender_id": current_user.id,
        "receiver_id": collaborator_id,
        "sender_label": sender_label,
        "message_id": message.id,
    }

    socketio.emit("chat:new_message", sender_payload, room=f"user_{current_user.id}")  # type: ignore
    socketio.emit("chat:new_message", receiver_payload, room=f"user_{collaborator_id}")  # type: ignore


@app.route("/demo", methods=["GET", "POST"])
def demo():
    # simple public demo: accept slider values and show top low-risk tracks
    if request.method == "POST":
        try:
            targets = {
                "danceability": float(request.form.get("danceability", 0.5)),
                "energy": float(request.form.get("energy", 0.5)),
                "tempo": float(request.form.get("tempo", 120.0)),
                "valence": float(request.form.get("valence", 0.5)),
            }
        except Exception:
            targets = {
                "danceability": 0.5,
                "energy": 0.5,
                "tempo": 120.0,
                "valence": 0.5,
            }

        genre_focus = request.form.get("genre", "").strip()
        industry_focus = request.form.get("industry_focus", "").strip()

        breakdown = _compute_demo_breakdown(targets, industry_focus, genre_focus)

        return render_template(
            "demo.html",
            targets=targets,
            genre=genre_focus,
            industry_focus=industry_focus,
            breakdown=breakdown,
        )

    # GET: show a small explanation page
    return render_template("demo.html", targets=None, breakdown=None)


def seed_demo_sandbox_data(user):
    """Seed the database with high-quality collaborative music supervision data
    for the demo sandbox user (demo.supervisor@gmail.com).
    """
    from models.database import (
        db,
        CampaignRoom,
        FavoriteRecommendation,
        SongStatus,
        ABTest,
        ABVote,
        RoomMessage,
        RoomReaction,
        RoomPin,
        RoomPoll,
        RoomPollVote,
        RoomEvent,
        FriendRequest,
        FriendMessage,
        UserInteractionLog,
    )

    # 1. Ensure Sofia Hart exists as a collaborator for campaign discussions
    sofia = User.query.filter_by(username="sofia.hart@gmail.com").first()
    if not sofia:
        sofia = User(username="sofia.hart@gmail.com")
        sofia.set_password("123")
        db.session.add(sofia)
        db.session.commit()

    sofia_prefs = UserPreferences.query.filter_by(user_id=sofia.id).first()
    if not sofia_prefs:
        sofia_prefs = UserPreferences(
            user_id=sofia.id, display_name="Sofia Hart", industry_focus="Content Lead"
        )
        db.session.add(sofia_prefs)
        db.session.commit()

    # Ensure Alex Mercer exists as a supervisor collaborator
    alex = User.query.filter_by(username="alex.mercer@gmail.com").first()
    if not alex:
        alex = User(username="alex.mercer@gmail.com")
        alex.set_password("123")
        db.session.add(alex)
        db.session.commit()

    alex_prefs = UserPreferences.query.filter_by(user_id=alex.id).first()
    if not alex_prefs:
        alex_prefs = UserPreferences(
            user_id=alex.id,
            display_name="Alex Mercer",
            industry_focus="Music Supervisor",
        )
        db.session.add(alex_prefs)
        db.session.commit()

    # Ensure Emma Stone exists as a producer collaborator
    emma = User.query.filter_by(username="emma.stone@gmail.com").first()
    if not emma:
        emma = User(username="emma.stone@gmail.com")
        emma.set_password("123")
        db.session.add(emma)
        db.session.commit()

    emma_prefs = UserPreferences.query.filter_by(user_id=emma.id).first()
    if not emma_prefs:
        emma_prefs = UserPreferences(
            user_id=emma.id, display_name="Emma Stone", industry_focus="Agency Producer"
        )
        db.session.add(emma_prefs)
        db.session.commit()

    # Ensure FriendRequests are pre-accepted for all three collaborators
    for buddy in (sofia, alex, emma):
        req = FriendRequest.query.filter(
            (
                (FriendRequest.sender_id == user.id)
                & (FriendRequest.receiver_id == buddy.id)
            )
            | (
                (FriendRequest.sender_id == buddy.id)
                & (FriendRequest.receiver_id == user.id)
            )
        ).first()
        if not req:
            req = FriendRequest(
                sender_id=buddy.id, receiver_id=user.id, status="accepted"
            )
            db.session.add(req)
        else:
            req.status = "accepted"
    db.session.commit()

    # Clean old direct messages for a fresh sandboxed thread
    FriendMessage.query.filter(
        ((FriendMessage.sender_id == user.id) | (FriendMessage.receiver_id == user.id))
    ).delete(synchronize_session=False)
    db.session.commit()

    # Seed active chat threads
    db.session.add_all(
        [
            # Sofia Hart thread
            FriendMessage(
                sender_id=sofia.id,
                receiver_id=user.id,
                body="Hey! I reviewed the new arpeggiated swells. The vocal clarity index on the summer stinger is absolutely perfect for the voice-over headroom!",
            ),
            FriendMessage(
                sender_id=user.id,
                receiver_id=sofia.id,
                body="Great feedback! Let's make sure the dialogue clarity stays above 80% across the board.",
            ),
            FriendMessage(
                sender_id=sofia.id,
                receiver_id=user.id,
                body="Agreed. Also, remember to lock the FM Pluck layer if you want that organic acoustic signature.",
            ),
            # Alex Mercer thread
            FriendMessage(
                sender_id=alex.id,
                receiver_id=user.id,
                body="I just pitched Hans Zimmer's 'Time' cue as a reference sync for our slow-build montage segment. It has a high cosine similarity match.",
            ),
            FriendMessage(
                sender_id=user.id,
                receiver_id=alex.id,
                body="Excellent choice. Let's see if the client likes the vibe overlap curves.",
            ),
            FriendMessage(
                sender_id=alex.id,
                receiver_id=user.id,
                body="I'll export the PRO cue sheet placement timestamps as soon as they sign off.",
            ),
            # Emma Stone thread
            FriendMessage(
                sender_id=emma.id,
                receiver_id=user.id,
                body="Hi team! Just double-checked the TikTok soundclash rooms. The energy pacing fits our Gen Z audience profile to a T.",
            ),
        ]
    )
    db.session.commit()

    # 2. Clear old demo supervisor campaigns to ensure a fresh, consistent sandbox state
    ABVote.query.filter(
        (ABVote.user_id == user.id) | (ABVote.user_id == sofia.id)
    ).delete(synchronize_session=False)
    RoomPollVote.query.filter(
        (RoomPollVote.user_id == user.id) | (RoomPollVote.user_id == sofia.id)
    ).delete(synchronize_session=False)
    db.session.commit()

    old_rooms = CampaignRoom.query.filter(CampaignRoom.created_by == user.id).all()
    for r in old_rooms:
        # Clear child dependencies that might have children themselves (ABVote and RoomPollVote)
        old_tests = ABTest.query.filter_by(room_id=r.id).all()
        for t in old_tests:
            ABVote.query.filter_by(test_id=t.id).delete()

        old_polls = RoomPoll.query.filter_by(room_id=r.id).all()
        for p in old_polls:
            RoomPollVote.query.filter_by(poll_id=p.id).delete()

        SongStatus.query.filter_by(room_id=r.id).delete()
        ABTest.query.filter_by(room_id=r.id).delete()
        RoomMessage.query.filter_by(room_id=r.id).delete()
        RoomReaction.query.filter_by(room_id=r.id).delete()
        RoomPin.query.filter_by(room_id=r.id).delete()
        RoomPoll.query.filter_by(room_id=r.id).delete()
        RoomEvent.query.filter_by(room_id=r.id).delete()
        r.members = []
        db.session.delete(r)
    db.session.commit()

    FavoriteRecommendation.query.filter_by(user_id=user.id).delete()
    UserInteractionLog.query.filter_by(user_id=user.id).delete()
    db.session.commit()

    # Seed User Interaction Logs for realistic Habits analytics
    # Study context: high plays, very low skips (15 plays, 2 skips)
    study_songs = [
        ("Honest", "Nico Collins"),
        ("A New Beginning", "Yasumu"),
        ("Adrift", "Kurt Stewart"),
        ("12 Hours", "Chris James"),
        ("01:22", "colours in the dark"),
        ("A Better Place", "Project AER"),
    ]
    for i in range(15):
        s_name, s_art = study_songs[i % len(study_songs)]
        db.session.add(
            UserInteractionLog(
                user_id=user.id,
                track_name=s_name,
                artist_name=s_art,
                action="play",
                context="study",
            )
        )
    for i in range(2):
        s_name, s_art = study_songs[i % len(study_songs)]
        db.session.add(
            UserInteractionLog(
                user_id=user.id,
                track_name=s_name,
                artist_name=s_art,
                action="skip",
                context="study",
            )
        )

    # Cooking context: moderate plays, higher skips (12 plays, 5 skips)
    cooking_songs = [
        ("#BrooklynBloodPop!", "SyKo"),
        ("...Baby One More Time", "Britney Spears"),
        ("22", "Taylor Swift"),
        ("5 Taara", "Diljit Dosanjh"),
        ("A-Punk", "Vampire Weekend"),
    ]
    for i in range(12):
        s_name, s_art = cooking_songs[i % len(cooking_songs)]
        db.session.add(
            UserInteractionLog(
                user_id=user.id,
                track_name=s_name,
                artist_name=s_art,
                action="play",
                context="cooking",
            )
        )
    for i in range(5):
        s_name, s_art = cooking_songs[i % len(cooking_songs)]
        db.session.add(
            UserInteractionLog(
                user_id=user.id,
                track_name=s_name,
                artist_name=s_art,
                action="skip",
                context="cooking",
            )
        )

    # Workout context: energetic tracks (10 plays, 1 skip)
    workout_songs = [
        ("Honest", "Nico Collins"),
        ("Neon Beats", "Retro Future"),
        ("ANUBIS", "KUTE"),
        ("AVOID ME", "KUTE"),
    ]
    for i in range(10):
        s_name, s_art = workout_songs[i % len(workout_songs)]
        db.session.add(
            UserInteractionLog(
                user_id=user.id,
                track_name=s_name,
                artist_name=s_art,
                action="play",
                context="workout",
            )
        )
    for i in range(1):
        s_name, s_art = workout_songs[i % len(workout_songs)]
        db.session.add(
            UserInteractionLog(
                user_id=user.id,
                track_name=s_name,
                artist_name=s_art,
                action="skip",
                context="workout",
            )
        )

    db.session.commit()

    # 3. Create fresh campaign rooms matching industry target presets
    room1 = CampaignRoom(
        mood_key="summer_campaign",
        name="Summer Brand Launch ☀️",
        brief_summary="Brand Awareness | Audience: Millennials | Platform: Instagram Reel | Energy: Happy & Feel-good",
        created_by=user.id,
    )
    room1.members.extend([user, sofia])

    room2 = CampaignRoom(
        mood_key="viral_trend",
        name="TikTok Viral Soundclash 📱",
        brief_summary="Direct Response | Audience: Gen Z | Platform: TikTok | Energy: Viral & Fast-paced",
        created_by=user.id,
    )
    room2.members.extend([user, sofia])

    db.session.add_all([room1, room2])
    db.session.commit()

    # 4. Extract real songs from ALL_SONGS to seed in favorites and campaign statuses
    songs_sample = [s for s in ALL_SONGS if s.get("trackName") and s.get("artistName")]
    if len(songs_sample) < 10:
        # Fallback if catalog is unexpectedly small
        songs_sample = [
            {
                "trackName": "Sunlight Glow",
                "artistName": "Summer Crew",
                "genre": "Pop",
                "danceability": 0.82,
                "energy": 0.88,
                "valence": 0.91,
                "speechiness": 0.04,
                "instrumentalness": 0.02,
            },
            {
                "trackName": "Scroll Stopper",
                "artistName": "The Hype",
                "genre": "Electronic",
                "danceability": 0.93,
                "energy": 0.91,
                "valence": 0.82,
                "speechiness": 0.15,
                "instrumentalness": 0.01,
            },
            {
                "trackName": "Corporate Spark",
                "artistName": "Elevate",
                "genre": "Ambient",
                "danceability": 0.32,
                "energy": 0.38,
                "valence": 0.52,
                "speechiness": 0.02,
                "instrumentalness": 0.85,
            },
            {
                "trackName": "Neon Beats",
                "artistName": "Retro Future",
                "genre": "Synth",
                "danceability": 0.85,
                "energy": 0.90,
                "valence": 0.75,
                "speechiness": 0.05,
                "instrumentalness": 0.05,
            },
            {
                "trackName": "Acoustic Warmth",
                "artistName": "Folk Trio",
                "genre": "Folk",
                "danceability": 0.35,
                "energy": 0.25,
                "valence": 0.70,
                "speechiness": 0.03,
                "instrumentalness": 0.20,
            },
            {
                "trackName": "Luxury Chill",
                "artistName": "Vibe Masters",
                "genre": "Jazz",
                "danceability": 0.15,
                "energy": 0.20,
                "valence": 0.35,
                "speechiness": 0.01,
                "instrumentalness": 0.90,
            },
        ]

    # Seed favorites
    for i, s in enumerate(songs_sample[:6]):
        fav = FavoriteRecommendation(
            user_id=user.id,
            track_name=s["trackName"],
            artist_name=s["artistName"],
            genre=s.get("genre", "Pop"),
            spotify_url=s.get("spotify_url"),
            color=s.get("color", "#64748b"),
            match_score=94 - i * 3,
            taste_match=88 - i * 2,
            source_type="mood_preset",
            source_label="Summer Campaign",
        )
        db.session.add(fav)
    db.session.commit()

    # 5. Seed track statuses for Room 1 (Summer Brand Launch)
    # Total Pitched: 6. Wins: 4 (2 approved, 2 shortlisted). Suggested: 2.
    for i, s in enumerate(songs_sample[:6]):
        tk = f"{s['trackName']}|||{s['artistName']}"
        status = "approved" if i < 2 else ("shortlisted" if i < 4 else "suggested")
        ss = SongStatus(
            room_id=room1.id,
            track_key=tk,
            status=status,
            changed_by=sofia.id if i % 2 == 0 else user.id,
            reason=(
                "Excellent emotional resonance & bright energy."
                if status != "suggested"
                else None
            ),
        )
        db.session.add(ss)

    # Seed track statuses for Room 2 (TikTok Viral Soundclash)
    # Total Pitched: 4. Wins: 2 (1 approved, 1 sent to client). Suggested: 1, Rejected: 1.
    for i, s in enumerate(songs_sample[4:8]):
        tk = f"{s['trackName']}|||{s['artistName']}"
        status = (
            "rejected"
            if i == 0
            else (
                "approved" if i == 1 else ("sent_to_client" if i == 2 else "suggested")
            )
        )
        ss = SongStatus(
            room_id=room2.id,
            track_key=tk,
            status=status,
            changed_by=user.id,
            reason=(
                "Vocals overlap with voiceover brief."
                if status == "rejected"
                else "Perfect visual beat-sync."
            ),
        )
        db.session.add(ss)
    db.session.commit()

    # 6. Seed A/B creative pre-testing vote parameters
    ab_test = ABTest(
        room_id=room1.id,
        song_a_key=f"{songs_sample[0]['trackName']}|||{songs_sample[0]['artistName']}",
        song_b_key=f"{songs_sample[1]['trackName']}|||{songs_sample[1]['artistName']}",
        title="Uplifting Hook Sync-Test",
        created_by=sofia.id,
    )
    db.session.add(ab_test)
    db.session.commit()

    # Add A/B votes with strong positive emotional consensus (Mean = 3.5 / 4.0 -> System1 Stars ~5.1)
    v1 = ABVote(
        test_id=ab_test.id, user_id=user.id, chosen="a", emotion_rating=4
    )  # 😍 Strong Positive
    v2 = ABVote(
        test_id=ab_test.id, user_id=sofia.id, chosen="a", emotion_rating=3
    )  # 😊 Positive
    db.session.add_all([v1, v2])
    db.session.commit()




@app.route("/demo/sandbox")
def demo_sandbox():
    """Launch the Interactive Demo Sandbox.
    Automatically creates/seeds the demo supervisor account and logs in.
    """
    demo_email = "demo.supervisor@gmail.com"

    # Find or create the supervisor account
    user = User.query.filter_by(username=demo_email).first()
    if not user:
        user = User(username=demo_email)
        user.set_password("123")
        db.session.add(user)
        db.session.commit()

    # Ensure profile preferences are set up beautifully
    prefs = UserPreferences.query.filter_by(user_id=user.id).first()
    if not prefs:
        prefs = UserPreferences(user_id=user.id)
        db.session.add(prefs)

    prefs.display_name = "Maya Patel (Sandbox Mode)"
    prefs.industry_focus = "Tech & Social Ads"
    prefs.target_generation = "millennials"
    prefs.target_campaign = "launch"
    prefs.genres = '["pop", "electronic", "synth"]'
    prefs.slider_positions = '{"danceability": "0.85", "energy": "0.90", "valence": "0.75", "acousticness": "0.05", "instrumentalness": "0.05"}'
    prefs.pref_danceability = 0.85
    prefs.pref_energy = 0.90
    prefs.pref_valence = 0.75
    prefs.pref_acousticness = 0.05
    prefs.pref_instrumentalness = 0.05

    db.session.commit()

    # Run the database seeding/reset routine
    seed_demo_sandbox_data(user)

    # Establish login session
    session["email"] = user.username

    flash(
        "Welcome to the USense Interactive Sandbox! Every premium feature is pre-seeded for testing.",
        "success",
    )
    return redirect(url_for("dashboard"))


# Dashboard
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "email" not in session:
        return redirect(url_for("home"))
    user = User.query.filter_by(username=session["email"]).first()
    prefs = UserPreferences.query.filter_by(user_id=user.id).first() if user else None

    if request.args.get("clear_campaign") == "1":
        session.pop("campaign_brief", None)
        flash("Campaign brief cleared.", "success")
        return redirect(url_for("dashboard", mood=request.args.get("mood", "").strip()))

    if request.method == "POST":
        campaign_brief = {
            "objective": request.form.get("campaign_objective", "").strip(),
            "target_audience": request.form.get("target_audience", "").strip(),
            "platform": request.form.get("campaign_platform", "").strip(),
            "energy": request.form.get("campaign_energy", "").strip(),
            "creative_notes": request.form.get("campaign_notes", "").strip(),
            "asset_name": "",
        }
        campaign_asset = request.files.get("campaign_asset")
        if campaign_asset and campaign_asset.filename:
            from werkzeug.utils import secure_filename

            filename = secure_filename(campaign_asset.filename)
            upload_path = os.path.join(app.static_folder, "uploads", "campaigns")
            os.makedirs(upload_path, exist_ok=True)
            campaign_asset.save(os.path.join(upload_path, filename))
            campaign_brief["asset_name"] = filename

        session["campaign_brief"] = campaign_brief
        flash(
            "Campaign brief saved. Recommendations now reflect this context.", "success"
        )
        mood_value = request.form.get("mood", "").strip()
        redirect_kwargs = {"mood": mood_value} if mood_value else {}
        return redirect(url_for("dashboard", **redirect_kwargs))

    saved_campaign_brief = session.get("campaign_brief", {}) or {}

    # Smart defaults from profile
    default_audience = ""
    default_objective = ""
    default_energy = ""

    if prefs:
        # Default Audience from Generation
        gen_map = {
            "gen_z": "Gen Z",
            "millennials": "Millennials",
            "boomers": "Boomers",
            "silent_generation": "Silent Generation",
        }
        if getattr(prefs, "target_generation", None) in gen_map:
            default_audience = gen_map[prefs.target_generation]

        # Default Objective & Energy from Target Campaign
        camp = getattr(prefs, "target_campaign", None)
        if camp in ("summer", "holiday"):
            default_objective = "awareness"
            default_energy = "happy"
        elif camp == "launch":
            default_objective = "excitement"
            default_energy = "energetic"
        elif camp == "corporate":
            default_objective = "trust"
            default_energy = "relaxed"
        elif camp == "social":
            default_objective = "conversion"
            default_energy = "energetic"

    campaign_brief = {
        "objective": saved_campaign_brief.get("objective") or default_objective,
        "target_audience": saved_campaign_brief.get("target_audience")
        or default_audience,
        "platform": saved_campaign_brief.get("platform", ""),
        "energy": saved_campaign_brief.get("energy") or default_energy,
        "creative_notes": saved_campaign_brief.get("creative_notes", ""),
        "asset_name": saved_campaign_brief.get("asset_name", ""),
    }
    campaign_objective_label = next(
        (
            item["label"]
            for item in CAMPAIGN_OBJECTIVES
            if item["value"] == campaign_brief["objective"]
        ),
        "",
    )
    campaign_platform_label = next(
        (
            item["label"]
            for item in CAMPAIGN_PLATFORMS
            if item["value"] == campaign_brief["platform"]
        ),
        "",
    )
    campaign_energy_label = next(
        (
            item["label"]
            for item in CAMPAIGN_ENERGY_LEVELS
            if item["value"] == campaign_brief["energy"]
        ),
        "",
    )
    campaign_brief_summary_parts = []
    if campaign_objective_label:
        campaign_brief_summary_parts.append(campaign_objective_label)
    if campaign_brief["target_audience"]:
        campaign_brief_summary_parts.append(
            f"Audience: {campaign_brief['target_audience']}"
        )
    if campaign_platform_label:
        campaign_brief_summary_parts.append(campaign_platform_label)
    if campaign_energy_label:
        campaign_brief_summary_parts.append(f"Energy: {campaign_energy_label}")
    if campaign_brief["asset_name"]:
        campaign_brief_summary_parts.append(f"Draft: {campaign_brief['asset_name']}")
    campaign_brief_summary = " | ".join(campaign_brief_summary_parts)

    # Campaign mood handling
    active_mood = request.values.get("mood", "").strip()
    active_mood_key = active_mood.lower()
    mood_prefs = None
    campaign_mood = None
    if active_mood_key and active_mood_key in CAMPAIGN_MOODS:
        from datetime import datetime, timedelta

        recent_cutoff = datetime.utcnow() - timedelta(minutes=5)
        recent = MoodSession.query.filter(
            MoodSession.user_id == user.id,
            MoodSession.mood_key == active_mood_key,
            MoodSession.created_at > recent_cutoff,
        ).first()
        if not recent:
            db.session.add(MoodSession(user_id=user.id, mood_key=active_mood_key))
            db.session.commit()

        preset = CAMPAIGN_MOODS[active_mood_key]

        class MoodPrefs:
            pass

        mood_prefs = MoodPrefs()
        if prefs:
            for column in prefs.__table__.columns:
                setattr(mood_prefs, column.name, getattr(prefs, column.name))
        else:
            mood_prefs.genres = "[]"
            mood_prefs.feature_weights = "{}"
            mood_prefs.use_interaction_signal = False
            mood_prefs.interaction_blend = 0.65
            mood_prefs.enable_personalized_similarity = False
            mood_prefs.personalized_similarity_text = ""
            mood_prefs.enable_genre_boost = False
            mood_prefs.genre_boost_weight = 1.0
            mood_prefs.user_id = user.id if user else None
            mood_prefs.display_name = None
            mood_prefs.weight_base_audio = 0.40
            mood_prefs.weight_industry = 0.20
            mood_prefs.weight_generation = 0.20
            mood_prefs.weight_campaign = 0.20
            mood_prefs.enable_acoustic_matcher = False
            mood_prefs.target_generation = None
            mood_prefs.target_campaign = None
            mood_prefs.industry_focus = None
            mood_prefs.roles = ""
        for key in (
            "pref_danceability",
            "pref_energy",
            "pref_valence",
            "pref_acousticness",
            "pref_instrumentalness",
        ):
            setattr(mood_prefs, key, preset[key])
        mood_prefs.genres = getattr(mood_prefs, "genres", "[]")
        campaign_mood = {
            "label": preset["label"],
            "emoji": preset["emoji"],
            "color": preset["color"],
            "summary": preset["desc"]
            + (f" Brief: {campaign_brief_summary}." if campaign_brief_summary else ""),
            "genres": [],
        }
    elif active_mood:
        mood_prefs, campaign_mood = build_mood_preferences(active_mood, prefs)
        if campaign_mood and campaign_brief_summary:
            campaign_mood["summary"] = (
                f"{campaign_mood['summary']} Brief: {campaign_brief_summary}."
            )

    effective_prefs = mood_prefs if mood_prefs else prefs

    # Apply Campaign Brief Creative Notes NLP Parser & Modulator
    brief_nlp_matched = []
    if campaign_brief.get("creative_notes"):
        effective_prefs, brief_nlp_matched = parse_creative_notes_nlp(
            campaign_brief["creative_notes"], effective_prefs
        )

    social_sidebar = get_social_sidebar_data(user, prefs)
    community_recommendations = get_community_recommendations(user, prefs)
    selected_genres = get_saved_genres(effective_prefs)
    display_name = (
        (prefs.display_name or session["email"]) if prefs else session["email"]
    )
    songs = get_hybrid_recommendations(user, effective_prefs)
    profile_alone_songs = get_hybrid_recommendations(user, prefs, n=6) if user else []

    # --- Marketing analytics (simple aggregates for dashboard) ---
    total_tracks = len(songs)
    avg_energy = 0.0
    avg_danceability = 0.0
    risk_variance = 0.0
    risk_score = 0.0
    top_genres = []
    if total_tracks:
        avg_energy = sum(float(s.get("energy", 0.0)) for s in songs) / total_tracks
        avg_danceability = (
            sum(float(s.get("danceability", 0.0)) for s in songs) / total_tracks
        )
        feature_variances = []
        for feature_key in RISK_FEATURE_KEYS:
            feature_values = [
                float(song.get(feature_key, 0.0))
                for song in songs
                if song.get(feature_key) is not None
            ]
            if len(feature_values) >= 2:
                feature_variances.append(pvariance(feature_values))

        if feature_variances:
            risk_variance = sum(feature_variances) / len(feature_variances)
            risk_score = min(1.0, risk_variance * 4.0)

        genre_counts = {}
        for s in songs:
            g = (s.get("genre") or "").strip()
            if not g:
                continue
            genre_counts[g] = genre_counts.get(g, 0) + 1
        top_genres = sorted(genre_counts.items(), key=lambda it: it[1], reverse=True)[
            :6
        ]
    marketing_stats = {
        "total_tracks": total_tracks,
        "risk_score": round(risk_score, 3),
        "risk_variance": round(risk_variance, 4),
        "avg_energy": round(avg_energy, 3),
        "avg_danceability": round(avg_danceability, 3),
        "top_genres": top_genres,
        "historical_fitness": 0.0,
    }

    # Calculate Multi-Vector Historical Fitness
    if user:
        from services.recommender_shared import track_key

        saved_tracks = FavoriteRecommendation.query.filter_by(user_id=user.id).all()
        if saved_tracks:
            # Use the already-scored songs list instead of re-scoring the entire catalog
            scored_keys = {
                track_key(s["trackName"], s["artistName"]): s.get("_fitness_overall", s.get("raw_score", 0.0))
                for s in songs
            }
            saved_fitnesses = []
            for t in saved_tracks:
                key = track_key(t.track_name, t.artist_name)
                if key in scored_keys:
                    saved_fitnesses.append(scored_keys[key])
            if saved_fitnesses:
                marketing_stats["historical_fitness"] = round(
                    (sum(saved_fitnesses) / len(saved_fitnesses)) * 100, 1
                )
    favorite_recommendations = get_favorite_recommendations(user)
    favorite_recommendation_keys = get_favorite_recommendation_keys(user)
    profile_feature_values = {
        feat["key"]: (
            getattr(effective_prefs, feat["key"], None) if effective_prefs else None
        )
        for feat in AUDIO_FEATURES
    }

    # Campaign brief history (last 10)
    mood_history = []
    if user:
        recent_sessions = (
            MoodSession.query.filter_by(user_id=user.id)
            .order_by(MoodSession.created_at.desc())
            .limit(10)
            .all()
        )
        for s in recent_sessions:
            preset_info = CAMPAIGN_MOODS.get(s.mood_key, {})
            mood_history.append(
                {
                    "mood_key": s.mood_key,
                    "label": preset_info.get("label", s.mood_key),
                    "emoji": preset_info.get("emoji", ""),
                    "color": preset_info.get("color", "#64748b"),
                    "created_at": s.created_at,
                }
            )
    # Campaign rooms for current user (recent 10)
    campaign_rooms = []
    completed_campaign_rooms = []
    rooms_with_approvals = []
    if user:
        # Fetch all rooms where the user is a member
        all_rooms = (
            CampaignRoom.query.filter(CampaignRoom.members.contains(user))
            .order_by(CampaignRoom.created_at.desc())
            .all()
        )
        campaign_rooms = [r for r in all_rooms if getattr(r, "is_ongoing", True)]
        completed_campaign_rooms = [
            r for r in all_rooms if not getattr(r, "is_ongoing", True)
        ]

        # Approved tracks per room for the "Branding Starters" list
        from models.database import SongStatus
        from services.song_service import ALL_SONGS
        from services.recommender_shared import track_key
        songs_by_key = {track_key(s["trackName"], s["artistName"]): s for s in ALL_SONGS}
        rooms_with_approvals = []
        for r in all_rooms:
            approved_statuses = SongStatus.query.filter_by(room_id=r.id, status="approved").all()
            if approved_statuses:
                tracks = []
                for ss in approved_statuses:
                    song_data = songs_by_key.get(ss.track_key)
                    if song_data:
                        tracks.append(song_data)
                if tracks:
                    rooms_with_approvals.append({
                        "room": r,
                        "tracks": tracks
                    })

    return render_template(
        "dashboard.html",
        email=session["email"],
        display_name=display_name,
        prefs=effective_prefs,
        songs=songs,
        profile_alone_songs=profile_alone_songs,

        selected_genres=selected_genres,
        available_genres=AVAILABLE_GENRES,
        saved_genres=get_saved_genres(prefs),
        feature_weight_controls=get_feature_weight_controls(),
        feature_weight_values=get_feature_weight_values(prefs),
        audio_features=AUDIO_FEATURES,
        profile_feature_values=profile_feature_values,
        social_sidebar=social_sidebar,
        community_recommendations=community_recommendations,
        favorite_recommendations=favorite_recommendations,
        favorite_recommendation_keys=favorite_recommendation_keys,
        mood_presets=CAMPAIGN_MOODS,
        campaign_objectives=CAMPAIGN_OBJECTIVES,
        campaign_platforms=CAMPAIGN_PLATFORMS,
        campaign_energy_levels=CAMPAIGN_ENERGY_LEVELS,
        campaign_brief=campaign_brief,
        campaign_brief_summary=campaign_brief_summary,
        active_mood=active_mood_key if active_mood_key in CAMPAIGN_MOODS else "",
        campaign_mood=campaign_mood,
        marketing_stats=marketing_stats,
        mood_history=mood_history,
        campaign_rooms=campaign_rooms,
        completed_campaign_rooms=completed_campaign_rooms,
        rooms_with_approvals=rooms_with_approvals,
        user_id=user.id if user else None,
        is_sandbox=(session["email"] == "demo.supervisor@gmail.com"),
        brief_nlp_matched=brief_nlp_matched,
    )


@app.route("/conversation/<int:collaborator_id>")
def conversation(collaborator_id):
    """Dedicated conversation page for a specific collaborator."""
    if "email" not in session:
        return redirect(url_for("home"))

    user = User.query.filter_by(username=session["email"]).first()
    if not user:
        return redirect(url_for("home"))

    # Check if users are collaborators
    if not are_collaborators(user.id, collaborator_id):
        flash("You can only message collaborators.", "error")
        return redirect(url_for("dashboard"))

    # Get collaborator info
    collaborator = User.query.get(collaborator_id)
    if not collaborator:
        flash("Collaborator not found.", "error")
        return redirect(url_for("dashboard"))

    # Get all messages between user and collaborator
    messages = (
        FriendMessage.query.filter(
            (
                (FriendMessage.sender_id == user.id)
                & (FriendMessage.receiver_id == collaborator_id)
            )
            | (
                (FriendMessage.sender_id == collaborator_id)
                & (FriendMessage.receiver_id == user.id)
            )
        )
        .order_by(FriendMessage.created_at.asc())
        .all()
    )

    # Format messages for display
    formatted_messages = []
    for msg in messages:
        is_sender = msg.sender_id == user.id
        formatted_messages.append(
            {
                "body": msg.body,
                "is_sender": is_sender,
                "direction": "You" if is_sender else collaborator.username,
                "sender_name": user.username if is_sender else collaborator.username,
                "created_at": msg.created_at,
            }
        )

    # Get user preferences for display
    prefs = UserPreferences.query.filter_by(user_id=user.id).first()
    display_name = (
        (prefs.display_name or session["email"]) if prefs else session["email"]
    )

    # Get all collaborators for sidebar
    social_sidebar = get_social_sidebar_data(user, prefs)

    return render_template(
        "conversation.html",
        email=session["email"],
        display_name=display_name,
        collaborator=collaborator,
        collaborator_id=collaborator_id,
        messages=formatted_messages,
        social_sidebar=social_sidebar,
    )


@app.route("/api/chat/<int:collaborator_id>/messages")
def api_chat_messages(collaborator_id):
    """JSON endpoint: return messages between current user and a collaborator."""
    if "email" not in session:
        return {"error": "Not authenticated"}, 401

    user = User.query.filter_by(username=session["email"]).first()
    if not user:
        return {"error": "User not found"}, 404

    if not are_collaborators(user.id, collaborator_id):
        return {"error": "Not collaborators"}, 403

    collaborator = User.query.get(collaborator_id)
    if not collaborator:
        return {"error": "Collaborator not found"}, 404

    messages = (
        FriendMessage.query.filter(
            (
                (FriendMessage.sender_id == user.id)
                & (FriendMessage.receiver_id == collaborator_id)
            )
            | (
                (FriendMessage.sender_id == collaborator_id)
                & (FriendMessage.receiver_id == user.id)
            )
        )
        .order_by(FriendMessage.created_at.asc())
        .all()
    )

    result = []
    for msg in messages:
        is_sender = msg.sender_id == user.id
        result.append(
            {
                "id": msg.id,
                "body": msg.body,
                "is_sender": is_sender,
                "created_at": msg.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    return {
        "messages": result,
        "collaborator_label": collaborator.username.split("@")[0],
        "collaborator_email": collaborator.username,
    }


# Removed redundant send_friend_message_http as it is now send_collaborator_message in social_routes.py


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "email" not in session:
        return redirect(url_for("home"))
    user = User.query.filter_by(username=session["email"]).first()
    prefs = UserPreferences.query.filter_by(user_id=user.id).first()

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        industry_focus = request.form.get("industry_focus", "").strip()
        selected_genres = request.form.getlist("genres")
        feature_weight_controls = get_feature_weight_controls()
        if prefs is None:
            prefs = UserPreferences(user_id=user.id)
            db.session.add(prefs)
        prefs.display_name = display_name
        prefs.industry_focus = industry_focus
        prefs.genres = json.dumps(selected_genres)
        prefs.roles = request.form.get("roles", "").strip()
        for feat in AUDIO_FEATURES:
            raw = request.form.get(feat["key"], "0.5")
            try:
                val = max(0.0, min(1.0, float(raw)))
            except ValueError:
                val = 0.5
            setattr(prefs, feat["key"], val)

        selected_weights = {}
        for item in feature_weight_controls:
            raw_weight = request.form.get(f"weight_{item['key']}", str(item["default"]))
            try:
                selected_weights[item["key"]] = max(0.0, min(2.0, float(raw_weight)))
            except ValueError:
                selected_weights[item["key"]] = item["default"]
        prefs.feature_weights = json.dumps(selected_weights)

        prefs.use_interaction_signal = (
            request.form.get("use_interaction_signal") == "on"
        )
        prefs.enable_personalized_similarity = (
            request.form.get("enable_personalized_similarity") == "on"
        )
        prefs.enable_genre_boost = request.form.get("enable_genre_boost") == "on"
        prefs.enable_acoustic_matcher = (
            request.form.get("enable_acoustic_matcher") == "on"
        )

        raw_blend = request.form.get("interaction_blend", "0.25")
        try:
            prefs.interaction_blend = max(0.0, min(0.8, float(raw_blend)))
        except ValueError:
            prefs.interaction_blend = 0.25

        raw_genre_boost = request.form.get("genre_boost_weight", "1")
        try:
            prefs.genre_boost_weight = float(
                max(1, min(3, int(round(float(raw_genre_boost)))))
            )
        except ValueError:
            prefs.genre_boost_weight = 1.0

        # Multi-Vector
        prefs.target_generation = request.form.get("target_generation", "").strip()
        prefs.target_campaign = request.form.get("target_campaign", "").strip()

        try:
            prefs.weight_base_audio = float(
                request.form.get("weight_base_audio", "0.4")
            )
        except ValueError:
            prefs.weight_base_audio = 0.4
        try:
            prefs.weight_industry = float(request.form.get("weight_industry", "0.2"))
        except ValueError:
            prefs.weight_industry = 0.2
        try:
            prefs.weight_generation = float(
                request.form.get("weight_generation", "0.2")
            )
        except ValueError:
            prefs.weight_generation = 0.2
        try:
            prefs.weight_campaign = float(request.form.get("weight_campaign", "0.2"))
        except ValueError:
            prefs.weight_campaign = 0.2

        prefs.personalized_similarity_text = request.form.get(
            "personalized_similarity_text", ""
        ).strip()[:1000]

        # Persist slider UI positions: either accept a JSON payload from the form
        # (filled by client-side JS) or fall back to saving the raw slider values.
        slider_positions_json = request.form.get("slider_positions", "")
        if slider_positions_json:
            try:
                prefs.slider_positions = slider_positions_json
            except Exception:
                prefs.slider_positions = json.dumps({})
        else:
            slider_positions = {}
            for feat in AUDIO_FEATURES:
                slider_positions[feat["key"]] = request.form.get(feat["key"], "0.50")

            # include weight slider positions
            for item in feature_weight_controls:
                slider_positions[f"weight_{item['key']}"] = request.form.get(
                    f"weight_{item['key']}", str(item["default"])
                )

            # include other sliders
            slider_positions["interaction_blend"] = request.form.get(
                "interaction_blend", "0.25"
            )
            slider_positions["genre_boost_weight"] = request.form.get(
                "genre_boost_weight", "1"
            )

            prefs.slider_positions = json.dumps(slider_positions)

        db.session.commit()
        saved_genres = selected_genres
        social_sidebar = get_social_sidebar_data(user, prefs)
        return render_template(
            "profile.html",
            email=session["email"],
            prefs=prefs,
            saved_genres=saved_genres,
            available_genres=AVAILABLE_GENRES,
            audio_features=AUDIO_FEATURES,
            feature_weight_controls=feature_weight_controls,
            feature_weight_values=get_feature_weight_values(prefs),
            social_sidebar=social_sidebar,
            success="Preferences saved successfully!",
        )

    saved_genres = get_saved_genres(prefs)
    feature_weight_controls = get_feature_weight_controls()
    social_sidebar = get_social_sidebar_data(user, prefs)
    return render_template(
        "profile.html",
        email=session["email"],
        prefs=prefs,
        saved_genres=saved_genres,
        available_genres=AVAILABLE_GENRES,
        audio_features=AUDIO_FEATURES,
        feature_weight_controls=feature_weight_controls,
        feature_weight_values=get_feature_weight_values(prefs),
        social_sidebar=social_sidebar,
    )


@app.route("/api/profile/save", methods=["POST"])
def api_profile_save():
    if "email" not in session:
        return {"status": "error", "message": "Unauthorized"}, 401

    user = User.query.filter_by(username=session["email"]).first()
    if not user:
        return {"status": "error", "message": "User not found"}, 404

    prefs = UserPreferences.query.filter_by(user_id=user.id).first()
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        db.session.add(prefs)

    data = request.get_json() or {}

    # Simple settings
    if "display_name" in data:
        prefs.display_name = str(data["display_name"]).strip()
    if "roles" in data:
        prefs.roles = str(data["roles"]).strip()
    if "industry_focus" in data:
        prefs.industry_focus = str(data["industry_focus"]).strip()
    if "target_generation" in data:
        prefs.target_generation = str(data["target_generation"]).strip()
    if "target_campaign" in data:
        prefs.target_campaign = str(data["target_campaign"]).strip()
    if "genres" in data:
        genres_list = data["genres"]
        if isinstance(genres_list, list):
            prefs.genres = json.dumps([str(g) for g in genres_list])

    # Interactive sliders
    for feat in AUDIO_FEATURES:
        feat_key = feat["key"]
        short_key = feat_key.replace("pref_", "")
        val_str = None
        if feat_key in data:
            val_str = data[feat_key]
        elif short_key in data:
            val_str = data[short_key]

        if val_str is not None:
            try:
                val = max(0.0, min(1.0, float(val_str)))
                setattr(prefs, feat_key, val)
            except (ValueError, TypeError):
                pass

    # Feature weights
    feature_weight_controls = get_feature_weight_controls()
    current_weights = {}
    if prefs.feature_weights:
        try:
            current_weights = json.loads(prefs.feature_weights)
        except Exception:
            current_weights = {}

    weights_updated = False
    for item in feature_weight_controls:
        val_str = None
        if f"weight_{item['key']}" in data:
            val_str = data[f"weight_{item['key']}"]
        elif item['key'] in data:
            val_str = data[item['key']]

        if val_str is not None:
            try:
                current_weights[item["key"]] = max(0.0, min(2.0, float(val_str)))
                weights_updated = True
            except (ValueError, TypeError):
                pass
    if weights_updated:
        prefs.feature_weights = json.dumps(current_weights)

    # Adaptive Learning & Toggles
    if "use_interaction_signal" in data:
        prefs.use_interaction_signal = bool(data["use_interaction_signal"])
    if "enable_personalized_similarity" in data:
        prefs.enable_personalized_similarity = bool(data["enable_personalized_similarity"])
    if "enable_genre_boost" in data:
        prefs.enable_genre_boost = bool(data["enable_genre_boost"])
    if "enable_acoustic_matcher" in data:
        prefs.enable_acoustic_matcher = bool(data["enable_acoustic_matcher"])

    if "interaction_blend" in data:
        try:
            prefs.interaction_blend = max(0.0, min(0.9, float(data["interaction_blend"])))
        except (ValueError, TypeError):
            pass

    if "genre_boost_weight" in data:
        try:
            prefs.genre_boost_weight = max(1.0, min(3.0, float(data["genre_boost_weight"])))
        except (ValueError, TypeError):
            pass

    # Multi-Vector Targeting Weights
    if "weight_base_audio" in data:
        try:
            prefs.weight_base_audio = max(0.0, min(1.0, float(data["weight_base_audio"])))
        except (ValueError, TypeError):
            pass
    if "weight_industry" in data:
        try:
            prefs.weight_industry = max(0.0, min(1.0, float(data["weight_industry"])))
        except (ValueError, TypeError):
            pass
    if "weight_generation" in data:
        try:
            prefs.weight_generation = max(0.0, min(1.0, float(data["weight_generation"])))
        except (ValueError, TypeError):
            pass
    if "weight_campaign" in data:
        try:
            prefs.weight_campaign = max(0.0, min(1.0, float(data["weight_campaign"])))
        except (ValueError, TypeError):
            pass

    if "personalized_similarity_text" in data:
        prefs.personalized_similarity_text = str(data["personalized_similarity_text"]).strip()[:1000]

    # Re-build slider_positions
    slider_positions = {}
    if prefs.slider_positions:
        try:
            slider_positions = json.loads(prefs.slider_positions)
        except Exception:
            slider_positions = {}

    for feat in AUDIO_FEATURES:
        slider_positions[feat["key"]] = getattr(prefs, feat["key"])
    for item in feature_weight_controls:
        slider_positions[f"weight_{item['key']}"] = current_weights.get(item["key"], item["default"])

    slider_positions["interaction_blend"] = prefs.interaction_blend
    slider_positions["genre_boost_weight"] = prefs.genre_boost_weight

    prefs.slider_positions = json.dumps(slider_positions)

    db.session.commit()
    return {"status": "success", "message": "Preferences saved successfully!"}


@app.route("/favorites")
def favorites():
    if "email" not in session:
        return redirect(url_for("home"))

    user = User.query.filter_by(username=session["email"]).first()
    prefs = UserPreferences.query.filter_by(user_id=user.id).first() if user else None
    display_name = (
        (prefs.display_name or session["email"]) if prefs else session["email"]
    )
    favorite_recommendations = get_favorite_recommendations(user)

    return render_template(
        "favorites.html",
        email=session["email"],
        display_name=display_name,
        favorite_recommendations=favorite_recommendations,
    )





@app.route("/workspace")
def workspace():
    if "email" not in session:
        return redirect(url_for("home"))

    email = session["email"]
    user = User.query.filter_by(username=email).first()
    if not user:
        return redirect(url_for("home"))

    prefs = UserPreferences.query.filter_by(user_id=user.id).first() if user else None
    social_sidebar = get_full_social_data(user, prefs)
    display_name = (
        (prefs.display_name or email.split("@")[0]) if prefs else email.split("@")[0]
    )

    return render_template(
        "workspace.html",
        email=email,
        display_name=display_name,
        social_sidebar=social_sidebar,
    )





# Logout
# pop it out the list
@app.route("/logout")
def logout():
    session.pop("email", None)
    return redirect(url_for("home"))


if __name__ == "__main__":
    with app.app_context():
        setup_database()
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
