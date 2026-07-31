

def get_generation_vector(gen_key):
    """
    Returns an ideal 5-dimensional Spotify audio vector for a given generation.
    Vector format: [danceability, energy, valence, acousticness, instrumentalness]
    """
    mapping = {
        "gen_z": [0.80, 0.75, 0.60, 0.10, 0.05, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "millennials": [0.65, 0.70, 0.65, 0.20, 0.10, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "boomers": [0.40, 0.50, 0.50, 0.60, 0.20, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "silent_generation": [
            0.30,
            0.30,
            0.50,
            0.80,
            0.30,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
        ],
    }
    return mapping.get(gen_key, [0.5] * 11)


def get_industry_vector(ind_key):
    """
    Returns an ideal 5-dimensional Spotify audio vector for a given industry.
    Vector format: [danceability, energy, valence, acousticness, instrumentalness]
    """
    mapping = {
        "consumer_goods": [
            0.60,
            0.75,
            0.60,
            0.25,
            0.10,
            0.70,
            0.10,
            0.25,
            0.60,
            0.50,
            0.50,
        ],
        "fashion_lifestyle": [
            0.60,
            0.40,
            0.50,
            0.50,
            0.40,
            0.30,
            0.05,
            0.10,
            0.30,
            0.50,
            0.50,
        ],
        "tech_saas": [0.55, 0.75, 0.45, 0.10, 0.65, 0.70, 0.10, 0.15, 0.65, 0.50, 0.50],
        "retail": [0.85, 0.85, 0.80, 0.10, 0.05, 0.80, 0.15, 0.20, 0.70, 0.40, 0.50],
        "hospitality": [
            0.50,
            0.35,
            0.60,
            0.75,
            0.45,
            0.25,
            0.05,
            0.15,
            0.30,
            0.50,
            0.50,
        ],
        "fitness_wellness": [
            0.90,
            0.95,
            0.70,
            0.05,
            0.05,
            0.90,
            0.20,
            0.30,
            0.85,
            0.40,
            0.50,
        ],
        "entertainment": [
            0.75,
            0.85,
            0.60,
            0.10,
            0.40,
            0.70,
            0.20,
            0.25,
            0.70,
            0.50,
            0.50,
        ],
        "education": [0.40, 0.40, 0.60, 0.70, 0.30, 0.30, 0.10, 0.15, 0.35, 0.50, 0.50],
        "finance": [0.30, 0.30, 0.50, 0.80, 0.80, 0.20, 0.05, 0.10, 0.25, 0.60, 0.50],
        "other": [0.50, 0.50, 0.50, 0.50, 0.20, 0.50, 0.10, 0.20, 0.50, 0.50, 0.50],
    }
    return mapping.get(ind_key, [0.5] * 11)


def get_campaign_vector(camp_key):
    """
    Returns an ideal 5-dimensional Spotify audio vector for a given campaign type.
    Vector format: [danceability, energy, valence, acousticness, instrumentalness]
    """
    mapping = {
        "summer": [0.80, 0.80, 0.90, 0.10, 0.00, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "holiday": [0.50, 0.60, 0.80, 0.40, 0.10, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "launch": [0.70, 0.90, 0.70, 0.10, 0.20, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "corporate": [0.40, 0.40, 0.50, 0.60, 0.40, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        "social": [0.80, 0.70, 0.70, 0.20, 0.00, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    }
    return mapping.get(camp_key, [0.5] * 11)
