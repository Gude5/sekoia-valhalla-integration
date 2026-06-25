from sekoia_valhalla_integration_modules.stix import (
    build_bundle,
    sigma_rule_to_indicator,
)


SAMPLE_RULE = {
    "signature_type": "sigma",
    "type": "process_creation",
    "filename": "proc_creation_win_susp.yml",
    "content": "title: Suspicious process creation\nlogsource:\n  product: windows\n",
}


def test_sigma_rule_to_indicator_shape():
    ind = sigma_rule_to_indicator(SAMPLE_RULE)

    assert ind["type"] == "indicator"
    assert ind["spec_version"] == "2.1"
    assert ind["id"].startswith("indicator--")
    assert ind["name"] == "proc_creation_win_susp.yml"
    assert ind["pattern"] == SAMPLE_RULE["content"]
    assert ind["pattern_type"] == "sigma"
    assert ind["labels"] == ["sigma", "valhalla"]
    assert "valid_from" in ind
    assert "created" in ind
    assert "modified" in ind


def test_sigma_rule_to_indicator_id_is_deterministic():
    a = sigma_rule_to_indicator(SAMPLE_RULE)
    b = sigma_rule_to_indicator(SAMPLE_RULE)
    assert a["id"] == b["id"]


def test_sigma_rule_to_indicator_id_differs_per_rule():
    other = dict(SAMPLE_RULE, filename="other.yml")
    a = sigma_rule_to_indicator(SAMPLE_RULE)
    b = sigma_rule_to_indicator(other)
    assert a["id"] != b["id"]


def test_sigma_rule_to_indicator_falls_back_when_filename_missing():
    rule = {"content": "title: X", "title": "Some title"}
    ind = sigma_rule_to_indicator(rule)
    assert ind["name"] == "Some title"


def test_build_bundle_wraps_indicators():
    indicators = [sigma_rule_to_indicator(SAMPLE_RULE)]
    bundle = build_bundle(indicators)

    assert bundle["type"] == "bundle"
    assert bundle["id"].startswith("bundle--")
    assert bundle["objects"] == indicators
