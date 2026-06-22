"""Database models for the AI Pen & Paper prototype.

The schema is intentionally broad: some tables already support future systems
such as merchants, enemies, skill checks, and world templates even when the
current MVP mainly uses character state, inventory, equipment, resources,
progression, story history, and campaign state.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class TimestampMixin:
    """Shared created/updated timestamps for mutable persisted records."""

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Account and character ownership
# ---------------------------------------------------------------------------


class User(db.Model, TimestampMixin):
    """Login account that owns characters and profile data."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)

    profile = db.relationship("UserProfile", back_populates="user", uselist=False)
    characters = db.relationship("Character", back_populates="user", cascade="all, delete-orphan")


class UserProfile(db.Model, TimestampMixin):
    """Public profile metadata for a user."""

    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    display_name = db.Column(db.String(80), nullable=False)
    bio = db.Column(db.Text)
    avatar_path = db.Column(db.String(255))
    show_profile_public = db.Column(db.Boolean, default=True, nullable=False)
    show_characters_public = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship("User", back_populates="profile")


class Character(db.Model, TimestampMixin):
    """Player character and the root record for character-owned game state."""

    __tablename__ = "characters"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    race = db.Column(db.String(40), nullable=False)
    class_name = db.Column(db.String(40), nullable=False)
    gender = db.Column(db.String(20), default="male", nullable=False)
    background = db.Column(db.Text)
    description = db.Column(db.Text)
    avatar_path = db.Column(db.String(255))
    portrait_key = db.Column(db.String(120))
    level = db.Column(db.Integer, default=1, nullable=False)
    xp = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(20), default="alive", nullable=False)
    inventory_json = db.Column(db.Text, default="{}", nullable=False)
    currency_json = db.Column(db.JSON, default=dict, nullable=False)

    user = db.relationship("User", back_populates="characters")
    attributes = db.relationship("CharacterAttribute", back_populates="character", uselist=False, cascade="all, delete-orphan")
    resources = db.relationship("CharacterResource", back_populates="character", uselist=False, cascade="all, delete-orphan")
    skills = db.relationship("CharacterSkill", back_populates="character", cascade="all, delete-orphan")
    campaigns = db.relationship("Campaign", back_populates="character", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Character state and progression
# ---------------------------------------------------------------------------


class CharacterAttribute(db.Model):
    """Core character attributes plus per-attribute lifetime XP."""

    __tablename__ = "character_attributes"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), unique=True, nullable=False)
    strength = db.Column(db.Integer, default=5, nullable=False)
    dexterity = db.Column(db.Integer, default=5, nullable=False)
    constitution = db.Column(db.Integer, default=5, nullable=False)
    intelligence = db.Column(db.Integer, default=5, nullable=False)
    perception = db.Column(db.Integer, default=5, nullable=False)
    charisma = db.Column(db.Integer, default=5, nullable=False)
    attribute_xp_json = db.Column(db.Text, default="{}", nullable=False)

    character = db.relationship("Character", back_populates="attributes")


class CharacterResource(db.Model):
    """Current and maximum HP, energy, mana, and legacy stamina values."""

    __tablename__ = "character_resources"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), unique=True, nullable=False)
    hp_current = db.Column(db.Integer, default=100, nullable=False)
    hp_max = db.Column(db.Integer, default=100, nullable=False)
    energy_current = db.Column(db.Integer, default=100, nullable=False)
    energy_max = db.Column(db.Integer, default=100, nullable=False)
    mana_current = db.Column(db.Integer, default=0, nullable=False)
    mana_max = db.Column(db.Integer, default=0, nullable=False)
    stamina_current = db.Column(db.Integer, default=100, nullable=False)
    stamina_max = db.Column(db.Integer, default=100, nullable=False)

    character = db.relationship("Character", back_populates="resources")


class SkillDefinition(db.Model):
    """Global skill catalog entry.

    Core skills are seeded and shared. Custom skills use the same table but are
    marked with is_custom so they can be attached to characters without adding
    new schema for every generated profession or activity.
    """

    __tablename__ = "skill_definitions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    category = db.Column(db.String(40), nullable=False)
    linked_attribute = db.Column(db.String(40), nullable=False)
    secondary_attributes_json = db.Column(db.Text, default="[]", nullable=False)
    aliases_json = db.Column(db.Text, default="[]", nullable=False)
    allowed_domains_json = db.Column(db.Text, default="[]", nullable=False)
    description = db.Column(db.Text)
    icon = db.Column(db.String(12))
    short_code = db.Column(db.String(8))
    is_custom = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    character_skills = db.relationship("CharacterSkill", back_populates="skill")


