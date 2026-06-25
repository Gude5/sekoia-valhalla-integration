from sekoia_valhalla_integration_modules.sigma_mapper import (
    DEFAULT_EFFORT,
    DEFAULT_SEVERITY,
    sigma_rule_to_catalog_payload,
)

HIGH_RULE_YAML = """\
title: Suspicious process creation
description: Detects a suspicious process being spawned.
level: high
logsource:
  product: windows
detection:
  selection: {EventID: 4688}
  condition: selection
"""

RULE = {
    "id": "abc-123",
    "filename": "proc_creation.yml",
    "content": HIGH_RULE_YAML,
}


def test_maps_required_fields():
    body = sigma_rule_to_catalog_payload(RULE, "alert-uuid", enabled=False)

    assert body["name"] == "Suspicious process creation"
    assert body["type"] == "sigma"
    assert body["description"] == "Detects a suspicious process being spawned."
    assert body["payload"] == HIGH_RULE_YAML
    assert body["severity"] == 70
    assert body["effort"] == DEFAULT_EFFORT
    assert body["alert_type_uuid"] == "alert-uuid"
    assert body["enabled"] is False


def test_enabled_flag_propagates():
    body = sigma_rule_to_catalog_payload(RULE, "x", enabled=True)
    assert body["enabled"] is True


def test_severity_mapping_per_level():
    cases = [
        ("informational", 20),
        ("low", 30),
        ("medium", 40),
        ("high", 70),
        ("critical", 90),
    ]
    for level, expected in cases:
        rule = {"id": "x", "content": f"title: t\nlevel: {level}\n"}
        body = sigma_rule_to_catalog_payload(rule, "a", enabled=False)
        assert body["severity"] == expected, f"level={level}"


def test_severity_falls_back_to_default_when_level_missing():
    rule = {"id": "x", "content": "title: no-level\n"}
    body = sigma_rule_to_catalog_payload(rule, "a", enabled=False)
    assert body["severity"] == DEFAULT_SEVERITY


def test_title_falls_back_to_filename_when_yaml_lacks_title():
    rule = {
        "id": "x",
        "filename": "fallback_name.yml",
        "content": "description: no title here\nlevel: medium\n",
    }
    body = sigma_rule_to_catalog_payload(rule, "a", enabled=False)
    assert body["name"] == "fallback_name.yml"


def test_handles_malformed_yaml_gracefully():
    rule = {
        "id": "x",
        "filename": "broken.yml",
        "content": "::: not valid yaml :::\n  - [unbalanced",
    }
    body = sigma_rule_to_catalog_payload(rule, "a", enabled=False)
    assert body["name"] == "broken.yml"
    assert body["severity"] == DEFAULT_SEVERITY
    assert body["payload"] == rule["content"]


def test_uses_top_level_level_field_when_yaml_lacks_one():
    rule = {
        "id": "x",
        "filename": "n.yml",
        "level": "critical",
        "content": "title: t\n",
    }
    body = sigma_rule_to_catalog_payload(rule, "a", enabled=False)
    assert body["severity"] == 90
