# AI Pen & Paper

> ⚠️ Work in Progress – this project is actively being developed.

A text-based AI-powered roleplaying game (RPG) prototype built with Flask, SQLAlchemy, and modern LLM APIs.

---

## 📌 Overview

This project is a personal showcase to demonstrate practical skills in:

- Backend development with Flask
- Database design using SQLAlchemy (SQLite)
- API integration (OpenAI / DeepSeek)
- State management for AI-driven systems
- Building interactive AI applications

The goal is to create a dynamic Pen & Paper experience where an AI acts as the game master.

---

## 🎯 Vision

The long-term goal is to build a system where:

- Players can create and manage characters
- Characters have persistent stats, inventory, and progression
- A full campaign state (location, time, quests) is stored
- The AI generates consistent story progression based on:
  - player actions
  - character stats
  - world state
- Multiple AI providers can be used interchangeably

---

## ⚙️ Technologies Used

- Python 3
- Flask
- Flask-SQLAlchemy
- SQLite
- OpenAI API
- DeepSeek API (OpenAI-compatible)
- HTML / CSS / JavaScript
- python-dotenv

---

## 🤖 AI Integration

The project currently supports multiple LLM providers:

- OpenAI (GPT models)
- DeepSeek (OpenAI-compatible)

The provider can be selected dynamically in the UI.

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/nicksteinmann/My_First_Ai_Project.git
cd AI_Pen_And_Paper
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create a `.env` file

Create a `.env` file in the project root with the following content:

```env
OPENAI_API_KEY=your_openai_key
DEEPSEEK_API_KEY=your_deepseek_key

OPENAI_MODEL=gpt-4.1-mini
DEEPSEEK_MODEL=deepseek-chat
```

### 4. Initialize and start the app

```bash
python app.py
```

Optional:

```bash
python seed_data.py
```

Open in browser:

```text
http://127.0.0.1:5000
```

---

## 🧱 Current Features (Implemented)

### 🔐 Authentication
- User registration
- Login / logout
- Password hashing using Werkzeug
- Unique username and email validation

### 👤 Character System
- Character creation
- Race presets
- Class presets
- Character deletion
- Character switching
- Active character selection

### 📊 Character Stats
- Strength
- Dexterity
- Intelligence
- Perception
- HP
- Mana
- Energy

Displayed consistently across:
- Home
- My Characters
- Community

### 🎒 Inventory & Equipment
- Equipment system
- Inventory system
- Starter gear stored in database
- Visible in all major views

### 🌍 Campaign State
Each character has:

- Location
- Time of day
- Active quest
- Equipment
- Inventory

Fully database-driven (no more mock data).

### 🧑‍🤝‍🧑 Community Page
- Real users
- Real characters
- Real stats
- Real inventory & equipment
- Real campaign state

### 🤖 AI Adventure Chat
AI receives full context:

- Character identity
- Stats
- Location
- Time
- Quest
- Equipment
- Inventory

---

## 🚧 Current Limitations

- No persistent story memory yet
- AI resets context between messages
- No quest completion system
- No quest progression tracking
- No combat system
- No NPC system
- No economy system
- No world persistence

---

## 🔜 Next Steps

### High Priority
- Persistent story memory
- Continuous scene progression
- Quest progression system

### Mid-Term
- Quest objectives & completion
- NPC interactions
- Merchant system
- Equipment usage

### Long-Term
- Full campaign engine
- AI memory optimization
- Dynamic world state
- Multiplayer concepts

---

## 🧠 Motivation

This project explores:

- AI + backend architecture
- Persistent game state
- LLM integration in real systems
- Scalable AI application design

It serves as both a learning project and a technical showcase.

---

## 📄 License

This project is for educational and demonstration purposes.