class CharacterSkill(db.Model, TimestampMixin):
    """Per-character progress for a global or custom skill definition."""

    __tablename__ = "character_skills"
    __table_args__ = (
        db.UniqueConstraint("character_id", "skill_id", name="uq_character_skill"),
    )

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill_definitions.id"), nullable=False)
    skill_level = db.Column(db.Integer, default=0, nullable=False)
    skill_xp = db.Column(db.Integer, default=0, nullable=False)
    bonus_modifier = db.Column(db.Integer, default=0, nullable=False)

    character = db.relationship("Character", back_populates="skills")
    skill = db.relationship("SkillDefinition", back_populates="character_skills")


# ---------------------------------------------------------------------------
# World templates and active campaign state
# ---------------------------------------------------------------------------


class WorldTemplate(db.Model, TimestampMixin):
    """Reusable world seed used when starting a campaign."""

    __tablename__ = "world_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    lore_summary = db.Column(db.Text)
    current_era = db.Column(db.String(100))
    world_year = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    locations = db.relationship("TemplateLocation", back_populates="world_template", cascade="all, delete-orphan")
    npcs = db.relationship("TemplateNPC", back_populates="world_template", cascade="all, delete-orphan")


class TemplateLocation(db.Model):
    """Location blueprint that can be copied or referenced by campaigns."""

    __tablename__ = "template_locations"

    id = db.Column(db.Integer, primary_key=True)
    world_template_id = db.Column(db.Integer, db.ForeignKey("world_templates.id"), nullable=False)
    parent_location_id = db.Column(db.Integer, db.ForeignKey("template_locations.id"))
    name = db.Column(db.String(120), nullable=False)
    location_type = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text)
    lore_text = db.Column(db.Text)
    is_discoverable = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    world_template = db.relationship("WorldTemplate", back_populates="locations")
    parent = db.relationship("TemplateLocation", remote_side=[id])


class TemplateNPC(db.Model):
    """NPC blueprint belonging to a world template."""

    __tablename__ = "template_npcs"

    id = db.Column(db.Integer, primary_key=True)
    world_template_id = db.Column(db.Integer, db.ForeignKey("world_templates.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("template_locations.id"))
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text)
    personality_summary = db.Column(db.Text)
    base_attitude = db.Column(db.String(30), default="neutral", nullable=False)
    is_important = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    world_template = db.relationship("WorldTemplate", back_populates="npcs")


class Campaign(db.Model, TimestampMixin):
    """Active adventure instance for one character in one world template."""

    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    world_template_id = db.Column(db.Integer, db.ForeignKey("world_templates.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), default="active", nullable=False)
    current_location_id = db.Column(db.Integer)
    current_ingame_day = db.Column(db.Integer, default=1, nullable=False)
    current_ingame_minute = db.Column(db.Integer, default=540, nullable=False)
    current_ingame_time = db.Column(db.String(20), default="morning", nullable=False)
    last_played_at = db.Column(db.DateTime, default=datetime.utcnow)

    character = db.relationship("Character", back_populates="campaigns")
    world_template = db.relationship("WorldTemplate")
    state = db.relationship("CampaignState", back_populates="campaign", uselist=False, cascade="all, delete-orphan")
    locations = db.relationship(
        "CampaignLocation",
        back_populates="campaign",
        cascade="all, delete-orphan",
        foreign_keys="CampaignLocation.campaign_id",
    )
    npcs = db.relationship("CampaignNPC", back_populates="campaign", cascade="all, delete-orphan")
    quests = db.relationship("CampaignQuest", back_populates="campaign", cascade="all, delete-orphan")
    items = db.relationship("CampaignItem", back_populates="campaign", cascade="all, delete-orphan")
    enemies = db.relationship("EnemyInstance", back_populates="campaign", cascade="all, delete-orphan")
    story_messages = db.relationship("StoryMessage", back_populates="campaign", cascade="all, delete-orphan")
    session_summaries = db.relationship("SessionSummary", back_populates="campaign", cascade="all, delete-orphan")
    settings = db.relationship("CampaignSetting", back_populates="campaign", uselist=False, cascade="all, delete-orphan")


class CampaignState(db.Model):
    """Long-lived campaign summary state beyond the immediate location."""

    __tablename__ = "campaign_state"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), unique=True, nullable=False)
    main_objective = db.Column(db.Text)
    current_scene_summary = db.Column(db.Text)
    world_state_summary = db.Column(db.Text)
    last_session_summary = db.Column(db.Text)
    notes_json = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    campaign = db.relationship("Campaign", back_populates="state")


class CampaignLocation(db.Model, TimestampMixin):
    """Discovered or generated location in a specific campaign."""

    __tablename__ = "campaign_locations"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    template_location_id = db.Column(db.Integer, db.ForeignKey("template_locations.id"))
    name = db.Column(db.String(120), nullable=False)
    location_type = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text)
    coordinate_x = db.Column(db.Float)
    coordinate_y = db.Column(db.Float)
    coordinate_source = db.Column(db.String(40))
    region_id = db.Column(db.String(80))
    region_name = db.Column(db.String(120))
    subregion = db.Column(db.String(120))
    world_location_id = db.Column(db.String(80))
    world_location_name = db.Column(db.String(120))
    is_discovered = db.Column(db.Boolean, default=False, nullable=False)
    is_custom = db.Column(db.Boolean, default=False, nullable=False)
    custom_state_json = db.Column(db.Text)

    campaign = db.relationship(
        "Campaign",
        back_populates="locations",
        foreign_keys=[campaign_id],
    )


