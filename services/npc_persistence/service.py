"""NPC persistence rules for quest anchors and temporary flavor NPCs."""

from __future__ import annotations

import json
from typing import Any

from models import Campaign, CampaignNPC, CampaignQuest, db

FLAVOR_NPC_RETENTION_DAYS = 2


def _load_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
        return decoded
    return fallback


def _npc_state_payload(npc: CampaignNPC) -> dict:
    payload = _load_json(getattr(npc, "state_json", None), {})
    return payload if isinstance(payload, dict) else {}


def _save_npc_state(npc: CampaignNPC, payload: dict) -> None:
    npc.state_json = json.dumps(payload or {}, ensure_ascii=False)


def _persistence_payload(npc: CampaignNPC) -> dict:
    state = _npc_state_payload(npc)
    payload = state.get("persistence")
    return dict(payload) if isinstance(payload, dict) else {}


def _set_persistence_payload(npc: CampaignNPC, payload: dict) -> None:
    state = _npc_state_payload(npc)
    state["persistence"] = payload
    _save_npc_state(npc, state)


def _trainer_anchor(npc: CampaignNPC) -> bool:
    state = _npc_state_payload(npc)
    return isinstance(state.get("trainer_profile"), dict)


def _quest_referenced_npc_ids(campaign_id: int) -> set[int]:
    referenced_ids: set[int] = set()
    quests = CampaignQuest.query.filter_by(campaign_id=campaign_id).all()
    for quest in quests:
        for field_name in ("quest_giver_npc_id", "turn_in_npc_id"):
            value = getattr(quest, field_name, None)
            if value:
                referenced_ids.add(int(value))

        objectives = _load_json(getattr(quest, "objectives_json", None), [])
        if isinstance(objectives, list):
            for objective in objectives:
                if not isinstance(objective, dict):
                    continue
                value = objective.get("npc_id")
                if value:
                    referenced_ids.add(int(value))

        rewards = _load_json(getattr(quest, "rewards_json", None), {})
        services = rewards.get("services", []) if isinstance(rewards, dict) else []
        if isinstance(services, list):
            for service in services:
                if not isinstance(service, dict):
                    continue
                value = service.get("provider_npc_id")
                if value:
                    referenced_ids.add(int(value))
    return referenced_ids


def anchor_npcs_for_quest_references(campaign_id: int, npc_ids: list[int] | set[int] | tuple[int, ...] | None = None, reason: str = "quest_anchor") -> None:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return

    target_ids = {int(value) for value in (npc_ids or []) if value}
    target_ids.update(_quest_referenced_npc_ids(campaign_id))
    if not target_ids:
        return

    npcs = CampaignNPC.query.filter(CampaignNPC.campaign_id == campaign.id, CampaignNPC.id.in_(target_ids)).all()
    current_day = int(campaign.current_ingame_day or 1)
    for npc in npcs:
        payload = _persistence_payload(npc)
        reasons = [str(item).strip() for item in payload.get("reasons", []) if str(item).strip()]
        if reason not in reasons:
            reasons.append(reason)
        payload.update({
            "mode": "anchored",
            "reasons": reasons,
            "anchored_on_day": int(payload.get("anchored_on_day", current_day) or current_day),
            "last_seen_day": int(payload.get("last_seen_day", current_day) or current_day),
            "expires_on_day": None,
        })
        _set_persistence_payload(npc, payload)


def cleanup_ephemeral_npcs(campaign_id: int, current_location_id: int | None = None) -> dict:
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return {"removed_npc_ids": [], "anchored_npc_ids": [], "touched_npc_ids": []}

    current_day = int(campaign.current_ingame_day or 1)
    quest_anchor_ids = _quest_referenced_npc_ids(campaign.id)
    removed_npc_ids: list[int] = []
    anchored_npc_ids: list[int] = []
    touched_npc_ids: list[int] = []

    npcs = CampaignNPC.query.filter_by(campaign_id=campaign.id, is_custom=True).all()
    for npc in npcs:
        is_anchor = bool(npc.merchant) or _trainer_anchor(npc) or int(npc.id) in quest_anchor_ids
        payload = _persistence_payload(npc)

        if is_anchor:
            reasons = [str(item).strip() for item in payload.get("reasons", []) if str(item).strip()]
            if int(npc.id) in quest_anchor_ids and "quest_anchor" not in reasons:
                reasons.append("quest_anchor")
            if npc.merchant and "merchant_anchor" not in reasons:
                reasons.append("merchant_anchor")
            if _trainer_anchor(npc) and "trainer_anchor" not in reasons:
                reasons.append("trainer_anchor")
            payload.update({
                "mode": "anchored",
                "reasons": reasons,
                "anchored_on_day": int(payload.get("anchored_on_day", current_day) or current_day),
                "last_seen_day": int(payload.get("last_seen_day", current_day) or current_day),
                "expires_on_day": None,
            })
            _set_persistence_payload(npc, payload)
            anchored_npc_ids.append(int(npc.id))
            continue

        expires_on_day = payload.get("expires_on_day")
        if not expires_on_day:
            expires_on_day = current_day + FLAVOR_NPC_RETENTION_DAYS
        else:
            expires_on_day = int(expires_on_day)

        if current_location_id is not None and int(npc.current_location_id or 0) == int(current_location_id):
            payload["last_seen_day"] = current_day
            expires_on_day = max(expires_on_day, current_day + FLAVOR_NPC_RETENTION_DAYS)
            touched_npc_ids.append(int(npc.id))

        payload.update({
            "mode": "ephemeral",
            "reasons": [],
            "expires_on_day": int(expires_on_day),
        })
        _set_persistence_payload(npc, payload)

        if current_day > int(expires_on_day):
            removed_npc_ids.append(int(npc.id))
            db.session.delete(npc)

    return {
        "removed_npc_ids": removed_npc_ids,
        "anchored_npc_ids": anchored_npc_ids,
        "touched_npc_ids": touched_npc_ids,
    }
