# AI Pen & Paper

> ⚠️ Work in Progress – this project is actively being developed.

A text-based AI-powered roleplaying game (RPG) prototype built with Flask, SQLAlchemy, and modern LLM APIs.

## 📌 Overview

This project is a personal showcase to demonstrate practical skills in:

- Backend development with Flask
- Database design using SQLAlchemy (SQLite)
- API integration (OpenAI / DeepSeek)
- Basic frontend interaction (HTML, JavaScript)
- System design for AI-driven applications

The goal is to build a dynamic, text-based Pen & Paper experience where an AI acts as the game master.

---

## 🎯 Project Goal

The long-term vision is to create a system where:

- Players can create and manage characters
- Game states are stored persistently in a database
- The AI generates dynamic story content based on:
  - player actions
  - character stats
  - world data
- Multiple AI models can be used interchangeably

---

## ⚙️ Technologies Used

- Python 3
- Flask
- SQLAlchemy (SQLite)
- OpenAI API
- DeepSeek API (OpenAI-compatible)
- HTML / JavaScript (basic frontend)

---

## 🤖 AI Integration

The application supports multiple LLM providers:

- OpenAI (e.g. GPT models)
- DeepSeek (OpenAI-compatible API)

A provider can be selected dynamically in the UI.

---

## 🚀 Getting Started

### 1. Clone the repository

git clone https://github.com/nicksteinmann/My_First_Ai_Project.git  
cd AI_Pen_And_Paper

---

### 2. Install dependencies

pip install -r requirements.txt

---

### 3. Create a `.env` file

Create a `.env` file in the project root:

OPENAI_API_KEY=your_openai_key  
DEEPSEEK_API_KEY=your_deepseek_key  

OPENAI_MODEL=gpt-4.1-mini  
DEEPSEEK_MODEL=deepseek-chat  

---

### 4. Initialize the database

Run the application once to create the database:

python app.py

Then (optional):

python seed_data.py

---

### 5. Start the application

python app.py

Open in browser:

http://127.0.0.1:5000

---

## 🧱 Current State

This is an early prototype.

Currently implemented:

- Flask backend structure
- Database models (SQLAlchemy)
- Basic frontend interface
- AI integration via API
- Provider switching (OpenAI / DeepSeek)
- Minimal seed data

---

## 🔜 Planned Features

- Character creation system
- Persistent game state
- Inventory and equipment system
- Combat and skill mechanics
- World and NPC system
- RAG-based world knowledge integration

---

## 🧠 Motivation

This project is built to explore:

- How to structure AI-driven applications
- How to combine databases with LLMs
- How to build scalable backend systems
- How to design interactive text-based experiences

---

## 📄 License

This project is for educational and demonstration purposes.