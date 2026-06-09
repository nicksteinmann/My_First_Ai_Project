# AI Pen & Paper

> Work in progress. This project is actively being developed.

A modular AI-powered text RPG built with Flask, SQLAlchemy, SQLite, and LLM tool calling.

The core rule is:

- Backend = source of truth
- AI = narrator and decision layer

The AI may describe and decide, but persistent game state is changed only through backend tools.

---

## Overview

AI Pen & Paper is a long-term architecture and learning project for a reusable AI-driven tool and rule engine, currently demonstrated through a fantasy RPG.

The current implementation is a fantasy text RPG, but the system is intentionally modular so it can later support other genres such as survival, sci-fi, horror, other rule-based simulations, or non-game AI applications.

The important idea is that this project is not only a game prototype. It is an experiment in building an AI application where an LLM can interact with a persistent backend through validated tools instead of freely inventing or changing state.

In this architecture, the backend acts as the durable memory and rule authority for the AI:

- the database stores what is true
- backend services define what is allowed
- tools expose safe actions to the LLM
- the LLM uses those tools to inspect and modify the world
- the final answer is narrative, but the state changes are deterministic

This makes the project closer to a reusable AI engine than a single scripted game.

---

## Engine Concept

The project explores a pattern that is useful beyond games:

> Give an AI access to structured data, rules, and validated actions, then let it explain, narrate, and generate new content within those boundaries.

The RPG implementation is the most expressive demonstration layer because it allows natural language, player freedom, procedural generation, and persistent consequences to interact at the same time.

For the RPG prototype, that means the AI can narrate a fantasy adventure while the backend controls characters, resources, equipment, inventory, skills, attributes, quests, and persistent campaign state.

The same underlying approach can also be adapted to domains where the AI needs much stricter boundaries and far less creativity, but still has to work against trusted application data and business rules.

Examples:

- an internal assistant that queries company data through controlled tools
- a training simulation where user choices change persistent state
- a rules-based support assistant that can perform validated actions
- a procedural content engine that generates new objects from fixed schemas
- a survival, sci-fi, horror, or sandbox RPG using the same backend principles

The game layer is therefore not the only goal of the project. It is also a way to demonstrate and stress-test the underlying engine in a setting that is harder than many business applications: the AI has more freedom, the user has more freedom, and the system still has to preserve consistency.

That means the RPG acts both as:

- a product prototype
- a technical demonstration of the underlying engine
- a pressure test for persistent AI-state interaction
- an extension that proves the engine can support creative generation, not only strict retrieval and validation

The current system is RAG-inspired, but it is not a classic vector-search RAG system yet. Instead of retrieving documents from embeddings, the backend injects structured state and provides tool calls that let the AI ask for, update, validate, and generate state through application services.

Future versions could add vector search, local document retrieval, or company-internal knowledge bases on top of the same tool-based architecture.

The tool-calling layer also makes the system adaptable to local or private LLMs. In a company setting, the same principle could be used with an internal model so sensitive data stays inside the organization while the AI still interacts with backend systems through validated tools.

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
- services/attributes/
- services/currency/
- services/equipment/
- services/inventory/
- services/leveling/
- services/prompt_builder/
- services/serializers/
- services/skills/
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
- Current map coordinates, region, and subregion for campaign locations
- Exact in-game day and minute, displayed as a coarse fantasy time of day
- Visible quests
- Structured quest state
- Quest rewards and reward claim status

Tools:

- update_location
- move_to_coordinates
- advance_time
- spend_time
- rest
- perform_check
- create_quest
- get_quest_details
- update_quest_objective_progress
- validate_quest_progress
- turn_in_quest
- claim_quest_rewards

### Quest Rules

Structured quest creation, progress, turn-in, and rewards are backend-driven instead of being left to free narration.

Implemented:

