import json
import re
from types import SimpleNamespace

DEFAULT_PROFILE = {
    "label": "Mood brief",
    "emoji": "\U0001f3b5",
    "color": "#0f766e",
    "summary": "electronic, mid-tempo, low warmth",
    "genres": ["electronic", "tech house", "synthpop"],
    "prefs": {
        "pref_danceability": 0.58,
        "pref_energy": 0.62,
        "pref_valence": 0.38,
        "pref_acousticness": 0.10,
        "pref_instrumentalness": 0.58,
    },
}

MOOD_TRANSLATION_RULES = [
    {
        "tokens": {"modern", "clean", "techy", "tech", "sleek", "polished", "digital"},
        "profile": {
            "label": "Modern / Clean / Techy",
            "emoji": "\U0001f3a7",
            "color": "#0f766e",
            "summary": "electronic, mid-tempo, low warmth",
            "genres": ["electronic", "tech house", "synthpop", "uk dance"],
            "prefs": {
                "pref_danceability": 0.58,
                "pref_energy": 0.62,
                "pref_valence": 0.38,
                "pref_acousticness": 0.10,
                "pref_instrumentalness": 0.58,
            },
        },
    },
    {
        "tokens": {"warm", "cozy", "organic", "acoustic", "soft", "human"},
        "profile": {
            "label": "Warm / Organic",
            "emoji": "\U0001f3b6",
            "color": "#b45309",
            "summary": "acoustic, slower, high warmth",
            "genres": ["acoustic", "indie folk", "singer-songwriter"],
            "prefs": {
                "pref_danceability": 0.38,
                "pref_energy": 0.34,
                "pref_valence": 0.62,
                "pref_acousticness": 0.82,
                "pref_instrumentalness": 0.22,
            },
        },
    },
    {
        "tokens": {"dark", "edgy", "aggressive", "bold", "intense", "gritty"},
        "profile": {
            "label": "Dark / Bold",
            "emoji": "\U0001f525",
            "color": "#991b1b",
            "summary": "driving, high energy, low warmth",
            "genres": ["electronic", "trap", "industrial"],
            "prefs": {
                "pref_danceability": 0.52,
                "pref_energy": 0.90,
                "pref_valence": 0.20,
                "pref_acousticness": 0.06,
                "pref_instrumentalness": 0.44,
            },
        },
    },
]


def _copy_recommendation_context(source, target):
    if not source:
        return

    if hasattr(source, "__table__"):
        for column in source.__table__.columns:
            setattr(target, column.name, getattr(source, column.name))
        return

    for attr in (
        "genres",
        "feature_weights",
        "use_interaction_signal",
        "interaction_blend",
        "enable_personalized_similarity",
        "personalized_similarity_text",
        "enable_genre_boost",
        "genre_boost_weight",
        "user_id",
        "display_name",
        "weight_base_audio",
        "weight_industry",
        "weight_generation",
        "weight_campaign",
        "target_generation",
        "target_campaign",
        "enable_acoustic_matcher",
        "roles",
        "industry_focus",
    ):
        setattr(target, attr, getattr(source, attr, None))


def _select_profile(tokens):
    best_rule = None
    best_score = 0
    for rule in MOOD_TRANSLATION_RULES:
        score = len(tokens.intersection(rule["tokens"]))
        if score > best_score:
            best_rule = rule
            best_score = score

    return best_rule["profile"] if best_rule else DEFAULT_PROFILE


def build_mood_preferences(brief_text, base_prefs=None):
    """Translate a short mood brief into the recommender's numeric preference fields."""

    cleaned = re.sub(r"[^a-z0-9\s-]+", " ", (brief_text or "").strip().lower())
    compact = " ".join(cleaned.split())
    tokens = set(compact.split())
    profile = _select_profile(tokens)

    mood_prefs = SimpleNamespace()
    _copy_recommendation_context(base_prefs, mood_prefs)

    mood_prefs.genres = json.dumps(profile["genres"])
    for key, value in profile["prefs"].items():
        setattr(mood_prefs, key, value)

    translation = {
        "label": profile["label"],
        "emoji": profile["emoji"],
        "color": profile["color"],
        "brief": brief_text,
        "normalized_brief": compact,
        "summary": profile["summary"],
        "genres": list(profile["genres"]),
        "preferences": dict(profile["prefs"]),
    }

    mood_prefs.mood_translation = translation
    mood_prefs.mood_brief = brief_text
    return mood_prefs, translation


