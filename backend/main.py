import os

from flask import Flask, render_template, session, request, redirect, url_for
import re
import json
from models.database import db, User, UserPreferences, init_db, setup_database
try:
    from routes.friend_routes import register_friend_routes
    from routes.recommendation_routes import register_recommendation_routes
    from routes.social_routes import register_social_routes
except ModuleNotFoundError:
    from backend.routes.friend_routes import register_friend_routes
    from backend.routes.recommendation_routes import register_recommendation_routes
    from backend.routes.social_routes import register_social_routes
from services.song_service import AUDIO_FEATURES, AVAILABLE_GENRES, get_saved_genres
from services.favorites_service import get_favorite_recommendation_keys, get_favorite_recommendations
from services.music_recommendation_service import get_feature_weight_controls, get_feature_weight_values, get_hybrid_recommendations
from services.social_service import get_community_recommendations, get_social_sidebar_data

_backend = os.path.dirname(os.path.abspath(__file__))
_frontend = os.path.join(_backend, "..", "frontend")
app = Flask(__name__,
    template_folder=os.path.join(_frontend, "templates"),
    static_folder=os.path.join(_frontend, "static"),
    instance_path=os.path.join(_backend, "instance"))
app.secret_key = "your_secret_key"# what is this

#config sql alchemy to work with flask
app.config["SQLALCHEMY_DATABASE_URI"]= "sqlite:///user.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False# we don't want to track modifications

init_db(app)
register_friend_routes(app)
register_recommendation_routes(app)
register_social_routes(app)
#REGEX validation
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
INVALID_EMAIL_WARNING = "Warning: enter a valid email address (example: name@email.com)."


def is_valid_email(value):
    return bool(EMAIL_REGEX.fullmatch(value))


def render_auth_page(error=None, success=None, email_value="", register_email_warning=None):
    return render_template(
        "index.html",
        error=error,
        success=success,
        email_value=email_value,
        register_email_warning=register_email_warning,
    )

#Routes
@app.route("/")
def home():
    return render_auth_page()#this is in the html

#Login
@app.route("/login",methods=["POST"])#sending info
def login():
    #collect info from the form
    email=request.form['email'].strip().lower()
    password=request.form['password']

    if not is_valid_email(email):
        return render_auth_page(error=INVALID_EMAIL_WARNING, email_value=email)

    # Stored in `username` column for DB compatibility.
    user=User.query.filter_by(username=email).first()
    if user and user.check_password(password):  #if these come true
        session['email']=user.username# a unique registration session
        return redirect(url_for('dashboard'))#where we send the user
    else:
        return render_auth_page(error="Invalid email or password", email_value=email)
    #we use an object
    #check if it's in the db/ login

    #otherwise show homepage
