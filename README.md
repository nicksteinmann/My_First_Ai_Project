# AI Pen & Paper

> Work in progress. This project is actively being developed.

A modular AI-powered text RPG built with Flask, SQLAlchemy, SQLite, and LLM tool calling.

The core rule is:

- Backend = source of truth
- AI = narrator and decision layer

The AI may describe and decide, but persistent game state is changed only through backend tools.

---

## Overview

AI Pen & Paper is a long-term architecture and learning project for a reusable AI-driven RPG engine.

The current implementation is a fantasy text RPG, but the system is intentionally modular so it can later support other genres such as survival, sci-fi, or horror.

---

## Tech Stack

- Python 3
- Flask
- Flask-SQLAlchemy
- SQLAlchemy
- SQLite
- OpenAI-compatible chat completions
- OpenAI API
- DeepSeek API
- HTML / CSS / JavaScript
- python-dotenv
- Werkzeug password hashing

---

## Core Design Philosophy

### AI responsibilities

- Narration
- Interpreting player intent
- Deciding when a tool should be used
- Continuing the scene after tool results

### Backend responsibilities

- Persistent state
- Validation
- Character data
- Campaign state
- Inventory logic
- Equipment logic
- Currency logic
- Tool execution

The AI must not directly modify game state. Every state change must go through validated backend tools.

---

## Architecture

### Entrypoint

- app.py

`app.py` creates the Flask app, configures the database, defines small app-level helpers, and registers route modules.

### Routes

- routes/auth_routes.py
- routes/page_routes.py
- routes/character_routes.py
- routes/game_routes.py

### Services

- services/adventure_state/
- services/currency/
- services/equipment/
- services/inventory/
- services/leveling/
- services/prompt_builder/
- services/serializers/
- services/story/
- services/tools/

### Data

- data/character_presets.py
- data/enemies.json
- data/items.json
- data/skills.json
- data/world.json

---

## Implemented Systems

### Authentication

- User registration
- Login / logout
- Password hashing
- Session handling

### Character System

- Persistent characters per user
- Race and class presets
- Attribute generation
- Resource rows for HP, Mana, Energy, and Stamina
- Character switching
- Character deletion
- Active character selection

### Campaign / Adventure State

Each active campaign tracks:

- Current location
- Time of day
- Active quest
- Quest description

Tools:

- update_location
- advance_time
- set_active_quest
- complete_active_quest

### Story Persistence

- Player and assistant messages are stored per campaign
- Recent story history is injected into each LLM turn
- Campaign continuity is preserved across messages

### Inventory System

Character-based container inventory stored in `inventory_json`.

Features:

- Multiple containers per character
- Container volume limits
- Max item size per container
- Item volume and weight
- Stackable items
- Hand usage metadata
- Backend validation

Tools:

- get_inventory
- add_inventory_item
- remove_inventory_item

### Equipment System

MVP equipment system stored alongside inventory data in `inventory_json`.

Implemented slots:

- head
- torso_clothing
- torso_armor
- legs_clothing
- legs_armor
- feet
- gloves
- belt
- belt_slot_1
- belt_slot_2
- backpack
- cloak
- ring_left
- ring_right
- main_hand
- off_hand

Rules:

- One-handed items use either `main_hand` or `off_hand`.
- Two-handed items occupy both hands.
- An equipped belt unlocks two attachment slots: `belt_slot_1` and `belt_slot_2`.
- Belt attachment slots can hold weapons of any item size.
- Belt attachment slots can hold pouch/container items only when their item size is `tiny` or `small`.
- Shields can be equipped in the `backpack` slot when no backpack or container item is equipped there.
- Equipped container items can add inventory containers when they define a container profile.
- Items cannot be unequipped while their equipment-created container still contains items.

Tools:

- get_equipment
- equip_item
- unequip_item

Not yet implemented:

- Advanced belt attachment rules beyond the current two-slot MVP
- More detailed belt pouch size classes
- Stat modifiers from equipment
- Starting gear auto-equipped on character creation

### Resource System

Backend-controlled character resources stored in `character_resources`.

Resources:

- hp
- mana
- energy

Rules:

- Resource values cannot drop below 0.
- Resource restoration is capped at the resource maximum.
- HP reaching 0 automatically sets the character status to `dead`.
- HP returning above 0 sets the character status back to `alive`.
- Resource maximum values can be updated for equipment or level-scaling systems.

Tools:

- get_resources
- add_resource
- remove_resource
- set_resource

Note: equipment stat modifiers are still future work.

### Character Level Progression

Backend-controlled character XP and level progression.

Rules:

