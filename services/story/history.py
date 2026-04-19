from models import StoryMessage


def get_recent_story_messages(campaign_id, limit=12):
    messages = (
        StoryMessage.query
        .filter_by(campaign_id=campaign_id)
        .order_by(StoryMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(messages))


def serialize_story_messages_for_template(messages):
    serialized = []

    for msg in messages:
        if msg.sender_type == "user":
            css_class = "user"
            sender_label = "You"
        elif msg.sender_type in ("assistant", "ai", "gm"):
            css_class = "ai"
            sender_label = "Game Master"
        else:
            css_class = "system"
            sender_label = "System"

        serialized.append({
            "sender_label": sender_label,
            "css_class": css_class,
            "content": msg.content
        })

    return serialized


def build_story_history_text(messages):
    if not messages:
        return ""

    lines = []
    for msg in messages:
        if msg.sender_type == "user":
            speaker = "Player"
        elif msg.sender_type in ("assistant", "ai", "gm"):
            speaker = "Game Master"
        else:
            speaker = "System"

        lines.append(f"{speaker}: {msg.content}")

    return "\n".join(lines)