#Register
@app.route("/register",methods=["POST"])
def register():
    email=request.form['email'].strip().lower()
    password=request.form['password']

    if not is_valid_email(email):
        return render_auth_page(error=INVALID_EMAIL_WARNING, email_value=email)

    # Stored in `username` column for DB compatibility.
    user=User.query.filter_by(username=email).first()
    if user:#if the user is true, already in the db
        return render_auth_page(
            error="Email already registered",
            email_value=email,
            register_email_warning="This email is already taken. Try logging in or use another email.",
        )
    else:
        new_user= User (username=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return render_auth_page(success="Account created. Please log in.", email_value=email)

#Dashboard
@app.route("/dashboard")
def dashboard():
    if "email" not in session:
        return redirect(url_for('home'))
    user = User.query.filter_by(username=session['email']).first()
    prefs = UserPreferences.query.filter_by(user_id=user.id).first() if user else None
    social_sidebar = get_social_sidebar_data(user, prefs)
    community_recommendations = get_community_recommendations(user, prefs)
    selected_genres = get_saved_genres(prefs)
    display_name = (prefs.display_name or session['email']) if prefs else session['email']
    songs = get_hybrid_recommendations(user, prefs)
    favorite_recommendations = get_favorite_recommendations(user)
    favorite_recommendation_keys = get_favorite_recommendation_keys(user)
    profile_feature_values = {
        feat['key']: getattr(prefs, feat['key'], None) if prefs else None
        for feat in AUDIO_FEATURES
    }
    return render_template(
        "dashboard.html",
        email=session['email'],
        display_name=display_name,
        songs=songs,
        selected_genres=selected_genres,
        audio_features=AUDIO_FEATURES,
        profile_feature_values=profile_feature_values,
        social_sidebar=social_sidebar,
        community_recommendations=community_recommendations,
        favorite_recommendations=favorite_recommendations,
        favorite_recommendation_keys=favorite_recommendation_keys,
    )

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "email" not in session:
        return redirect(url_for('home'))
    user = User.query.filter_by(username=session['email']).first()
    prefs = UserPreferences.query.filter_by(user_id=user.id).first()

    if request.method == "POST":
        display_name = request.form.get('display_name', '').strip()
        selected_genres = request.form.getlist('genres')
        feature_weight_controls = get_feature_weight_controls()
        if prefs is None:
            prefs = UserPreferences(user_id=user.id)
            db.session.add(prefs)
        prefs.display_name = display_name
        prefs.genres = json.dumps(selected_genres)
        for feat in AUDIO_FEATURES:
            raw = request.form.get(feat['key'], '0.5')
            try:
                val = max(0.0, min(1.0, float(raw)))
            except ValueError:
                val = 0.5
            setattr(prefs, feat['key'], val)

        selected_weights = {}
        for item in feature_weight_controls:
            raw_weight = request.form.get(f"weight_{item['key']}", str(item['default']))
            try:
                selected_weights[item['key']] = max(0.0, min(2.0, float(raw_weight)))
            except ValueError:
                selected_weights[item['key']] = item['default']
        prefs.feature_weights = json.dumps(selected_weights)

        prefs.use_interaction_signal = request.form.get("use_interaction_signal") == "on"
        prefs.enable_personalized_similarity = request.form.get("enable_personalized_similarity") == "on"
        prefs.enable_genre_boost = request.form.get("enable_genre_boost") == "on"

        raw_blend = request.form.get("interaction_blend", "0.25")
        try:
            prefs.interaction_blend = max(0.0, min(0.8, float(raw_blend)))
        except ValueError:
            prefs.interaction_blend = 0.25

        raw_genre_boost = request.form.get("genre_boost_weight", "1")
        try:
            prefs.genre_boost_weight = float(max(1, min(3, int(round(float(raw_genre_boost))))))
        except ValueError:
            prefs.genre_boost_weight = 1.0

        prefs.personalized_similarity_text = request.form.get("personalized_similarity_text", "").strip()[:1000]

        db.session.commit()
        saved_genres = selected_genres
        return render_template("profile.html",
            email=session['email'],
            prefs=prefs,
            saved_genres=saved_genres,
            available_genres=AVAILABLE_GENRES,
            audio_features=AUDIO_FEATURES,
            feature_weight_controls=feature_weight_controls,
            feature_weight_values=get_feature_weight_values(prefs),
            success="Preferences saved successfully!")

    saved_genres = get_saved_genres(prefs)
    feature_weight_controls = get_feature_weight_controls()
    return render_template("profile.html",
        email=session['email'],
        prefs=prefs,
        saved_genres=saved_genres,
        available_genres=AVAILABLE_GENRES,
        audio_features=AUDIO_FEATURES,
        feature_weight_controls=feature_weight_controls,
        feature_weight_values=get_feature_weight_values(prefs))


@app.route("/favorites")
def favorites():
    if "email" not in session:
        return redirect(url_for('home'))

    user = User.query.filter_by(username=session['email']).first()
    prefs = UserPreferences.query.filter_by(user_id=user.id).first() if user else None
    display_name = (prefs.display_name or session['email']) if prefs else session['email']
    favorite_recommendations = get_favorite_recommendations(user)

    return render_template(
        "favorites.html",
        email=session['email'],
        display_name=display_name,
        favorite_recommendations=favorite_recommendations,
    )

#Logout
#pop it out the list
@app.route("/logout")
def logout():
    session.pop('email', None)
    return redirect(url_for('home'))
if __name__ == "__main__":
    with app.app_context():
        setup_database()
    app.run(debug=True)
