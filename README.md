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

### 6. Audio and Preview Handling
The application contains logic for handling and serving audio previews, including fallback audio generation and audio file management for campaign-related content.

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