- Strict quest objective schemas
- Structured reward data
- Backend reward value ranges based on quest level, danger, and quest type
- Backend normalization and clamping for model-proposed XP and currency rewards
- Explicit quest ids for quest progress, validation, turn-in, and reward claims
- Multiple visible quests without a single global active quest slot
- `bring_item` objectives that validate required inventory items and consume them on turn-in
- `reach_location` objectives that support both stored `location_id` values and generated `location_name` destinations
- Campaign locations can store Avalion map coordinates and inherit regional context from fixed world locations
- `update_location` can resolve known Avalion places, accept explicit coordinates, or inherit the current coordinate for local sublocations
- `move_to_coordinates` handles overland map movement from the current coordinate to a fixed world location or explicit generated-place coordinate
- Map coordinates are normalized to 3 decimal places; with 10 km per coordinate unit this gives roughly 10 meter precision
- Normal coordinate movement is distance-validated against backend map data so small jobs do not silently jump across the continent
- Travel duration estimates are backend-derived from distance, travel mode, route mode, and terrain hints; walking defaults to 5 km/h
- `move_to_coordinates` applies backend-estimated travel minutes to the campaign clock on successful travel
- `advance_time` updates exact backend minutes and rolls the campaign date while the UI shows the fantasy calendar date plus a broad day phase
- Calendar dates are derived from the absolute campaign day using 13 months of 28 days and 7-day weeks, starting on 12. Suncrest 1143
- `spend_time` handles backend-default action durations for searches, meals, shopping, chores, training, crafting, combat, and waiting
- `rest` handles short rests, long rests, and sleeping until morning
- `turn_in_quest` validates objectives, consumes delivery items, and grants normal XP, currency, and item rewards
- Separate quest states for active, completed, turned in, and claimed rewards
- Multiple visible quests in the UI
- Hover details for quest description, objective progress, reward summary, and turn-in info
- Prompt-side quest context filtering so only relevant quest context is injected into conversations

Currently supported objective types:

- reach_location
- talk_to_npc
- return_to_npc
- collect_item
- bring_item
- kill_enemy_type
- kill_npc

Reward authority:

- `quest_level`, `quest_type`, and `danger_level` define backend XP and currency ranges.
- Model-provided `rewards_json` is treated as a proposal and is clamped into the backend range.
- Model-provided `reward_rules_json` can carry optional negotiation/context hints, but it cannot widen backend reward ranges.
- Structured quest XP, currency, and item rewards must be paid through `turn_in_quest` or `claim_quest_rewards`, not through direct reward tools.

Current limitations:

- `kill_enemy_type` and `kill_npc` are structurally prepared, but still need full combat/NPC-state integration
- Generated NPCs still need a real NPC registry before generated turn-in targets can reliably use stable NPC ids
- Quest reward constants and multipliers are implemented, but still need balancing from playtests
- Service rewards are structured and claimable, but their later redemption flow still depends on future NPC/service systems

### Story Persistence

- Player and assistant messages are stored per campaign
- Recent story history is injected into each LLM turn
- Campaign continuity is preserved across messages

### Inventory System

Character-based container inventory stored in `inventory_json`.

Features:

- Multiple containers per character
- Inventory capacity comes from carried containers and equipped gear
- The fallback `base_inventory` container has no real storage capacity
- Free `main_hand` and `off_hand` slots create temporary hand containers with volume `1.0`
- Hand containers can only store items with `hand_usage: none`
- One-handed and two-handed items must use equipment hand slots instead of hand containers
- Nearby scene containers can expose items that are in reach but not carried
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
- Torso and leg clothing can provide small pocket containers when their item data includes a container profile.
- Starter characters begin with simple clothing, shoes, a belt, a small belt pouch, and a wooden club equipped.
- Starter characters now begin with their backpack equipped.
- Items cannot be unequipped while their equipment-created container still contains items.

Tools:

- get_equipment
- equip_item
- unequip_item
- get_attack_profile
- get_defense_profile
- preview_attack_outcome

Not yet implemented:

- Advanced belt attachment rules beyond the current two-slot MVP
- More detailed belt pouch size classes
- Persistent equipment-derived effective stat overlays outside combat preview flows
- More detailed clothing types such as dresses occupying multiple clothing slots

Combat-oriented equipment foundation now implemented:

- Weapon families with backend fallback for unknown/AI-generated weapons (`improvised`, `unarmed`)
- Family-specific base damage and scaling profiles for melee, ranged, and magic archetypes
- Item-level aware weapon progression
- Non-linear combat scaling based on level, weapon level, skill level, and weighted attributes
- Defense profile calculation with simultaneous dodge and block scoring
- Armor-class behavior (`light`, `medium`, `heavy`) influencing dodge vs block tendencies
- Clear-defense zero-damage rules in outcome preview:
  - clear dodge win => 0 damage
  - clear block win => 0 damage
- Attack outcome preview for attacker vs defender probability checks, including strong level-gap behavior

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
- Resource growth now uses non-linear scaling curves (resource-specific exponents) anchored to previous max values, with class multipliers applied.
- Current HP, Mana, and Energy also increase by the gained maximum amount when the character is alive.
- Character level also derives a small Renown/Ruf tier for social context.
- Renown can influence whether NPCs recognize the character or know rumors about them.
- Renown does not grant automatic rewards, discounts, authority, or quest completion.

Tool:

- add_xp

Current class scaling:

- Knight: stronger HP growth, lower Mana growth
- Mage: stronger Mana growth, lower HP growth
- Rogue: stronger Energy growth
- Priest: stronger Mana growth
- Ranger: stronger Energy growth

Current Renown/Ruf tiers:

- Level 1-4: Unknown
- Level 5-9: Familiar Face
- Level 10-19: Local Name
- Level 20-34: Regional Reputation
- Level 35-49: Well Known
- Level 50-74: Famous Hero
- Level 75-99: Legendary Figure
- Level 100: Living Legend

Note: skill XP, skill levels, skill points, and level-up choices are future work.

### Attribute Progression

Backend-controlled attribute progression attached to character level-ups.

Attributes:

- strength
- dexterity
- constitution
- intelligence
- perception
- charisma

Rules:

- Attribute values are separate from future skill levels.
- Attribute XP uses the same progression curve as character level XP: `100 * level^1.55`.
- Attribute XP is stored as total lifetime XP per attribute in `attribute_xp_json`.
- Character level-ups automatically grant attribute XP in the backend.
- Attribute XP can also be granted directly through the `add_attribute_xp` backend tool.
- The AI does not need an extra tool call for attribute progression after `add_xp`.
- Batch attribute XP grants are supported so one tool call can update multiple attributes.
- The awarded attribute XP is based on the character level interval, not the current attribute level.
- A class can grant at most 25% of the matching level interval to its strongest attribute.
- Existing local SQLite databases are upgraded with a small compatibility column check until real migrations exist.

Current class focus:

- Knight: strength and constitution
- Mage: intelligence
- Rogue: dexterity and perception
- Priest: charisma and intelligence
- Ranger: perception and dexterity

Note: backend time costs for lessons and self-training are prepared through `spend_time`, but direct training XP rules, equipment modifiers, and status-effect modifiers are future work.

Tool:

- add_attribute_xp

### Skill Progression

Backend-controlled learned skills for concrete abilities.

Core skills:

- Swordsmanship
- Axes & Hammers
- Polearms
- Archery
- Dodging
- Blocking
- Stealth
- Lockpicking
- Pickpocketing
- Trap Disarming
- Climbing
- Athletics
- Arcane Lore
- Herbalism
- Medicine
- Survival
- Persuasion
- Deception
- Intimidation
- Insight

Rules:

- Level 0 represents an untrained skill.
- Unlocking a skill from level 0 to level 1 costs 20 XP.
- After level 1, skill XP uses the normal progression curve: `100 * level^1.55`.
- Skills are separate from attributes.
- Attributes will later act as modifiers for checks, but they do not directly replace skill training.
- Core skills are seeded at app startup.
- Custom skills can be created when an activity is repeatable, learnable, broad enough, and no core skill fits.
- Custom skills are stored in `skill_definitions` with `is_custom=True`.
- Custom skill metadata now supports:
  - aliases
  - secondary attributes
  - allowed check domains
- Characters learn skills through `character_skills`.
- Custom skill creation is limited per character to prevent uncontrolled growth.
- Alias matching prevents near-duplicate skill creation when the same concept is requested under a different name.
- `perform_check` enforces domain compatibility for registered skills and can reject invalid skill/domain combinations.
- Skill chips use emoji for core skills and fall back to short codes for custom skills.

Tools:

- get_skills
- add_skill_xp
- create_custom_skill

### Status Effects

Character status effects are now backend-driven gameplay state, not only display data.

Implemented:

- name
- effect type
- remaining duration
- source text
- modifier bundles for common effects such as:
  - poisoned
  - bleeding
  - burning
  - stunned
  - blessed
  - fatigued
  - slowed
  - shielded
  - frozen
- backend ticking during:
  - `advance_time`
  - `spend_time`
  - `rest`
  - combat turns
- resource loss over time for effects such as poison
- check modifiers through `perform_check`
- attack / dodge / block modifiers through combat and equipment profile helpers
- temporary action lockouts for effects such as `stunned`
- status effects remain visible on Home, My Characters, and Community pages

Tools:

- get_status_effects
- apply_status_effect
- remove_status_effect

Current limitations:

- effect stacking and refresh rules are still MVP-level
- resistance, cleansing, immunity, and more advanced effect interactions are still future work
- enemy/item/spell content still needs broader use of the new effect system

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
- Story history is kept as context, while prompt rules prevent blind re-execution of past events
- Each game request gets a backend turn id that is included in tool results
- Quest-relevant context is injected selectively instead of always dumping every quest into every scene
- Final narration is checked for backend-controlled state claims such as quest completion, rewards, XP, currency, or inventory gains
- If the model claims those outcomes without matching successful tool results, the draft is rejected and the model must call tools or restate the scene without false state changes
- Meta placeholders such as "already provided a reply" are also rejected so they do not reach the player as empty turns
- Direct reward tools such as `add_currency` and `add_xp` are blocked in paid NPC job context; structured work must be created and paid through quest tools
- Quest creation fills missing concrete currency rewards from backend reward rules so turn-in validation has a real payout value

