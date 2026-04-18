from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(256), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class UserPreferences(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    genres = db.Column(db.Text, default="[]")
    pref_danceability = db.Column(db.Float, default=0.5)
    pref_energy = db.Column(db.Float, default=0.5)
    pref_valence = db.Column(db.Float, default=0.5)
    pref_acousticness = db.Column(db.Float, default=0.5)
    pref_instrumentalness = db.Column(db.Float, default=0.0)
    feature_weights = db.Column(db.Text, default="{}")
    use_interaction_signal = db.Column(db.Boolean, default=False)
    interaction_blend = db.Column(db.Float, default=0.25)
    enable_personalized_similarity = db.Column(db.Boolean, default=False)
    personalized_similarity_text = db.Column(db.Text, default="")
    enable_genre_boost = db.Column(db.Boolean, default=False)
    genre_boost_weight = db.Column(db.Float, default=1.0)


class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    __table_args__ = (
        db.CheckConstraint("sender_id != receiver_id", name="ck_friend_request_not_self"),
    )


class FriendMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    __table_args__ = (
        db.CheckConstraint("sender_id != receiver_id", name="ck_friend_message_not_self"),
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

    user = db.relationship("User", backref=db.backref("favorite_recommendations", lazy=True))

    __table_args__ = (
        db.UniqueConstraint("user_id", "track_name", "artist_name", name="uq_favorite_track_per_user"),
    )


def init_db(app):
    db.init_app(app)


def migrate_user_preferences_columns():
    new_columns = [
        "ALTER TABLE user_preferences ADD COLUMN pref_danceability REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_energy REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_valence REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_acousticness REAL DEFAULT 0.5",
        "ALTER TABLE user_preferences ADD COLUMN pref_instrumentalness REAL DEFAULT 0.0",
        "ALTER TABLE user_preferences ADD COLUMN feature_weights TEXT DEFAULT '{}'",
        "ALTER TABLE user_preferences ADD COLUMN use_interaction_signal BOOLEAN DEFAULT 0",
        "ALTER TABLE user_preferences ADD COLUMN interaction_blend REAL DEFAULT 0.25",
        "ALTER TABLE user_preferences ADD COLUMN enable_personalized_similarity BOOLEAN DEFAULT 0",
        "ALTER TABLE user_preferences ADD COLUMN personalized_similarity_text TEXT DEFAULT ''",
        "ALTER TABLE user_preferences ADD COLUMN enable_genre_boost BOOLEAN DEFAULT 0",
        "ALTER TABLE user_preferences ADD COLUMN genre_boost_weight REAL DEFAULT 1.0",
    ]
    for sql in new_columns:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def setup_database():
    db.create_all()
    migrate_user_preferences_columns()
