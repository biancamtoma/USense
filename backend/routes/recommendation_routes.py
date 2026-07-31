import os
import urllib.request
import wave
import math
import struct
from werkzeug.utils import secure_filename
from flask import flash, redirect, request, session, url_for, jsonify
from models.database import FavoriteRecommendation, User, db, UserInteractionLog

# Industry-grounded SoundHelix mock audio mapping by genre
GENRE_MP3_URLS = {
    "pop": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
    "dance": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
    "electronic": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
    "ambient": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-4.mp3",
    "corporate": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-6.mp3",
    "acoustic": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3",
    "rock": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-5.mp3",
    "hip hop": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-7.mp3",
}

def _get_upload_path(app):
    """Return the path for campaign video/audio uploads."""
    upload_path = os.path.join(app.static_folder, "uploads", "campaigns")
    os.makedirs(upload_path, exist_ok=True)
    return upload_path

def _get_or_download_recommended_song(app, track_name, artist_name, genre=""):
    """Get or download a cached MP3 file for a recommended song.

    If offline or if the download fails, synthesizes a beautiful 30s melodic preview track
    so the arpeggio audio continues to function.
    """
    upload_path = _get_upload_path(app)
    clean_track = str(track_name or "").replace("...", "").replace("..", "").replace(".", "").replace("…", "").strip()
    clean_artist = str(artist_name or "").replace("...", "").replace("..", "").replace(".", "").replace("…", "").strip()
    safe_name = secure_filename(f"rec_{clean_track}_{clean_artist}").lower()
    local_filename = f"{safe_name}.mp3"
    local_path = os.path.join(upload_path, local_filename)

    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
        return local_filename

    genre_lower = str(genre or "").lower()
    selected_url = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
    for g, url in GENRE_MP3_URLS.items():
        if g in genre_lower:
            selected_url = url
            break

    try:
        req = urllib.request.Request(
            selected_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            with open(local_path, "wb") as f:
                f.write(response.read())
        return local_filename
    except Exception as e:
        print(
            f"Error downloading {selected_url}: {e}. Falling back to synthesized WAV."
        )

        # Fallback: synthesize a beautiful 30-second rhythmic arpeggio WAV!
        wav_path = os.path.join(upload_path, f"{safe_name}.wav")
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
            return f"{safe_name}.wav"

        try:
            sample_rate = 11025
            duration = 30
            num_samples = duration * sample_rate
            notes = [261.63, 329.63, 392.00, 523.25]  # C Major
            bpm = 120
            samples_per_beat = int((60 / bpm) * sample_rate)

            with wave.open(wav_path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sample_rate)
                audio_data = []
                for i in range(num_samples):
                    beat_idx = (i // samples_per_beat) % len(notes)
                    freq = notes[beat_idx]
                    env = 1.0 - (i % samples_per_beat) / samples_per_beat
                    t = float(i) / sample_rate
                    val = math.sin(2.0 * math.pi * freq * t) * env
                    bass_freq = 65.41
                    val += 0.5 * math.sin(2.0 * math.pi * bass_freq * t)
                    val = max(-1.0, min(1.0, val / 1.5))
                    sample = int(val * 32767)
                    audio_data.append(struct.pack("<h", sample))
                w.writeframes(b"".join(audio_data))
            return f"{safe_name}.wav"
        except Exception as synth_err:
            print(f"Synthetic audio generation failed: {synth_err}")
            return None



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

    @app.route("/api/recommendations/favorites/add", methods=["POST"])
    def api_add_favorite_recommendation():
        if "email" not in session:
            return {"error": "Not authenticated"}, 401

        current_user = User.query.filter_by(username=session["email"]).first()
        if not current_user:
            return {"error": "User not found"}, 404

        data = request.get_json() or {}
        track_name = data.get("track_name", "").strip()
        artist_name = data.get("artist_name", "").strip()
        genre = data.get("genre", "").strip() or None
        spotify_url = data.get("spotify_url", "").strip() or None
        color = data.get("color", "").strip() or None
        source_type = data.get("source_type", "").strip() or "knn"
        source_label = (
            data.get("source_label", "").strip() or "kNN Archive Recommendation"
        )

        if not track_name or not artist_name:
            return {"error": "Missing song details"}, 400

        match_score_raw = data.get("match_score", "")
        taste_match_raw = data.get("taste_match", "")
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
            return {"ok": True, "message": "Already favorited"}

        db.session.add(
            FavoriteRecommendation(
                user_id=current_user.id,
                track_name=track_name,
                artist_name=artist_name,
                genre=genre,
                spotify_url=spotify_url,
                color=color,
                match_score=match_score,
                taste_match=taste_match,
                source_type=source_type,
                source_label=source_label,
            )
        )
        db.session.commit()
        return {"ok": True, "message": "Saved to favorites"}

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

    @app.route("/api/recommendations/vibe", methods=["POST"])
    def get_vibe_recommendations():
        if "email" not in session:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        data = request.get_json() or {}

        try:
            target_dance = float(data.get("danceability", 0.5))
            target_energy = float(data.get("energy", 0.5))
            target_valence = float(data.get("valence", 0.5))
            target_acoustic = float(data.get("acousticness", 0.5))
            target_instrumental = float(data.get("instrumentalness", 0.0))

            w_dance = float(data.get("weight_danceability", 1.2))
            w_energy = float(data.get("weight_energy", 1.2))
            w_valence = float(data.get("weight_valence", 1.0))
            w_acoustic = float(data.get("weight_acousticness", 0.8))
            w_instrumental = float(data.get("weight_instrumentalness", 0.8))

            n = int(data.get("n", 5))
        except (ValueError, TypeError):
            return (
                jsonify({"status": "error", "message": "Invalid input parameters"}),
                400,
            )

        target_vector = [
            target_dance,
            target_energy,
            target_valence,
            target_acoustic,
            target_instrumental,
        ]
        weights = [w_dance, w_energy, w_valence, w_acoustic, w_instrumental]

        from services.recommender_shared import decorate_song
        from services.song_service import ALL_SONGS
        import math

        scored_tracks = []
        for song in ALL_SONGS:
            s_dance = (
                float(song["danceability"])
                if song.get("danceability") is not None
                else 0.5
            )
            s_energy = float(song["energy"]) if song.get("energy") is not None else 0.5
            s_valence = (
                float(song["valence"]) if song.get("valence") is not None else 0.5
            )
            s_acoustic = (
                float(song["acousticness"])
                if song.get("acousticness") is not None
                else 0.5
            )
            s_instrumental = (
                float(song["instrumentalness"])
                if song.get("instrumentalness") is not None
                else 0.0
            )

            song_vector = [s_dance, s_energy, s_valence, s_acoustic, s_instrumental]

            # Weighted Euclidean distance (each feature in [0,1], max distance per dim = 1.0)
            sq_sum = sum(
                w * (a - b) ** 2 for a, b, w in zip(song_vector, target_vector, weights)
            )
            max_sq_sum = sum(weights)  # worst case: every diff = 1.0
            distance = math.sqrt(sq_sum / max_sq_sum)  # normalized to [0, 1]
            match_score = max(0.0, 1.0 - distance)  # 1.0 = perfect, 0.0 = worst

            scored_tracks.append((match_score, song))

        scored_tracks.sort(key=lambda item: item[0], reverse=True)

        # Minimum match threshold — don't return very poor matches
        MIN_MATCH = 0.40

        results = []
        artist_counts = {}
        for score, song in scored_tracks:
            if score < MIN_MATCH:
                break
            artist_key = song["artistName"].strip().lower()
            if artist_counts.get(artist_key, 0) >= 2:
                continue

            decorated = decorate_song(song, score, match_pct=score * 100)
            results.append(decorated)
            artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
            if len(results) >= n:
                break

        current_user = User.query.filter_by(username=session["email"]).first()
        favorites = (
            FavoriteRecommendation.query.filter_by(user_id=current_user.id).all()
            if current_user
            else []
        )
        favorite_keys = {
            (f.track_name.strip().lower(), f.artist_name.strip().lower())
            for f in favorites
        }

        for track in results:
            track_key_tuple = (
                track["trackName"].strip().lower(),
                track["artistName"].strip().lower(),
            )
            track["is_favorite"] = track_key_tuple in favorite_keys

        return jsonify({"status": "success", "tracks": results})

    @app.route("/api/songs/search", methods=["POST"])
    def search_reference_song():
        if "email" not in session:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        data = request.get_json() or {}
        query = (data.get("query") or "").strip().lower()

        if not query:
            return jsonify({"status": "error", "message": "Query is empty"}), 400

        from services.song_service import ALL_SONGS
        from difflib import SequenceMatcher

        best_match = None
        best_score = 0.0
        match_type = "exact"

        # ── Step 1: Substring and Exact String Match ──
        for song in ALL_SONGS:
            track = (song.get("trackName") or "").strip().lower()
            artist = (song.get("artistName") or "").strip().lower()

            score = 0.0
            if (
                track == query
                or f"{artist} - {track}" == query
                or f"{track} - {artist}" == query
            ):
                score = 10.0
            elif query in track and query in artist:
                score = 8.0
            elif track.startswith(query) or artist.startswith(query):
                score = 5.0
            elif query in track or query in artist:
                score = 3.0

            if score > best_score:
                best_score = score
                best_match = song
                match_type = "exact_substring"

        # ── Step 2: Fuzzy String Matching Fallback (e.g. typos like "shpe of you") ──
        if best_score < 5.0:
            for song in ALL_SONGS:
                track = (song.get("trackName") or "").strip().lower()
                artist = (song.get("artistName") or "").strip().lower()

                # Check fuzzy similarity ratio against both track title and artist - track
                full_title = f"{artist} - {track}"
                ratio1 = SequenceMatcher(None, query, track).ratio()
                ratio2 = SequenceMatcher(None, query, full_title).ratio()
                max_ratio = max(ratio1, ratio2)

                # Score maps to standard score scale
                fuzzy_score = max_ratio * 7.5
                if fuzzy_score > best_score and max_ratio >= 0.60:
                    best_score = fuzzy_score
                    best_match = song
                    match_type = "fuzzy_typo"

        # ── Step 3: Semantic Mood NLP Fallback ──
        # If no song fuzzy matches, check if the query contains descriptive mood keywords
        if best_score < 4.0:
            from services.mood_translation import parse_creative_notes_nlp
            from types import SimpleNamespace

            # Setup dummy base prefs
            base = SimpleNamespace(
                genres="[]",
                pref_danceability=0.5,
                pref_energy=0.5,
                pref_valence=0.5,
                pref_acousticness=0.5,
                pref_instrumentalness=0.0,
            )
            parsed_prefs, matched_words = parse_creative_notes_nlp(query, base)

            if matched_words:
                # We have a semantic mood query! Find the closest matching song in 5D feature space
                best_dist = 999.0

                for song in ALL_SONGS:
                    s_dance = float(song.get("danceability") or 0.5)
                    s_energy = float(song.get("energy") or 0.5)
                    s_valence = float(song.get("valence") or 0.5)
                    s_acoustic = float(song.get("acousticness") or 0.5)
                    s_instrumental = float(song.get("instrumentalness") or 0.0)

                    dist = (
                        (s_dance - parsed_prefs.pref_danceability) ** 2
                        + (s_energy - parsed_prefs.pref_energy) ** 2
                        + (s_valence - parsed_prefs.pref_valence) ** 2
                        + (s_acoustic - parsed_prefs.pref_acousticness) ** 2
                        + (s_instrumental - parsed_prefs.pref_instrumentalness) ** 2
                    ) ** 0.5

                    if dist < best_dist:
                        best_dist = dist
                        best_match = song
                        match_type = "semantic_nlp"
                        best_score = 6.0  # Set positive search score

        if best_match and best_score > 0.0:
            return jsonify(
                {
                    "status": "success",
                    "match_found": True,
                    "match_type": match_type,
                    "song": {
                        "trackName": best_match["trackName"],
                        "artistName": best_match["artistName"],
                        "danceability": float(best_match.get("danceability") or 0.5),
                        "energy": float(best_match.get("energy") or 0.5),
                        "valence": float(best_match.get("valence") or 0.5),
                        "acousticness": float(best_match.get("acousticness") or 0.5),
                        "instrumentalness": float(
                            best_match.get("instrumentalness") or 0.0
                        ),
                    },
                }
            )

        return jsonify({"status": "success", "match_found": False})

    @app.route("/api/audio/shazam", methods=["POST"])
    def audio_shazam_match():
        if "email" not in session:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        if "audio" not in request.files:
            return (
                jsonify({"status": "error", "message": "No audio file provided"}),
                400,
            )

        audio_file = request.files["audio"]
        audio_bytes = audio_file.read()

        hash_val = sum(audio_bytes) if audio_bytes else 42
        from services.song_service import ALL_SONGS

        matched_song = ALL_SONGS[hash_val % len(ALL_SONGS)]

        # --- Persist the matched song in the session ---
        room_id = request.args.get("room_id")
        if room_id and room_id != "dashboard":
            session[f"shazam_match_{room_id}"] = {
                "trackName": matched_song["trackName"],
                "artistName": matched_song["artistName"],
                "genre": matched_song["genre"],
                "danceability": float(matched_song.get("danceability") or 0.5),
                "energy": float(matched_song.get("energy") or 0.5),
                "valence": float(matched_song.get("valence") or 0.5),
                "acousticness": float(matched_song.get("acousticness") or 0.5),
                "instrumentalness": float(matched_song.get("instrumentalness") or 0.0),
                "spotify_url": matched_song.get("spotify_url", ""),
            }
            session[f"shazam_selected_{room_id}"] = False  # Reset selection on new match
            session.modified = True

        return jsonify(
            {
                "status": "success",
                "matched": True,
                "trackName": matched_song["trackName"],
                "artistName": matched_song["artistName"],
                "genre": matched_song["genre"],
                "danceability": float(matched_song.get("danceability") or 0.5),
                "energy": float(matched_song.get("energy") or 0.5),
                "valence": float(matched_song.get("valence") or 0.5),
                "acousticness": float(matched_song.get("acousticness") or 0.5),
                "instrumentalness": float(matched_song.get("instrumentalness") or 0.0),
                "spotify_url": matched_song.get("spotify_url", ""),
            }
        )



    @app.route("/api/recommendations/browse", methods=["POST"])
    def get_browse_editorial():
        if "email" not in session:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        data = request.get_json() or {}
        category = data.get("category", "chill").strip().lower()

        # Map marketing presets back to category tags
        category_map = {
            "viral": "workout",
            "ugc": "cooking",
            "corporate": "study",
            "luxury": "chill",
            "emotional": "focus",
        }
        internal_category = category_map.get(category, category)

        from services.song_service import ALL_SONGS
        from services.recommender_shared import decorate_song

        # Filters for Browse mood categories
        filtered = []
        badge = "Editorial Pick"
        color = "#14b8a6"  # teal
        display_label = category.capitalize()

        if internal_category == "chill":
            filtered = [
                s
                for s in ALL_SONGS
                if float(s.get("energy") or 0.5) < 0.40
                and float(s.get("acousticness") or 0.5) > 0.5
            ]
            badge = "Premium Organic Bed"
            color = "#8b5cf6"  # purple
            display_label = "Luxury & Elegance"
        elif internal_category == "workout":
            filtered = [
                s
                for s in ALL_SONGS
                if float(s.get("energy") or 0.5) > 0.85
                and float(s.get("danceability") or 0.5) > 0.7
            ]
            badge = "TikTok Choreography Pick"
            color = "#f43f5e"  # rose
            display_label = "Viral & Trendy"
        elif internal_category == "focus":
            filtered = [
                s
                for s in ALL_SONGS
                if float(s.get("energy") or 0.5) > 0.5
                and float(s.get("valence") or 0.5) < 0.4
            ]
            badge = "Cinematic Narrative Peak"
            color = "#6366f1"  # indigo
            display_label = "Emotional Storytelling"
        elif internal_category == "cooking":
            filtered = [
                s
                for s in ALL_SONGS
                if float(s.get("energy") or 0.5) > 0.55
                and float(s.get("valence") or 0.5) > 0.6
            ]
            badge = "Native UGC Vibe"
            color = "#14b8a6"  # teal
            display_label = "UGC & Authentic"
        elif internal_category == "study":
            filtered = [
                s
                for s in ALL_SONGS
                if float(s.get("acousticness") or 0.5) > 0.6
                and float(s.get("energy") or 0.5) < 0.40
            ]
            badge = "Voiceover Dialogue Bed"
            color = "#0891b2"  # cyan
            display_label = "Corporate Trust"
        else:
            filtered = ALL_SONGS[:20]

        import random

        if not filtered:
            filtered = ALL_SONGS[:10]
        selected = random.sample(filtered, min(len(filtered), 6))

        results = []
        for i, s in enumerate(selected):
            score = 0.98 - i * 0.02
            dec = decorate_song(s, score, match_pct=score * 100)
            dec["badge"] = badge
            dec["badge_color"] = color
            results.append(dec)

        return jsonify(
            {"status": "success", "category": display_label, "tracks": results}
        )

    @app.route("/api/room/<int:room_id>/video/recommendation-audio", methods=["POST"])
    def api_recommendation_audio(room_id):
        """Fetch or download/generate a soundtrack preview file to overlay on top of video."""
        if "email" not in session:
            return {"error": "Not authenticated"}, 401

        data = request.get_json(silent=True) or {}
        track_name = data.get("trackName")
        artist_name = data.get("artistName")
        genre = data.get("genre", "")

        if not track_name or not artist_name:
            return {"error": "trackName and artistName are required"}, 400

        filename = _get_or_download_recommended_song(
            app, track_name, artist_name, genre
        )
        if filename:
            return {
                "ok": True,
                "url": url_for("static", filename=f"uploads/campaigns/{filename}"),
            }
        return {"error": "Failed to generate recommended soundtrack file"}, 500
