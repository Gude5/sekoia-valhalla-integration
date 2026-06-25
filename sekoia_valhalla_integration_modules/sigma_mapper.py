import yaml

SEVERITY_MAP = {
    "informational": 20,
    "low": 30,
    "medium": 40,
    "high": 70,
    "critical": 90,
}
DEFAULT_SEVERITY = 40
DEFAULT_EFFORT = 2


def sigma_rule_to_catalog_payload(
    rule: dict, alert_type_uuid: str, enabled: bool
) -> dict:
    payload_yaml = rule["content"]
    try:
        parsed = yaml.safe_load(payload_yaml) or {}
    except yaml.YAMLError:
        parsed = {}

    title = parsed.get("title") or rule.get("name") or rule.get("filename") or "unnamed"
    description = parsed.get("description") or rule.get("description") or ""
    level = (parsed.get("level") or rule.get("level") or "").lower()
    severity = SEVERITY_MAP.get(level, DEFAULT_SEVERITY)

    return {
        "name": title,
        "type": "sigma",
        "description": description,
        "payload": payload_yaml,
        "severity": severity,
        "effort": DEFAULT_EFFORT,
        "alert_type_uuid": alert_type_uuid,
        "enabled": enabled,
    }
