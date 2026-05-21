"""Development seed script for baseline data."""

from app import app
from models import db, TemplateLocation, WorldTemplate, SkillDefinition, LLMModelConfig
from services.skills.constants import CORE_SKILLS
from services.world_data import ensure_world_template_locations, load_world_data


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

        world_data = load_world_data()

        if not WorldTemplate.query.filter_by(slug="avalion-default").first():
            world = WorldTemplate(
                name=world_data["name"],
                slug="avalion-default",
                description=world_data["summary"],
                lore_summary=world_data["summary"],
                current_era=world_data["era"],
                world_year=world_data["year"]
            )
            db.session.add(world)
            db.session.flush()
            ensure_world_template_locations(db.session, world, TemplateLocation)
        else:
            world = WorldTemplate.query.filter_by(slug="avalion-default").first()
            ensure_world_template_locations(db.session, world, TemplateLocation)

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