- Characters start at level 1 with 0 XP.
- Character level is capped at 100.
- Character XP only increases.
- Stored XP is total lifetime character XP, not only XP toward the current level.
- The XP bar is calculated from total XP, current level threshold, and next level threshold.
- XP needed per next level uses a progressive curve: `100 * level^1.55`.
- Level-ups can happen multiple times from one XP grant.
- Level-ups increase HP, Mana, and Energy maximum values.
- Class multipliers control how much each resource grows per level.
- Current HP, Mana, and Energy also increase by the gained maximum amount when the character is alive.

Tool:

- add_xp

Current class scaling:

- Knight: stronger HP growth, lower Mana growth
- Mage: stronger Mana growth, lower HP growth
- Rogue: stronger Energy growth
- Priest: stronger Mana growth
- Ranger: stronger Energy growth

Note: skill XP, skill levels, skill points, and level-up choices are future work.

### Status Effects

Character status effect tables already exist and are now serialized into the UI.

Displayed fields:

- name
- effect type
- remaining duration
- source text

Current scope:

- Status effects are visible on Home, My Characters, and Community pages.

Tools:

- get_status_effects
- apply_status_effect
- remove_status_effect

Note: automatic duration ticking and complex modifier application are future work.

### Currency System

Currencies:

- gold
- silver
- copper

Conversion rule:

- 1 gold = 10 silver
- 1 silver = 50 copper

Stored in `currency_json`.

Tools:

- get_currency
- add_currency
- remove_currency

Note: automatic currency conversion and change-making are still future work.

### AI Tool Calling

The game turn pipeline supports:

- Tool definitions from multiple systems
- OpenAI-style tool calls
- DeepSeek / DSML fallback parsing
- Tool name normalization for some legacy model outputs
- Multi-tool execution in one turn
- A bounded tool loop
- A final no-tool narration call if the model keeps requesting tools until the loop limit is reached
- Story history is marked as already resolved before it is sent back to the LLM
- Each game request gets a backend turn id that is included in tool results

This prevents the technical fallback text from being shown to the player after successful tool execution.
It also reduces accidental repeated state changes from old narration context.

---

## UI

Pages:

- Home
- My Characters
- World
- Community
- Support

Current displays:

- Active character
- Stats
- Skills / attributes
- Adventure chat
- Provider selection
- Campaign state
- Equipment slots
- Character XP progress
- Inventory containers
- Currency
- Story history

---

## Current State

Working:

- Modular Flask architecture
- Persistent users and characters
- Persistent campaigns
- Story persistence
- Tool-controlled adventure state
- Container inventory
- Currency system
- Equipment MVP
- Resource tools for HP / Mana / Energy
- Character status sync when HP reaches 0
- Status effect display and tools
- Character level progression and XP tool
- Multi-system tool pipeline
- UI state refresh after game turns

Known limitations:

- No stat modifiers from equipment yet
- No skill XP / skill level progression yet
- No level-up choice or skill point spending yet
- No automatic status-effect duration ticking yet
- No status-effect stat/resource modifiers yet
- No real skill check system yet
- No combat system yet
- No NPC system yet
- No merchant / trading system yet
- No structured world knowledge system yet
- Tool calling works, but retry and failure handling are still MVP-level

---

## MVP Roadmap

High priority:

- Equipment stat modifiers
- Skill XP and skill level progression
- Status-effect duration ticking and modifier logic
- Starting gear auto-equip
- Advanced belt and pouch attachment rules
- Skill checks with real gameplay impact
- Level-up choices and skill point spending

Mid-term:

- Merchant and trading tools
- NPC interaction system
- Combat system
- Better tool retry and failure handling

Long-term:

- Reusable AI RPG framework
- Genre templates
- Better AI consistency
- World simulation and events

---

## Getting Started

### 1. Clone

```bash
git clone https://github.com/nicksteinmann/My_First_Ai_Project.git
cd AI_Pen_And_Paper
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create a `.env` file

Create `.env` in the project root:

```env
OPENAI_API_KEY=your_openai_key
DEEPSEEK_API_KEY=your_deepseek_key

OPENAI_MODEL=gpt-4.1-mini
DEEPSEEK_MODEL=deepseek-chat
```

### 5. Start the app

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Optional seed script:

```bash
python seed_data.py
```

---

## Environment Notes

Required environment variables:

- OPENAI_API_KEY
- DEEPSEEK_API_KEY
- OPENAI_MODEL
- DEEPSEEK_MODEL

The default provider in the game UI is DeepSeek when available.

---

## Git Workflow

Existing branch pattern:

- feature/name
- refactor/name

Existing commit style:

- feat: short description
- fix: short description
- refactor: short description

---

## Motivation

This project explores:

- AI and backend architecture
- Persistent game state
- LLM integration in real applications
- Modular system design
- Tool-based state control
- Scalable AI game systems

It serves as both a learning project and a technical showcase.

---

## License

Copyright (c) 2026 Nick Steinmann

All rights reserved.

This project is published for educational and showcase purposes only.

The code may not be used, copied, modified, or distributed for commercial purposes without explicit permission from the author.
