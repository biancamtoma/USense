from services.music_recommendation_service import cosine_similarity, get_recommendations
from services.song_service import AUDIO_FEATURES, get_saved_genres
from models.database import FriendMessage, FriendRequest, User, UserPreferences
import json

DEFAULT_FEATURE_VALUES = {
    "pref_danceability": 0.5,
    "pref_energy": 0.5,
    "pref_valence": 0.5,
    "pref_acousticness": 0.5,
    "pref_instrumentalness": 0.0,
}


def _pref_value(prefs, key):
    value = getattr(prefs, key, None) if prefs else None
    if value is None:
        return DEFAULT_FEATURE_VALUES[key]
    return value


def _get_preferences_map():
    return {prefs.user_id: prefs for prefs in UserPreferences.query.all()}


def _user_label(user, prefs_map):
    prefs = prefs_map.get(user.id)
    if prefs and prefs.display_name:
        return prefs.display_name
    return user.username.split("@")[0]


def _prefs_vector(prefs):
    return [_pref_value(prefs, feature["key"]) for feature in AUDIO_FEATURES]


def _preference_similarity(current_prefs, other_prefs):
    return cosine_similarity(_prefs_vector(current_prefs), _prefs_vector(other_prefs))


def _accepted_collaborator_requests_for_user(user_id):
    return FriendRequest.query.filter(
        FriendRequest.status == "accepted",
        ((FriendRequest.sender_id == user_id) | (FriendRequest.receiver_id == user_id)),
    ).all()


def get_collaborator_ids(user_id):
    collaborator_ids = set()
    for item in _accepted_collaborator_requests_for_user(user_id):
        collaborator_ids.add(
            item.receiver_id if item.sender_id == user_id else item.sender_id
        )
    return collaborator_ids


def are_collaborators(user_id, other_user_id):
    return other_user_id in get_collaborator_ids(user_id)


def get_collaborator_summary(user):
    if not user:
        return {
            "collaborators": [],
            "incoming_requests": [],
            "outgoing_requests": [],
        }

    prefs_map = _get_preferences_map()
    collaborators = []
    for item in _accepted_collaborator_requests_for_user(user.id):
        other_user = item.receiver if item.sender_id == user.id else item.sender
        if other_user:
            collaborators.append(
                {
                    "id": other_user.id,
                    "email": other_user.username,
                    "label": _user_label(other_user, prefs_map),
                    "request_id": item.id,
                }
            )

    incoming = FriendRequest.query.filter_by(
        receiver_id=user.id, status="pending"
    ).all()
    outgoing = FriendRequest.query.filter_by(sender_id=user.id, status="pending").all()

    return {
        "collaborators": sorted(collaborators, key=lambda item: item["email"].lower()),
        "incoming_requests": [
            {
                "id": item.id,
                "email": item.sender.username,
                "label": _user_label(item.sender, prefs_map),
            }
            for item in incoming
            if item.sender
        ],
        "outgoing_requests": [
            {
                "id": item.id,
                "email": item.receiver.username,
                "label": _user_label(item.receiver, prefs_map),
            }
            for item in outgoing
            if item.receiver
        ],
    }


def _mutual_taste_summary(current_prefs, other_prefs):
    shared_genres = sorted(
        set(get_saved_genres(current_prefs)) & set(get_saved_genres(other_prefs))
    )

    feature_weights = {}
    if current_prefs and getattr(current_prefs, "feature_weights", None):
        try:
            feature_weights = json.loads(current_prefs.feature_weights)
        except (TypeError, ValueError):
            feature_weights = {}

    feature_diffs = []
    for feature in AUDIO_FEATURES:
        current_value = _pref_value(current_prefs, feature["key"])
        other_value = _pref_value(other_prefs, feature["key"])
        diff = abs(current_value - other_value)
        column_key = feature["key"].replace("pref_", "")
        weight = float(feature_weights.get(column_key, 1.0))

        feature_diffs.append(
            {
                "label": feature["label"],
                "diff": diff,
                "weighted_distance": diff / max(0.1, weight),
                "current": current_value,
                "other": other_value,
            }
        )

    parts = []
    if shared_genres:
        parts.append("shared genres: " + ", ".join(shared_genres[:3]))

    closest = sorted(feature_diffs, key=lambda item: item["weighted_distance"])[:2]
    if closest:
        notes = []
        for item in closest:
            left = int(item["current"] * 100)
            right = int(item["other"] * 100)
            notes.append(f"{item['label']}: {left}% vs {right}%")
        parts.append("closest values: " + " | ".join(notes))
    else:
        parts.append("similar across audio preferences")

    return "; ".join(parts) if parts else "similar across audio preferences"