class CampaignNPC(db.Model, TimestampMixin):
    """Campaign-specific NPC state, including generated NPCs."""

    __tablename__ = "campaign_npcs"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    template_npc_id = db.Column(db.Integer, db.ForeignKey("template_npcs.id"))
    current_location_id = db.Column(db.Integer, db.ForeignKey("campaign_locations.id"))
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(30), default="alive", nullable=False)
    attitude_label = db.Column(db.String(30), default="neutral", nullable=False)
    relationship_score = db.Column(db.Integer, default=0, nullable=False)
    is_custom = db.Column(db.Boolean, default=False, nullable=False)
    state_json = db.Column(db.Text)

    campaign = db.relationship("Campaign", back_populates="npcs")
    merchant = db.relationship("Merchant", back_populates="campaign_npc", uselist=False, cascade="all, delete-orphan")


class CampaignQuest(db.Model, TimestampMixin):
    """Quest record tracked inside one campaign."""

    __tablename__ = "campaign_quests"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    quest_type = db.Column(db.String(40), default="general", nullable=False)
    status = db.Column(db.String(20), default="active", nullable=False)
    quest_giver_npc_id = db.Column(db.Integer, db.ForeignKey("campaign_npcs.id"))
    turn_in_npc_id = db.Column(db.Integer, db.ForeignKey("campaign_npcs.id"))
    start_location_id = db.Column(db.Integer, db.ForeignKey("campaign_locations.id"))
    target_location_id = db.Column(db.Integer, db.ForeignKey("campaign_locations.id"))
    turn_in_location_id = db.Column(db.Integer, db.ForeignKey("campaign_locations.id"))
    objectives_json = db.Column(db.Text, default="[]", nullable=False)
    reward_gold = db.Column(db.Integer, default=0, nullable=False)
    reward_xp = db.Column(db.Integer, default=0, nullable=False)
    reward_items_json = db.Column(db.Text)
    rewards_json = db.Column(db.Text, default="{}", nullable=False)
    reward_rules_json = db.Column(db.Text, default="{}", nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime)
    turned_in_at = db.Column(db.DateTime)
    reward_claimed_at = db.Column(db.DateTime)
    failed_at = db.Column(db.DateTime)

    campaign = db.relationship("Campaign", back_populates="quests")


# ---------------------------------------------------------------------------
# Items, merchants, and commerce
# ---------------------------------------------------------------------------


class ItemDefinition(db.Model, TimestampMixin):
    """Template item definition for future reusable item generation."""

    __tablename__ = "item_definitions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    item_type = db.Column(db.String(40), nullable=False)
    rarity = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    value_base = db.Column(db.Integer, default=0, nullable=False)
    weight = db.Column(db.Integer, default=0, nullable=False)
    slot_type = db.Column(db.String(40))
    stat_modifiers_json = db.Column(db.Text)
    is_template_item = db.Column(db.Boolean, default=True, nullable=False)