def parse_creative_notes_nlp(notes_text, base_prefs):
    """
    NLP parser for marketing creative notes. Extracts adjectives and semantic keywords
    to dynamically shift audio target preferences (Valence, Energy, Danceability, etc.).
    """
    if not notes_text:
        return base_prefs, []

    from types import SimpleNamespace

    # Copy base preferences
    prefs = SimpleNamespace()
    for attr in (
        "genres",
        "pref_danceability",
        "pref_energy",
        "pref_valence",
        "pref_acousticness",
        "pref_instrumentalness",
    ):
        setattr(prefs, attr, getattr(base_prefs, attr, 0.5))

    # Copy context attributes if they exist
    if base_prefs:
        for attr in (
            "genres",
            "feature_weights",
            "use_interaction_signal",
            "interaction_blend",
            "enable_personalized_similarity",
            "personalized_similarity_text",
            "enable_genre_boost",
            "genre_boost_weight",
            "user_id",
            "display_name",
        ):
            if hasattr(base_prefs, attr):
                setattr(prefs, attr, getattr(base_prefs, attr))

    # Semantic Keyword Rules
    keywords_map = {
        # Valence shifts (Brand Sentiment / Uplift)
        "happy": ("pref_valence", 0.25),
        "joy": ("pref_valence", 0.25),
        "uplifting": ("pref_valence", 0.20),
        "bright": ("pref_valence", 0.15),
        "positive": ("pref_valence", 0.15),
        "fun": ("pref_valence", 0.20),
        "sad": ("pref_valence", -0.30),
        "emotional": ("pref_valence", -0.15),
        "somber": ("pref_valence", -0.25),
        "serious": ("pref_valence", -0.15),
        "dark": ("pref_valence", -0.20),
        # Energy shifts (Attention Grab / Narrative Pace)
        "energetic": ("pref_energy", 0.25),
        "hype": ("pref_energy", 0.30),
        "intense": ("pref_energy", 0.25),
        "loud": ("pref_energy", 0.20),
        "fast": ("pref_energy", 0.15),
        "active": ("pref_energy", 0.20),
        "calm": ("pref_energy", -0.25),
        "soft": ("pref_energy", -0.20),
        "peaceful": ("pref_energy", -0.25),
        "quiet": ("pref_energy", -0.20),
        "relaxing": ("pref_energy", -0.20),
        "background": ("pref_energy", -0.15),
        # Danceability shifts (UGC Scroll-Stopping)
        "danceable": ("pref_danceability", 0.25),
        "rhythmic": ("pref_danceability", 0.20),
        "groove": ("pref_danceability", 0.20),
        "tempo": ("pref_danceability", 0.10),
        "beat": ("pref_danceability", 0.15),
        # Acousticness shifts (Organic texture)
        "acoustic": ("pref_acousticness", 0.30),
        "organic": ("pref_acousticness", 0.25),
        "natural": ("pref_acousticness", 0.20),
        "piano": ("pref_acousticness", 0.15),
        "guitar": ("pref_acousticness", 0.15),
        "electronic": ("pref_acousticness", -0.25),
        "synth": ("pref_acousticness", -0.25),
        "digital": ("pref_acousticness", -0.20),
        # Instrumentalness shifts (Voiceover headroom)
        "instrumental": ("pref_instrumentalness", 0.40),
        "voiceover": ("pref_instrumentalness", 0.30),
        "headroom": ("pref_instrumentalness", 0.25),
        "narration": ("pref_instrumentalness", 0.30),
        "clean": ("pref_instrumentalness", 0.15),
        "vocals": ("pref_instrumentalness", -0.30),
        "lyrical": ("pref_instrumentalness", -0.35),
    }

    words = re.sub(r"[^a-z0-9\s-]+", " ", notes_text.lower()).split()
    matched_keywords = []

    for word in words:
        if word in keywords_map:
            feat, shift = keywords_map[word]
            current_val = getattr(prefs, feat, 0.5)
            new_val = max(0.0, min(1.0, current_val + shift))
            setattr(prefs, feat, new_val)
            matched_keywords.append(word.capitalize())

    matched_keywords = list(set(matched_keywords))
    return prefs, matched_keywords
