from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(256), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class UserPreferences(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    display_name = db.Column(db.String(100), nullable=True)
    industry_focus = db.Column(db.String(80), nullable=True)
    genres = db.Column(db.Text, default="[]")
    roles = db.Column(db.Text, default="")
    # Stores UI slider positions (normalized 0-1 or 0-2 for weight sliders) serialized as JSON
    slider_positions = db.Column(db.Text, default="{}")
    pref_danceability = db.Column(db.Float, default=0.5)
    pref_energy = db.Column(db.Float, default=0.5)
    pref_valence = db.Column(db.Float, default=0.5)
    pref_acousticness = db.Column(db.Float, default=0.5)
    pref_instrumentalness = db.Column(db.Float, default=0.0)
    feature_weights = db.Column(db.Text, default="{}")
    use_interaction_signal = db.Column(db.Boolean, default=False)
    interaction_blend = db.Column(db.Float, default=0.65)
    enable_personalized_similarity = db.Column(db.Boolean, default=False)
    personalized_similarity_text = db.Column(db.Text, default="")
    enable_genre_boost = db.Column(db.Boolean, default=False)
    genre_boost_weight = db.Column(db.Float, default=1.0)
    enable_acoustic_matcher = db.Column(db.Boolean, default=False)

    # Multi-Vector Targeting
    target_generation = db.Column(db.String(50), nullable=True)
    target_campaign = db.Column(db.String(50), nullable=True)

    # Fitness Weights
    weight_base_audio = db.Column(db.Float, default=0.40)
    weight_industry = db.Column(db.Float, default=0.20)
    weight_generation = db.Column(db.Float, default=0.20)
    weight_campaign = db.Column(db.Float, default=0.20)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    __table_args__ = (
        db.CheckConstraint(
            "sender_id != receiver_id", name="ck_friend_request_not_self"
        ),
    )


class FriendMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    __table_args__ = (
        db.CheckConstraint(
            "sender_id != receiver_id", name="ck_friend_message_not_self"
        ),
    )


campaign_room_members = db.Table(
    "campaign_room_members",
    db.Column(
        "room_id", db.Integer, db.ForeignKey("campaign_room.id"), primary_key=True
    ),
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
)


class FavoriteRecommendation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    track_name = db.Column(db.String(255), nullable=False)
    artist_name = db.Column(db.String(255), nullable=False)
    genre = db.Column(db.String(120), nullable=True)
    spotify_url = db.Column(db.String(600), nullable=True)
    color = db.Column(db.String(20), nullable=True)
    match_score = db.Column(db.Integer, nullable=True)
    source_type = db.Column(db.String(32), nullable=True)
    source_label = db.Column(db.String(120), nullable=True)
    taste_match = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship(
        "User", backref=db.backref("favorite_recommendations", lazy=True)
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "track_name", "artist_name", name="uq_favorite_track_per_user"
        ),
    )


class MoodSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    mood_key = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User", backref=db.backref("mood_sessions", lazy=True))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class CampaignRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mood_key = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    brief_summary = db.Column(db.String(500), nullable=True)
    asset_path = db.Column(db.String(500), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    is_ongoing = db.Column(db.Boolean, default=True)

    creator = db.relationship("User", backref=db.backref("campaign_rooms", lazy=True))
    members = db.relationship(
        "User",
        secondary=campaign_room_members,
        backref=db.backref("shared_rooms", lazy=True),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class RoomMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.String(500), nullable=False)
    track_key = db.Column(db.String(500), nullable=True)
    audio_ts = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    room = db.relationship("CampaignRoom", backref=db.backref("messages", lazy=True))
    user = db.relationship("User")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class RoomReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    track_key = db.Column(db.String(500), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    room = db.relationship("CampaignRoom", backref=db.backref("reactions", lazy=True))
    user = db.relationship("User")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    __table_args__ = (
        db.UniqueConstraint(
            "room_id", "user_id", "track_key", "emoji", name="uq_room_reaction"
        ),
    )


class RoomPin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    pin_type = db.Column(
        db.String(32), nullable=False
    )  # 'song', 'mood', 'trend', 'reference'
    content = db.Column(db.Text, nullable=False)
    label = db.Column(db.String(200), nullable=True)
    meta_json = db.Column(db.Text, nullable=True)  # Extra info like artist or color
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User", backref=db.backref("pins", lazy=True))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class RoomPoll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question = db.Column(db.String(500), nullable=False)
    options_json = db.Column(db.Text, nullable=False)  # List of strings
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User", backref=db.backref("polls", lazy=True))
    votes = db.relationship(
        "RoomPollVote", backref="poll", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class RoomPollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("room_poll.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    option_index = db.Column(db.Integer, nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class RoomEvent(db.Model):
    """Activity-feed event inside a campaign room."""

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    event_type = db.Column(db.String(32), nullable=False)
    body = db.Column(db.String(500), nullable=True)
    track_key = db.Column(db.String(500), nullable=True)
    meta_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    room = db.relationship("CampaignRoom", backref=db.backref("events", lazy=True))
    user = db.relationship("User")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


SONG_STATUSES = [
    "suggested",
    "in_discussion",
    "shortlisted",
    "approved",
    "rejected",
    "sent_to_client",
]

SONG_STATUS_LABELS = {
    "suggested": "Suggested",
    "in_discussion": "In Discussion",
    "shortlisted": "Shortlisted",
    "approved": "Approved",
    "rejected": "Rejected",
    "sent_to_client": "Sent to Client",
}


class SongStatus(db.Model):
    """Tracks the approval-pipeline stage for a song inside a campaign room."""

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    track_key = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="suggested")
    changed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reason = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    room = db.relationship(
        "CampaignRoom", backref=db.backref("song_statuses", lazy=True)
    )
    user = db.relationship("User")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    __table_args__ = (
        db.UniqueConstraint("room_id", "track_key", name="uq_song_status_per_room"),
    )


class ABTest(db.Model):
    """
    Classical (between-subjects) A/B test.

    Each participating user is randomly pre-assigned to Group A *or* Group B
    and sees only the song for their group.  They then answer:

      1. would_listen  – binary Yes/No  → two-proportion z-test
      2. rating        – numeric 1-5    → Welch's t-test

    Because no participant sees both songs this is the textbook definition of
    an A/B test (between-subjects design).
    """

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    song_a_key = db.Column(db.String(500), nullable=False)
    song_b_key = db.Column(db.String(500), nullable=False)
    title = db.Column(db.String(300), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    room = db.relationship("CampaignRoom", backref=db.backref("ab_tests", lazy=True))
    creator = db.relationship("User")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    votes = db.relationship("ABVote", backref="test", cascade="all, delete-orphan")


# Emotion scale retained for legacy/display purposes
AB_EMOTION_LABELS = {
    4: "Strong Positive 😍",
    3: "Positive 😊",
    2: "Neutral 😐",
    1: "Negative 😕",
}


class ABVote(db.Model):
    """
    A single participant's response in a classical A/B test.

    Fields
    ------
    assigned_group : 'a' or 'b'  – the song the participant was shown (random)
    chosen         : 'a' or 'b'  – kept equal to assigned_group for compatibility
    would_listen   : bool        – "Would you listen to this song?" (binary outcome)
    rating         : int 1-5     – numeric rating (continuous outcome)
    emotion_rating : int 1-4     – legacy emotion scale (kept for back-compat)
    """

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("ab_test.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_group = db.Column(db.String(1), nullable=False, default="a")  # 'a' or 'b'
    chosen = db.Column(db.String(1), nullable=False)                       # kept = assigned_group
    would_listen = db.Column(db.Boolean, nullable=True)                    # Yes / No
    rating = db.Column(db.Integer, nullable=True)                          # 1-5 numeric rating
    emotion_rating = db.Column(db.Integer, nullable=False, default=3)      # legacy 1-4
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    __table_args__ = (
        db.UniqueConstraint("test_id", "user_id", name="uq_ab_vote_per_user"),
    )


# Usage types for cue sheets (industry standard for PRO submission)
CUE_USAGE_TYPES = {
    "BI": "Background Instrumental",
    "BV": "Background Vocal",
    "VV": "Visual Vocal",
    "T": "Theme / Logo Sting",
    "MT": "Main Title",
    "ET": "End Title",
}


class CueSheetEntry(db.Model):
    """Music cue sheet entry for sync licensing documentation (PRO-ready)."""

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("campaign_room.id"), nullable=False)
    track_key = db.Column(db.String(500), nullable=False)
    cue_number = db.Column(db.Integer, nullable=False)
    usage_type = db.Column(db.String(10), nullable=False, default="BI")
    timecode_in = db.Column(db.String(20), nullable=True)  # "00:00:03"
    timecode_out = db.Column(db.String(20), nullable=True)  # "00:00:28"
    duration_sec = db.Column(db.Float, nullable=True)
    notes = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    room = db.relationship("CampaignRoom", backref=db.backref("cue_entries", lazy=True))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    __table_args__ = (
        db.UniqueConstraint("room_id", "cue_number", name="uq_cue_number_per_room"),
    )


class UserInteractionLog(db.Model):
    """Logs individual user interactions (play, skip, save) for learning personalization."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    track_name = db.Column(db.String(255), nullable=False)
    artist_name = db.Column(db.String(255), nullable=False)
    action = db.Column(db.String(32), nullable=False)  # 'play', 'skip', 'save'
    context = db.Column(
        db.String(64), nullable=True
    )  # 'cooking', 'studying', 'workout', 'chill', 'focus'
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship(
        "User",
        backref=db.backref("interaction_logs", lazy=True, cascade="all, delete-orphan"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


DEMO_USER_RENAMES = {
    "social_test@example.com": ("sofia.hart@gmail.com", "Sofia Hart"),
    "agent_test@example.com": ("ethan.brooks@gmail.com", "Ethan Brooks"),
    "marketing-demo-20260503@example.com": ("maya.patel@gmail.com", "Maya Patel"),
}


def init_db(app):
    db.init_app(app)


def migrate_user_preferences_columns():
    new_columns = [
        "ALTER TABLE user_preferences ADD COLUMN pref_danceability REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_energy REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_valence REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_acousticness REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_instrumentalness REAL DEFAULT 0.0",
        "ALTER TABLE user_preferences ADD COLUMN industry_focus TEXT DEFAULT ''",
        "ALTER TABLE user_preferences ADD COLUMN feature_weights TEXT DEFAULT '{}'",
        "ALTER TABLE user_preferences ADD COLUMN slider_positions TEXT DEFAULT '{}'",
        "ALTER TABLE user_preferences ADD COLUMN use_interaction_signal BOOLEAN DEFAULT 0",
        "ALTER TABLE user_preferences ADD COLUMN interaction_blend REAL DEFAULT 0.65",
        "ALTER TABLE user_preferences ADD COLUMN enable_personalized_similarity BOOLEAN DEFAULT 0",
        "ALTER TABLE user_preferences ADD COLUMN personalized_similarity_text TEXT DEFAULT ''",
        "ALTER TABLE user_preferences ADD COLUMN enable_genre_boost BOOLEAN DEFAULT 0",
        "ALTER TABLE user_preferences ADD COLUMN genre_boost_weight REAL DEFAULT 1.0",
        "ALTER TABLE user_preferences ADD COLUMN target_generation VARCHAR(50)",
        "ALTER TABLE user_preferences ADD COLUMN target_campaign VARCHAR(50)",
        "ALTER TABLE user_preferences ADD COLUMN roles TEXT DEFAULT ''",
        "ALTER TABLE user_preferences ADD COLUMN weight_base_audio REAL DEFAULT 0.40",
        "ALTER TABLE user_preferences ADD COLUMN weight_industry REAL DEFAULT 0.20",
        "ALTER TABLE user_preferences ADD COLUMN weight_generation REAL DEFAULT 0.20",
        "ALTER TABLE user_preferences ADD COLUMN weight_campaign REAL DEFAULT 0.20",
        "ALTER TABLE user_preferences ADD COLUMN enable_acoustic_matcher BOOLEAN DEFAULT 0",
    ]
    for sql in new_columns:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def migrate_campaign_room_columns():
    new_columns = [
        "ALTER TABLE campaign_room ADD COLUMN brief_summary VARCHAR(500)",
        "ALTER TABLE campaign_room ADD COLUMN asset_path VARCHAR(500)",
        "ALTER TABLE campaign_room ADD COLUMN is_ongoing BOOLEAN DEFAULT 1",
    ]
    for sql in new_columns:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def normalize_demo_users():
    for old_username, (new_username, display_name) in DEMO_USER_RENAMES.items():
        user = User.query.filter_by(username=old_username).first()
        if not user:
            continue

        user.username = new_username

        prefs = UserPreferences.query.filter_by(user_id=user.id).first()
        if prefs:
            prefs.display_name = display_name
        else:
            db.session.add(UserPreferences(user_id=user.id, display_name=display_name))

    db.session.commit()


def migrate_ab_vote_columns():
    """Add classical A/B test columns to the ab_vote table (safe ALTER TABLE)."""
    new_cols = [
        "ALTER TABLE ab_vote ADD COLUMN assigned_group VARCHAR(1) DEFAULT 'a'",
        "ALTER TABLE ab_vote ADD COLUMN would_listen BOOLEAN",
        "ALTER TABLE ab_vote ADD COLUMN rating INTEGER",
    ]
    for sql in new_cols:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def setup_database():
    db.create_all()
    migrate_user_preferences_columns()
    migrate_campaign_room_columns()
    migrate_ab_vote_columns()
    normalize_demo_users()
    # SongStatus table is created by db.create_all() above
