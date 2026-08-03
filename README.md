## Project Overview

USense aims to provide marketing teams with a unified workspace for music-led campaign planning by blending several ideas:

- personalized recommendations based on user preferences and audio characteristics,
- social features for collaboration and messaging between team members,
- campaign-style rooms for planning and reviewing music for marketing initiatives,
- a lightweight dashboard experience for browsing, saving, and discussing music.

The app is especially useful for scenarios where music is not only consumed, but also selected and curated to fit campaign goals, audience moods, and brand tone.

---

## Key Features

### 1. Personalized Music Recommendations
The app uses music/audio feature data to generate recommendations based on user taste and target attributes such as:

- danceability,
- energy,
- valence,
- acousticness,
- instrumentalness.

Recommendation logic is organized around hybrid recommendation services and shared recommender utilities.

### 2. Mood and Creative Brief Translation
The backend includes a mood translation service that converts short human descriptions into recommendation preferences. For example, phrases like “warm”, “dark”, or “energetic” can influence the music target profile used by the recommender.

This is particularly relevant for campaign creation and creative brief interpretation.

### 3. Favorites and Saved Recommendations
Users can save recommended songs to a personal favorites list so that they can revisit and manage songs they liked.

### 4. Social Features
The app supports basic social interactions such as:

- sending collaborator requests,
- accepting or declining requests,
- messaging collaborators,
- viewing a social dashboard.

These features are integrated into the main user experience and help connect users around shared music interests.

### 5. Campaign Rooms
One of the most distinctive aspects of the project is its campaign-room system. Marketing teams can create dedicated rooms for organizing music around specific brand, audience, or creative themes.

Campaign rooms support:

- mood presets,
- room creation,
- room events,
- reactions and approvals,
- track status transitions,
- recommendation suggestions tied to the room’s brief.

This makes the platform useful for content teams, campaign planners, and creative discussions around music selection.

## Analytic features included in the project

#### 1. Russell's index and music positioning
The application includes work around Russell's emotional model, which helps position songs along dimensions such as valence and arousal. In practice, this supports a more structured view of how a track may fit a brand mood, campaign emotion, or audience response.

#### 2. Logistic regression-based modeling
A logistic regression component is used as part of the recommendation and analysis pipeline. This provides a simple but interpretable baseline for modeling preference-related outcomes and helps connect musical features to likely user response patterns.

#### 3. k-NN (k-Nearest Neighbors)
The project includes a k-nearest-neighbors approach for recommendation. This method looks for songs with similar feature profiles to the ones a user or campaign brief already favors. It is especially useful for finding tracks with similar sonic characteristics and for building a similarity-driven recommendation experience.

#### 4. k-Means clustering
K-means clustering is used as part of the analytical flow to group songs by shared musical characteristics. This helps identify latent patterns in the music catalog and can support segmentation, exploratory analysis, and campaign fit evaluation.

#### 5. Popularity-based analysis
The project also includes popularity-based logic and related work on popularity weighting. This helps balance highly popular tracks with niche or less obvious recommendations, allowing the system to support both mainstream and more targeted campaign needs.

#### 6. Gaussian noise application
Gaussian noise is applied in the experimental or modeling layer to simulate variability and robustness in the recommendation pipeline. This can be useful for testing sensitivity, exploring uncertainty, and avoiding overly rigid recommendations.

#### 7. Mnemonic and cue sheet support
The system includes mnemonic-style cueing and cue-sheet concepts to help translate emotional or campaign-oriented ideas into recommendation targets. This is especially relevant for marketing teams that want to connect abstract creative briefs to concrete musical attributes.

#### 8. A/B testing support
A/B testing functionality is built into the campaign-room experience. This allows the system to compare different recommendation strategies, moods, or music selections in a structured way so teams can evaluate which direction performs better for a campaign.

#### 9. Emotional congruence
A major design principle of the system is emotional congruence: aligning the recommended music with the emotional tone of a campaign, audience, or brand message. This is one of the most important concepts for marketing-oriented music selection because it helps ensure that the soundtrack supports the intended emotional effect rather than merely matching superficial genre preferences.

---
## Technology Stack

### Backend
- Python
- Flask
- Flask-SQLAlchemy
- Flask-SocketIO
- Flask-CORS
- SQLite

### Data / Recommendation Layer
- pandas
- scikit-learn
- numpy

### Frontend
- Jinja2 templates
- HTML/CSS/JavaScript assets
- Flask-rendered pages and dynamic UI components

---

## Usage Flow

### 1. Register or Sign In
Open the app in a browser and create an account or log in with an existing one.

### 2. Explore Recommendations
After logging in, the dashboard allows you to browse recommendations and interact with the app’s recommendation system.

### 3. Save Favorites
You can save songs you like to your favorites list for later access.

### 4. Collaborate with Others
Send collaborator invitations and communicate with others through the social features.

### 5. Create a Campaign Room
Create a room for a campaign, mood, or creative theme and use the recommendation system to suggest music that fits the brief.

---

## Database

The app uses SQLite through Flask-SQLAlchemy. The database is initialized from the backend models and is stored in the project environment as a local SQLite database file.

The data model includes entities such as:

- users,
- user preferences,
- favorites,
- messages,
- collaborator requests,
- campaign rooms,
- room events,
- room reactions,
- song status records,
- A/B test-related tables.

---

## Recommendation Approach

Although the project contains a relatively lightweight implementation, it is structured around the idea of combining multiple recommendation signals:

- audio feature matching,
- genre preferences,
- user interaction signals,
- collaborative or social context,
- campaign-specific targets.

The code is organized into separate recommender services, making it easier to extend and improve over time.

---