class CampaignItem(db.Model, TimestampMixin):
    """Concrete item instance generated or discovered inside a campaign."""

    __tablename__ = "campaign_items"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    base_item_id = db.Column(db.Integer, db.ForeignKey("item_definitions.id"))
    name = db.Column(db.String(120), nullable=False)
    item_type = db.Column(db.String(40), nullable=False)
    rarity = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    value_final = db.Column(db.Integer, default=0, nullable=False)
    weight = db.Column(db.Integer, default=0, nullable=False)
    slot_type = db.Column(db.String(40))
    stat_modifiers_json = db.Column(db.Text)
    special_effects_json = db.Column(db.Text)
    is_generated = db.Column(db.Boolean, default=False, nullable=False)

    campaign = db.relationship("Campaign", back_populates="items")


class Merchant(db.Model):
    """Merchant behavior and pricing profile attached to a campaign NPC."""

    __tablename__ = "merchants"

    id = db.Column(db.Integer, primary_key=True)
    campaign_npc_id = db.Column(db.Integer, db.ForeignKey("campaign_npcs.id"), nullable=False)
    merchant_type = db.Column(db.String(40), nullable=False)
    refresh_rule = db.Column(db.String(20), default="daily", nullable=False)
    last_refresh_ingame_day = db.Column(db.Integer, default=1, nullable=False)
    price_modifier = db.Column(db.Integer, default=100, nullable=False)
    inventory_profile_json = db.Column(db.Text)

    campaign_npc = db.relationship("CampaignNPC", back_populates="merchant")
    inventory = db.relationship("MerchantInventory", back_populates="merchant", cascade="all, delete-orphan")


class MerchantInventory(db.Model):
    """Stock entry linking a merchant to a campaign item."""

    __tablename__ = "merchant_inventory"

    id = db.Column(db.Integer, primary_key=True)
    merchant_id = db.Column(db.Integer, db.ForeignKey("merchants.id"), nullable=False)
    campaign_item_id = db.Column(db.Integer, db.ForeignKey("campaign_items.id"), nullable=False)
    stock_quantity = db.Column(db.Integer, default=1, nullable=False)
    price_override = db.Column(db.Integer)
    generated_ingame_day = db.Column(db.Integer, nullable=False)
    is_sold_out = db.Column(db.Boolean, default=False, nullable=False)

    merchant = db.relationship("Merchant", back_populates="inventory")


# ---------------------------------------------------------------------------
# Enemies, status effects, and checks
# ---------------------------------------------------------------------------


class EnemyDefinition(db.Model, TimestampMixin):
    """Reusable enemy stat block for future combat generation."""

    __tablename__ = "enemy_definitions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    enemy_type = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text)
    base_hp = db.Column(db.Integer, nullable=False)
    base_armor = db.Column(db.Integer, nullable=False)
    base_evasion = db.Column(db.Integer, nullable=False)
    base_damage_min = db.Column(db.Integer, nullable=False)
    base_damage_max = db.Column(db.Integer, nullable=False)
    awareness_default = db.Column(db.String(20), default="idle", nullable=False)
    weaknesses_json = db.Column(db.Text)
    resistances_json = db.Column(db.Text)
    target_modifiers_json = db.Column(db.Text)


class EnemyInstance(db.Model, TimestampMixin):
    """Concrete enemy state inside a campaign."""

    __tablename__ = "enemy_instances"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    enemy_definition_id = db.Column(db.Integer, db.ForeignKey("enemy_definitions.id"), nullable=False)
    current_location_id = db.Column(db.Integer, db.ForeignKey("campaign_locations.id"))
    custom_name = db.Column(db.String(100))
    hp_current = db.Column(db.Integer, nullable=False)
    hp_max = db.Column(db.Integer, nullable=False)
    armor_current = db.Column(db.Integer, nullable=False)
    evasion_current = db.Column(db.Integer, nullable=False)
    awareness_state = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="alive", nullable=False)
    state_json = db.Column(db.Text)

    campaign = db.relationship("Campaign", back_populates="enemies")
    status_effects = db.relationship("EnemyStatusEffect", back_populates="enemy_instance", cascade="all, delete-orphan")


