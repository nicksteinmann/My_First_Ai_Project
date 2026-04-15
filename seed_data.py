from app import app
from models import db, WorldTemplate, SkillDefinition, LLMModelConfig


def seed():
    with app.app_context():

        # === Skills (nur Basics) ===
        skills = [
            {"name": "Schwertkampf", "category": "Kampf", "linked_attribute": "strength"},
            {"name": "Bogenschießen", "category": "Kampf", "linked_attribute": "dexterity"},
            {"name": "Schlösser knacken", "category": "Utility", "linked_attribute": "dexterity"},
            {"name": "Täuschen", "category": "Social", "linked_attribute": "charisma"},
        ]

        for s in skills:
            if not SkillDefinition.query.filter_by(name=s["name"]).first():
                db.session.add(SkillDefinition(**s))

        # === Welt (Platzhalter) ===
        if not WorldTemplate.query.filter_by(slug="testwelt").first():
            world = WorldTemplate(
                name="Testwelt",
                slug="testwelt",
                description="Eine einfache Testwelt.",
                lore_summary="Platzhalter-Lore",
                current_era="Mittelalter",
                world_year=1000
            )
            db.session.add(world)

        # === Modelle (für Auswahl später) ===
        models = [
            {"provider_name": "openai", "model_name": "gpt-4.1-mini", "display_name": "GPT Mini"},
            {"provider_name": "deepseek", "model_name": "deepseek-chat", "display_name": "DeepSeek"}
        ]

        for m in models:
            if not LLMModelConfig.query.filter_by(model_name=m["model_name"]).first():
                db.session.add(LLMModelConfig(**m))

        db.session.commit()
        print("Seed Daten eingefügt.")


if __name__ == "__main__":
    seed()