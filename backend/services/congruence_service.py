"""Emotional Congruence Scoring Service.

Computes how well a recommended song aligns with the campaign brief,
based on industry-standard music supervision principles:

1. Emotional Alignment — valence/energy match to campaign mood target
2. Pacing Fit — BPM suitability for the target platform
3. Vocal-Visual Balance — instrumentalness match to video type

References:
- Kantar LINK+ music congruence evaluation
- Goldsmiths/SoundOut research (sound modulates ad response by up to 16.4%)
- Standard music supervision BPM ranges per platform
"""

# Industry-standard BPM ranges per advertising platform.
# Source: sync licensing platform guidelines (Musicbed, Artlist, Epidemic Sound)
PLATFORM_BPM_RANGES = {
    "tiktok": (95, 135),  # Fast-paced, scroll-stopping
    "instagram_reel": (95, 130),  # Similar to TikTok, slightly broader
    "youtube_shorts": (90, 130),  # Moderate-to-fast
    "social_ad": (85, 125),  # Moderate, needs to work in-feed
    "web_video": (80, 120),  # Narrative-paced, YouTube pre-roll
    "tv_ad": (90, 130),  # Cinematic, dynamic
    "in_store": (70, 110),  # Background, ambient
    "podcast": (70, 100),  # Calm, under-voice
}

# Default BPM range when no platform is specified
DEFAULT_BPM_RANGE = (80, 130)

# Vocal preference by campaign energy level
# Music supervision rule: dialogue-heavy or calm content prefers instrumental
ENERGY_INSTRUMENTAL_PREFERENCE = {
    "viral": 0.15,  # Vocals fine — catchy hooks help virality
    "energetic": 0.20,  # Vocals OK — lyrics add energy
    "happy": 0.20,  # Vocals add to feel-good vibe
    "relaxed": 0.55,  # Prefer more instrumental — less intrusive
    "emotional": 0.45,  # Cinematic — instrumental preferred
}


def _safe_float(val, default=0.5):
    """Parse a value to float, clipping to [0, 1]."""
    if val is None:
        return default
    try:
        return max(0.0, min(1.0, float(val)))
    except (ValueError, TypeError):
        return default


def compute_congruence(song, mood_preset, platform=None, campaign_energy=None):
    """Compute emotional congruence score for a song against a campaign context.

    Returns a dict with:
      - emotional_alignment (0-100): How well audio features match the mood target
      - pacing_fit (0-100): How well BPM matches the platform
      - vocal_balance (0-100): How well instrumentalness matches the video type
      - acoustic_balance (0-100): How well acousticness matches the mood preset
      - overall (0-100): Weighted combination
      - grade: 'high', 'moderate', or 'low'
      - badge_emoji: '🟢', '🟡', or '🔴'
    """

    # ── 1. Emotional Alignment ──
    # Compare song's audio features to the mood preset's target values
    # using Euclidean distance (L2 norm) normalized against the maximum possible distance.
    import math
    squared_diffs = []
    feature_pairs = [
        ("danceability", "pref_danceability"),
        ("energy", "pref_energy"),
        ("valence", "pref_valence"),
        ("acousticness", "pref_acousticness"),
        ("instrumentalness", "pref_instrumentalness"),
    ]
    for song_key, preset_key in feature_pairs:
        song_val = _safe_float(song.get(song_key))
        target_val = (
            mood_preset.get(preset_key, 0.5)
            if isinstance(mood_preset, dict)
            else getattr(mood_preset, preset_key, 0.5)
        )
        target_val = _safe_float(target_val)
        squared_diffs.append((song_val - target_val) ** 2)

    if squared_diffs:
        euclidean_dist = math.sqrt(sum(squared_diffs))
        max_dist = math.sqrt(len(feature_pairs))  # Maximum possible distance is sqrt(5) ≈ 2.236
        emotional_alignment = (1.0 - (euclidean_dist / max_dist)) * 100
    else:
        emotional_alignment = 50.0

    # ── 2. Pacing Fit ──
    # Compare song BPM to the platform's expected range
    # (industry-standard BPM ranges from sync licensing guides)
    song_bpm = 0.0
    try:
        song_bpm = float(song.get("tempo") or 0)
    except (ValueError, TypeError):
        song_bpm = 0.0

    bpm_range = PLATFORM_BPM_RANGES.get(platform, DEFAULT_BPM_RANGE)
    bpm_min, bpm_max = bpm_range

    if song_bpm <= 0:
        # Unknown BPM — neutral score
        pacing_fit = 50.0
    elif bpm_min <= song_bpm <= bpm_max:
        # Within ideal range — score based on how centered it is
        range_center = (bpm_min + bpm_max) / 2
        range_half = (bpm_max - bpm_min) / 2
        distance_from_center = abs(song_bpm - range_center) / range_half
        pacing_fit = (1.0 - distance_from_center * 0.3) * 100  # Max 100, min ~70
    else:
        # Outside range — penalty based on distance
        if song_bpm < bpm_min:
            overshoot = (bpm_min - song_bpm) / bpm_min
        else:
            overshoot = (song_bpm - bpm_max) / bpm_max
        pacing_fit = max(10.0, (1.0 - overshoot) * 70)

    # ── 3. Vocal-Visual & Acoustic Balance ──
    # Music supervision rule: dialogue-heavy / calm content prefers instrumental
    # Additionally, mood presets may prefer more acoustic texture (e.g., "Holiday & Warmth")

    song_instrumentalness = _safe_float(song.get("instrumentalness"), 0.0)
    preferred_instrumentalness = ENERGY_INSTRUMENTAL_PREFERENCE.get(
        campaign_energy, 0.30
    )

    song_acousticness = _safe_float(song.get("acousticness"), 0.0)
    preferred_acousticness = (
        mood_preset.get("pref_acousticness", 0.5)
        if isinstance(mood_preset, dict)
        else getattr(mood_preset, "pref_acousticness", 0.5)
    )

    # Closer to preference = higher score
    inst_distance = abs(song_instrumentalness - preferred_instrumentalness)
    vocal_balance = (1.0 - inst_distance) * 100

    acoustic_distance = abs(song_acousticness - preferred_acousticness)
    acoustic_balance = (1.0 - acoustic_distance) * 100

    # ── Combined Score ──
    # Weights reflect industry priorities: emotional alignment matters most, acoustic texture is also important
    overall = (
        emotional_alignment * 0.45
        + pacing_fit * 0.30
        + vocal_balance * 0.15
        + acoustic_balance * 0.10
    )

    # Grade thresholds
    if overall >= 72:
        grade = "high"
        badge_emoji = "🟢"
    elif overall >= 50:
        grade = "moderate"
        badge_emoji = "🟡"
    else:
        grade = "low"
        badge_emoji = "🔴"

    return {
        "emotional_alignment": round(emotional_alignment, 1),
        "pacing_fit": round(pacing_fit, 1),
        "vocal_balance": round(vocal_balance, 1),
        "acoustic_balance": round(acoustic_balance, 1),
        "overall": round(overall, 1),
        "grade": grade,
        "badge_emoji": badge_emoji,
        "platform_bpm_range": f"{bpm_min}-{bpm_max}",
    }