This prevents the technical fallback text from being shown to the player after successful tool execution.
It also reduces accidental repeated state changes from old narration context.
It keeps narration and backend state closer together when a model forgets a required tool call or ignores a failed tool result.

### Music / UX

Implemented:

- Optional looping background music on the game page
- Speaker mute/unmute control
- Hover/expand volume slider interaction
- Lower default playback volume for less intrusive long sessions

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
- Attributes
- Skills
- Adventure chat
- Provider selection
- Campaign state
- Multi-quest list with hover details
- Equipment slots
- Character XP progress
- Inventory containers
- Currency
- Story history

---

## Current State

Working:

- AI RPG engine prototype with a fantasy game as the current demonstration layer
- Modular Flask architecture
- Persistent users and characters
- Persistent campaigns
- Story persistence
- Tool-controlled adventure state
- Structured quest creation, turn-in, and reward claim flow
- Container inventory
- Currency system
- Equipment MVP
- Weapon attack profile calculation (family, scaling, item level, skill contribution, non-linear factors)
- Defense profile calculation (dodge/block scoring, armor class weighting, armor-related bonuses)
- Outcome probability preview for attacker vs defender (full/partial/zero-damage distribution)
- Resource tools for HP / Mana / Energy
- Character status sync when HP reaches 0
- Status effect display and tools
- Character level progression and XP tool
- Automatic attribute XP from character level-ups
- Skill progression and skill XP tools
- Structured Avalion world map data with fixed regions, cities, coordinates, and route distances
- MVP rectangular region and subregion bounds for coordinate-based location resolution
- World overview page backed by `data/world.json`
- Active campaign locations can carry coordinate, region, subregion, and fixed-world-location context
- Coordinate travel tool that validates destination distance before updating the active campaign location
- Backend travel-time estimation for coordinate and fixed-route travel, applied to the in-game clock on successful travel
- Backend action-time tools for meaningful non-travel actions, rests, and sleeping until morning
- Multi-system tool pipeline
- UI state refresh after game turns
- Rule-grounded item and state interaction through backend tools

Known limitations:

- No vector-based RAG or external knowledge retrieval yet
- No full round-based combat action resolver yet (current state provides attack/defense profiles and outcome preview, not full battle turns)
- No full custom-skill balancing layer yet (metadata and domain safety exist, but balancing policies are still being tuned)
- No level-up choice or skill point spending yet
- No full enemy combat state machine yet (enemy AI actions, advanced encounter scripting, and richer round behaviors still need work)
- No NPC system yet
- No merchant / trading system yet
- No full quest combat resolution yet for `kill_enemy_type` / `kill_npc`
- Region/subregion bounds are MVP rectangles; organic border polygons and generated-place persistence rules still need deeper map integration
- Non-quest loot and pickup/equip changes still need stronger tool-routing enforcement
- Travel time is applied by backend tools, but broader schedule systems such as shop refreshes and NPC routines are still future work
- Reward economy values are backend-controlled, but not final-balanced yet
- Tool calling works, but retry and failure handling are still MVP-level

---

## MVP Roadmap

High priority:

- Equipment stat modifiers for always-on effective character overlays (outside preview tools)
- Direct attribute training rules
- Starting gear auto-equip
- Advanced belt and pouch attachment rules
- Full combat turn resolution on top of attack/defense profiles
- Skill checks with real gameplay impact
- Level-up choices and skill point spending

Mid-term:

- Merchant and trading tools
- NPC interaction system
- Combat system
- Organic region/subregion polygons and generated-place persistence
- Shop opening hours, trainer schedules, rest recovery, and status-effect ticking tied to campaign time
- Better tool retry and failure handling

Long-term:

- Reusable AI RPG framework
- Genre templates
- RAG or retrieval layer for structured world and knowledge data
- Local/private LLM compatibility for sensitive data use cases
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

### 6. Run backend regression tests

The current test suite uses Python's built-in `unittest` runner, so no extra
test dependency is required.

```bash
python -m unittest discover -s tests -v
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
- LLM tool calling as a controlled interface to application state
- RAG-inspired grounding through structured backend data
- Persistent game state
- LLM integration in real applications
- Modular system design
- Tool-based state control
- Scalable AI game systems
- Rule-based procedural content generation
- Building an AI system that can create narrative freedom without owning the source of truth

It serves as both a school and learning project and a technical showcase.

The goal is to demonstrate more than a playable text adventure. The project shows how an AI can be connected to a backend in a way that keeps data, rules, and state changes deterministic while still allowing flexible natural-language interaction and creative generation.

---

## License

Copyright (c) 2026 Nick Steinmann

All rights reserved.

This project is published for educational and showcase purposes only.

The code may not be used, copied, modified, or distributed for commercial purposes without explicit permission from the author.