def get_social_sidebar_data(user, prefs):
    collaborator_summary = get_collaborator_summary(user)
    if not user:
        return {
            "collaborator_summary": collaborator_summary,
            "chat_threads": [],
            "suggested_people": [],
        }

    prefs_map = _get_preferences_map()
    current_collaborator_ids = {
        collaborator["id"] for collaborator in collaborator_summary["collaborators"]
    }
    pending_status_by_pair = {
        tuple(sorted((item.sender_id, item.receiver_id))): "pending"
        for item in FriendRequest.query.filter_by(status="pending").all()
    }

    chat_threads = []
    for collaborator in collaborator_summary["collaborators"]:
        collaborator_user = User.query.get(collaborator["id"])
        recent_messages = (
            FriendMessage.query.filter(
                (
                    (FriendMessage.sender_id == user.id)
                    & (FriendMessage.receiver_id == collaborator["id"])
                )
                | (
                    (FriendMessage.sender_id == collaborator["id"])
                    & (FriendMessage.receiver_id == user.id)
                )
            )
            .order_by(FriendMessage.created_at.desc(), FriendMessage.id.desc())
            .limit(3)
            .all()
        )

        chat_threads.append(
            {
                "collaborator_id": collaborator["id"],
                "collaborator_label": collaborator["label"],
                "collaborator_email": collaborator["email"],
                "recent_messages": [
                    {
                        "body": message.body,
                        "direction": (
                            "You"
                            if message.sender_id == user.id
                            else _user_label(collaborator_user, prefs_map)
                        ),
                    }
                    for message in reversed(recent_messages)
                ],
            }
        )

    suggested_people = []
    for candidate in User.query.order_by(User.username.asc()).all():
        if candidate.id == user.id:
            continue
        if candidate.username == "demo.supervisor@gmail.com":
            continue

        candidate_collaborator_ids = get_collaborator_ids(candidate.id)
        common_collaborator_ids = sorted(
            current_collaborator_ids & candidate_collaborator_ids
        )
        common_collaborator_count = len(common_collaborator_ids)
        common_collaborator_names = [
            _user_label(User.query.get(collaborator_id), prefs_map)
            for collaborator_id in common_collaborator_ids
            if User.query.get(collaborator_id)
        ]
        candidate_prefs = prefs_map.get(candidate.id)
        taste_match = _preference_similarity(prefs, candidate_prefs)
        if common_collaborator_count == 0 and taste_match < 0.94:
            continue

        pair_key = tuple(sorted((user.id, candidate.id)))
        pending_status = pending_status_by_pair.get(pair_key)
        is_collaborator = candidate.id in current_collaborator_ids

        suggested_people.append(
            {
                "email": candidate.username,
                "label": _user_label(candidate, prefs_map),
                "is_collaborator": is_collaborator,
                "common_collaborator_count": common_collaborator_count,
                "common_collaborator_names": common_collaborator_names[:3],
                "taste_match": int(taste_match * 100),
                "mutual_tastes": _mutual_taste_summary(prefs, candidate_prefs),
                "pending_status": pending_status,
            }
        )

    suggested_people.sort(
        key=lambda item: (item["common_collaborator_count"], item["taste_match"]),
        reverse=True,
    )

    return {
        "collaborator_summary": collaborator_summary,
        "chat_threads": chat_threads[:4],
        "suggested_people": suggested_people[:4],
    }


