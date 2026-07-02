import re
from typing import Optional

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

# Tier 1: clean 1:1 mappings from raw SigmaHQ field names to Elastic Common
# Schema. Covers the ~22 most-frequent Windows/network fields in the Valhalla
# feed; forecast yield ~40-50% of the feed on its own. Extended in later
# stages (Tier 3 passthrough + Tier 2 context-dependent + user overrides).
RAW_TO_ECS: dict[str, str] = {
    # Process
    "Image": "process.executable",
    "CommandLine": "process.command_line",
    "OriginalFileName": "process.pe.original_file_name",
    "ParentImage": "process.parent.executable",
    "ParentCommandLine": "process.parent.command_line",
    "ProcessName": "process.name",
    "CurrentDirectory": "process.working_directory",
    "IntegrityLevel": "process.integrity_level",
    "User": "user.name",
    "SourceImage": "process.executable",
    "TargetImage": "process.executable",
    # Users
    "TargetUserName": "user.target.name",
    # Event metadata
    "EventID": "event.code",
    "Provider_Name": "winlog.provider_name",
    "EventLog": "winlog.channel",
    # Files / DLLs / pipes
    "TargetFilename": "file.path",
    "ImageLoaded": "dll.path",
    "ImagePath": "process.executable",
    "PipeName": "file.name",
    # PE metadata (Sysmon image_load)
    "Description": "file.pe.description",
    "Product": "file.pe.product",
    "Company": "file.pe.company",
    # PowerShell
    "ScriptBlockText": "powershell.file.script_block_text",
    # Network / DNS
    "DestinationIp": "destination.ip",
    "DestinationPort": "destination.port",
    "DestinationHostname": "destination.domain",
    "SourceIp": "source.ip",
    "IpAddress": "source.ip",
    "QueryName": "dns.question.name",
    "Initiated": "network.direction",
    # Web / proxy — W3C ELF fields used by IIS + proxy logs
    "cs-method": "http.request.method",
    "cs-referer": "http.request.referrer",
    "cs-uri-query": "url.query",
    "cs-uri-stem": "url.path",
    "cs-uri": "url.original",
    "sc-status": "http.response.status_code",
    "userAgent": "user_agent.original",
    # Services
    "ServiceName": "service.name",
    "ServiceFileName": "service.executable",
    # Code signatures
    "Signed": "code_signature.signed",
    "Signature": "code_signature.subject_name",
    "SignatureStatus": "code_signature.status",
}

# Field key like "CommandLine" or "cs-uri-query|contains|base64offset".
# Field names allow letters, digits, underscore, dot, and hyphen (for W3C ELF
# style names such as `cs-method`).
_FIELD_KEY_RE = re.compile(r"^([A-Za-z0-9_.\-]+)((?:\|[a-z0-9_]+)*)$")

# Keys under `detection:` that are not selection blocks and must not be walked.
_NON_SELECTION_KEYS = frozenset({"condition", "timeframe"})


def _split_field_key(key: str) -> tuple[str, str]:
    """Split ``"Field|mod1|mod2"`` into ``("Field", "|mod1|mod2")``.

    Returns the whole key as the field name and empty modifiers if the input
    doesn't match the expected shape (defensive — unusual keys pass through
    unchanged so the caller can decide what to do).
    """
    m = _FIELD_KEY_RE.match(key)
    if not m:
        return key, ""
    return m.group(1), m.group(2) or ""


def _convert_selection(
    node, mapping: dict[str, str], unmapped: list[str]
):
    """Recurse into a detection selection block or list of such blocks.

    Rewrites field-name keys via ``mapping`` while preserving Sigma modifiers.
    Any bare field not in the mapping is appended to ``unmapped``; the key is
    kept as-is (the caller decides to skip the rule based on ``unmapped``).
    Values are never modified in this stage.
    """
    if isinstance(node, dict):
        new_dict: dict = {}
        for k, v in node.items():
            if isinstance(k, str):
                bare, mods = _split_field_key(k)
                mapped = mapping.get(bare)
                if mapped is None:
                    unmapped.append(bare)
                    new_key = k
                else:
                    new_key = f"{mapped}{mods}"
                new_dict[new_key] = _convert_selection(v, mapping, unmapped)
            else:
                new_dict[k] = _convert_selection(v, mapping, unmapped)
        return new_dict
    if isinstance(node, list):
        return [_convert_selection(item, mapping, unmapped) for item in node]
    return node


def convert_payload_to_ecs(
    payload_yaml: str,
    mapping: Optional[dict[str, str]] = None,
) -> tuple[Optional[str], list[str]]:
    """Convert a Sigma rule YAML payload's detection block to ECS field names.

    Args:
        payload_yaml: The raw Sigma rule YAML text.
        mapping: Field-name mapping to use. Defaults to :data:`RAW_TO_ECS`.

    Returns:
        ``(converted_yaml, [])`` if every field in every selection block is in
        the mapping, otherwise ``(None, [unique_unmapped_field_names])``. The
        list is de-duplicated and sorted for stable output.

        On YAML parse failure returns ``(None, ["<yaml-parse-error>"])``.
        On missing/malformed detection block returns
        ``(None, ["<no-detection>"])``.
    """
    if mapping is None:
        mapping = RAW_TO_ECS

    try:
        parsed = yaml.safe_load(payload_yaml)
    except yaml.YAMLError:
        return None, ["<yaml-parse-error>"]

    if not isinstance(parsed, dict):
        return None, ["<invalid-root>"]

    detection = parsed.get("detection")
    if not isinstance(detection, dict):
        return None, ["<no-detection>"]

    unmapped: list[str] = []
    new_detection: dict = {}
    for k, v in detection.items():
        if k in _NON_SELECTION_KEYS:
            new_detection[k] = v
        else:
            new_detection[k] = _convert_selection(v, mapping, unmapped)

    if unmapped:
        return None, sorted(set(unmapped))

    parsed["detection"] = new_detection
    return (
        yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True),
        [],
    )


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
