"""Development seed script for baseline data."""

from app import app
from models import db, WorldTemplate, SkillDefinition, LLMModelConfig
from services.skills.constants import CORE_SKILLS


def seed():
    """Insert baseline skills, world template, and model configs if missing."""

    with app.app_context():
        skills = CORE_SKILLS

        for s in skills:
            if not SkillDefinition.query.filter_by(name=s["name"]).first():
                db.session.add(SkillDefinition(
                    name=s["name"],
                    category=s["category"],
                    linked_attribute=s["linked_attribute"],
                    description=s.get("description"),
                    icon=s.get("icon"),
                    short_code=s.get("short_code"),
                    is_custom=False,
                    is_active=True,
                ))

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

        models = [
            {"provider_name": "openai", "model_name": "gpt-4.1-mini", "display_name": "GPT Mini"},
            {"provider_name": "deepseek", "model_name": "deepseek-chat", "display_name": "DeepSeek"}
        ]

        for m in models:
            if not LLMModelConfig.query.filter_by(model_name=m["model_name"]).first():
                db.session.add(LLMModelConfig(**m))

        db.session.commit()
        print("Seed data inserted.")


if __name__ == "__main__":
    seed()