def get_community_recommendations(user, prefs, limit=6):
    if not user:
        return []

    prefs_map = _get_preferences_map()
    collaborator_ids = get_collaborator_ids(user.id)
    neighbors = []

    for candidate in User.query.order_by(User.username.asc()).all():
        if candidate.id == user.id:
            continue
        if candidate.username == "demo.supervisor@gmail.com":
            continue

        candidate_prefs = prefs_map.get(candidate.id)
        similarity = _preference_similarity(prefs, candidate_prefs)
        if similarity <= 0:
            continue

        is_collaborator = candidate.id in collaborator_ids
        relation_label = "Collaborator" if is_collaborator else "Not collaborator yet"
        neighbors.append(
            (candidate, relation_label, candidate_prefs, similarity, is_collaborator)
        )

    # Keep only the strongest neighbors so collaborative scoring favors closest users.
    neighbors.sort(key=lambda item: item[3], reverse=True)
    neighbors = neighbors[:12]

    if not neighbors:
        return []

    aggregated_tracks = {}
    for (
        candidate_user,
        relation_label,
        candidate_prefs,
        similarity,
        is_friend,
    ) in neighbors:
        for song in get_recommendations(candidate_prefs, n=3):
            track_key = (
                song["trackName"].strip().lower(),
                song["artistName"].strip().lower(),
            )
            weighted_song_score = similarity * song.get("raw_score", 0.0)

            if track_key not in aggregated_tracks:
                aggregated_tracks[track_key] = {
                    "score": 0.0,
                    "song": song,
                    "source_user": candidate_user,
                    "source_relation": relation_label,
                    "source_prefs": candidate_prefs,
                    "source_similarity": similarity,
                    "source_is_collaborator": is_friend,
                }

            aggregated_tracks[track_key]["score"] += weighted_song_score

            # Keep metadata from the closest contributing neighbor for explanation UI.
            if similarity > aggregated_tracks[track_key]["source_similarity"]:
                aggregated_tracks[track_key]["source_user"] = candidate_user
                aggregated_tracks[track_key]["source_relation"] = relation_label
                aggregated_tracks[track_key]["source_prefs"] = candidate_prefs
                aggregated_tracks[track_key]["source_similarity"] = similarity
                aggregated_tracks[track_key]["source_is_collaborator"] = is_friend

    ranked_tracks = sorted(
        aggregated_tracks.values(), key=lambda item: item["score"], reverse=True
    )
    picks = []
    for item in ranked_tracks[:limit]:
        source_user = item["source_user"]
        source_prefs = item["source_prefs"]
        source_similarity = item["source_similarity"]

        picks.append(
            {
                "source_label": _user_label(source_user, prefs_map),
                "source_email": source_user.username,
                "relation_label": item["source_relation"],
                "is_collaborator": item["source_is_collaborator"],
                "mutual_tastes": _mutual_taste_summary(prefs, source_prefs),
                "taste_match": int(source_similarity * 100),
                "song": item["song"],
            }
        )

    return picks


