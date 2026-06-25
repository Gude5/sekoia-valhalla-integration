import uuid
from datetime import datetime, timezone

VALHALLA_NAMESPACE = uuid.UUID("9739cddd-e475-4bde-b505-d51c99d97113")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def sigma_rule_to_indicator(rule: dict) -> dict:
    name = rule.get("filename") or rule.get("title") or "unnamed-sigma-rule"
    indicator_id = "indicator--" + str(uuid.uuid5(VALHALLA_NAMESPACE, f"sigma::{name}"))
    now = _now_iso()
    return {
        "type": "indicator",
        "spec_version": "2.1",
        "id": indicator_id,
        "created": now,
        "modified": now,
        "name": name,
        "pattern": rule["content"],
        "pattern_type": "sigma",
        "valid_from": now,
        "labels": ["sigma", "valhalla"],
    }


def build_bundle(indicators: list[dict]) -> dict:
    return {
        "type": "bundle",
        "id": "bundle--" + str(uuid.uuid4()),
        "objects": indicators,
    }