class StatusEffectDefinition(db.Model):
    """Reusable status effect definition for buffs, debuffs, and conditions."""

    __tablename__ = "status_effect_definitions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    effect_type = db.Column(db.String(40), nullable=False)
    default_duration_turns = db.Column(db.Integer, default=1, nullable=False)
    modifiers_json = db.Column(db.Text)


class EnemyStatusEffect(db.Model):
    """Active status effect applied to an enemy instance."""

    __tablename__ = "enemy_status_effects"

    id = db.Column(db.Integer, primary_key=True)
    enemy_instance_id = db.Column(db.Integer, db.ForeignKey("enemy_instances.id"), nullable=False)
    status_effect_id = db.Column(db.Integer, db.ForeignKey("status_effect_definitions.id"), nullable=False)
    duration_remaining = db.Column(db.Integer, nullable=False)
    source_text = db.Column(db.Text)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    enemy_instance = db.relationship("EnemyInstance", back_populates="status_effects")


class CharacterStatusEffect(db.Model):
    """Active status effect applied to a player character."""

    __tablename__ = "character_status_effects"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    status_effect_id = db.Column(db.Integer, db.ForeignKey("status_effect_definitions.id"), nullable=False)
    duration_remaining = db.Column(db.Integer, nullable=False)
    source_text = db.Column(db.Text)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SkillCheckLog(db.Model):
    """Audit trail for future deterministic skill checks and combat rolls."""

    __tablename__ = "skill_check_log"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"))
    enemy_instance_id = db.Column(db.Integer, db.ForeignKey("enemy_instances.id"))
    action_text = db.Column(db.Text, nullable=False)
    action_type = db.Column(db.String(60), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill_definitions.id"))
    attribute_used = db.Column(db.String(40))
    difficulty_value = db.Column(db.Integer, nullable=False)
    roll_value = db.Column(db.Integer, nullable=False)
    total_value = db.Column(db.Integer, nullable=False)
    outcome = db.Column(db.String(30), nullable=False)
    damage_done = db.Column(db.Integer)
    status_effects_applied_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Story, support, and campaign settings
# ---------------------------------------------------------------------------


class StoryMessage(db.Model):
    """Persisted chat/story message for campaign history."""

    __tablename__ = "story_messages"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    message_type = db.Column(db.String(30), nullable=False)
    sender_type = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    campaign = db.relationship("Campaign", back_populates="story_messages")


class SessionSummary(db.Model):
    """Condensed campaign summary for future long-context management."""

    __tablename__ = "session_summaries"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    summary_type = db.Column(db.String(20), nullable=False)
    summary_text = db.Column(db.Text, nullable=False)
    important_npcs_json = db.Column(db.Text)
    important_locations_json = db.Column(db.Text)
    open_quests_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    campaign = db.relationship("Campaign", back_populates="session_summaries")


class SupportChatSession(db.Model, TimestampMixin):
    """Out-of-game support chat session."""

    __tablename__ = "support_chat_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"))
    context_mode = db.Column(db.String(30), nullable=False)


class SupportChatMessage(db.Model):
    """Message belonging to a support chat session."""

    __tablename__ = "support_chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("support_chat_sessions.id"), nullable=False)
    sender_type = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class LLMModelConfig(db.Model):
    """Selectable LLM provider/model configuration."""

    __tablename__ = "llm_model_configs"

    id = db.Column(db.Integer, primary_key=True)
    provider_name = db.Column(db.String(50), nullable=False)
    model_name = db.Column(db.String(80), nullable=False)
    display_name = db.Column(db.String(80), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    supports_json_mode = db.Column(db.Boolean, default=True, nullable=False)
    supports_tools = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CampaignSetting(db.Model):
    """Per-campaign gameplay and model settings."""

    __tablename__ = "campaign_settings"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), unique=True, nullable=False)
    selected_model_id = db.Column(db.Integer, db.ForeignKey("llm_model_configs.id"), nullable=False)
    narrative_style = db.Column(db.String(40), default="fantasy_adventure", nullable=False)
    violence_filter_mode = db.Column(db.String(30), default="moderate", nullable=False)
    difficulty_mode = db.Column(db.String(30), default="normal", nullable=False)
    merchant_generation_mode = db.Column(db.String(30), default="hybrid", nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    campaign = db.relationship("Campaign", back_populates="settings")