def get_full_social_data(user, prefs):
    """Return social data with larger limits for the dedicated /social page."""
    collaborator_summary = get_collaborator_summary(user)
    if not user:
        return {
            "collaborator_summary": collaborator_summary,
            "chat_threads": [],
            "suggested_people": [],
            "collaborator_profiles": [],
        }

    prefs_map = _get_preferences_map()
    current_collaborator_ids = {
        collaborator["id"] for collaborator in collaborator_summary["collaborators"]
    }
    pending_status_by_pair = {
        tuple(sorted((item.sender_id, item.receiver_id))): "pending"
        for item in FriendRequest.query.filter_by(status="pending").all()
    }

    # All collaborator chat threads (no limit)
    chat_threads = []
    for collaborator in collaborator_summary["collaborators"]:
        collaborator_user = User.query.get(collaborator["id"])
        recent_messages = (
            FriendMessage.query.filter(
                (
                    (FriendMessage.sender_id == user.id)
                    & (FriendMessage.receiver_id == collaborator["id"])
                )
                | (
                    (FriendMessage.sender_id == collaborator["id"])
                    & (FriendMessage.receiver_id == user.id)
                )
            )
            .order_by(FriendMessage.created_at.desc(), FriendMessage.id.desc())
            .limit(5)
            .all()
        )

        chat_threads.append(
            {
                "collaborator_id": collaborator["id"],
                "collaborator_label": collaborator["label"],
                "collaborator_email": collaborator["email"],
                "request_id": collaborator["request_id"],
                "recent_messages": [
                    {
                        "body": message.body,
                        "direction": (
                            "You"
                            if message.sender_id == user.id
                            else _user_label(collaborator_user, prefs_map)
                        ),
                    }
                    for message in reversed(recent_messages)
                ],
            }
        )

    # More suggested people (up to 8)
    suggested_people = []
    for candidate in User.query.order_by(User.username.asc()).all():
        if candidate.id == user.id:
            continue
        if candidate.username == "demo.supervisor@gmail.com":
            continue

        candidate_collaborator_ids = get_collaborator_ids(candidate.id)
        common_collaborator_ids = sorted(
            current_collaborator_ids & candidate_collaborator_ids
        )
        common_collaborator_count = len(common_collaborator_ids)
        common_collaborator_names = [
            _user_label(User.query.get(collaborator_id), prefs_map)
            for collaborator_id in common_collaborator_ids
            if User.query.get(collaborator_id)
        ]
        candidate_prefs = prefs_map.get(candidate.id)
        taste_match = _preference_similarity(prefs, candidate_prefs)
        if common_collaborator_count == 0 and taste_match < 0.94:
            continue

        pair_key = tuple(sorted((user.id, candidate.id)))
        pending_status = pending_status_by_pair.get(pair_key)
        is_collaborator = candidate.id in current_collaborator_ids

        suggested_people.append(
            {
                "email": candidate.username,
                "label": _user_label(candidate, prefs_map),
                "is_collaborator": is_collaborator,
                "common_collaborator_count": common_collaborator_count,
                "common_collaborator_names": common_collaborator_names[:3],
                "taste_match": int(taste_match * 100),
                "mutual_tastes": _mutual_taste_summary(prefs, candidate_prefs),
                "pending_status": pending_status,
            }
        )

    suggested_people.sort(
        key=lambda item: (item["common_collaborator_count"], item["taste_match"]),
        reverse=True,
    )

    # Compile Collaborator Profiles
    collaborator_profiles = []
    from services.favorites_service import get_favorite_recommendations

    for collaborator in collaborator_summary["collaborators"]:
        collaborator_user = User.query.get(collaborator["id"])
        collaborator_prefs = prefs_map.get(collaborator["id"])
        if collaborator_user:
            raw_favorites = get_favorite_recommendations(collaborator_user)
            favorites = [
                {
                    "trackName": f.track_name,
                    "artistName": f.artist_name,
                    "genre": f.genre,
                    "spotify_url": f.spotify_url,
                    "color": f.color,
                }
                for f in raw_favorites[:3]
            ]

            from services.song_service import AUDIO_FEATURES

            pref_values = {
                feat["label"]: int(
                    _pref_value(collaborator_prefs, feat["key"]) * 100
                )
                for feat in AUDIO_FEATURES
            }

            collaborator_profiles.append(
                {
                    "id": collaborator["id"],
                    "label": collaborator["label"],
                    "email": collaborator["email"],
                    "preferences": pref_values,
                    "favorites": favorites,
                }
            )

    return {
        "collaborator_summary": collaborator_summary,
        "chat_threads": chat_threads,
        "suggested_people": suggested_people[:8],
        "collaborator_profiles": collaborator_profiles,
    }
