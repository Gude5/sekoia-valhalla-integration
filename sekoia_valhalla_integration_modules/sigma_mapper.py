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
# Schema. Covers the ~34 most-frequent Windows/network/web fields in the
# Valhalla feed. Extended in Stage 2 with context-aware branches for
# ``TargetObject`` and value-splitting for ``Hashes``.
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
    # Cloud events (AWS CloudTrail / Azure activity logs — Sekoia also
    # accepts source-specific extensions like `aws.cloudtrail.event_name`,
    # but ECS-native fields work for both sources and keep the map small.
    # Revisit if source-specific enrichment becomes important.)
    "eventName": "event.action",
    "eventSource": "event.provider",
    "operationName": "event.action",
    "errorCode": "aws.cloudtrail.error_code",
    "properties.message": "azure.activitylogs.properties.message",
    "status": "event.outcome",
    "riskEventType": "azure.signinlogs.properties.risk_event_type",
    # Linux auditd
    "SYSCALL": "auditd.data.syscall",
    "type": "auditd.log.record_type",
    "a0": "auditd.data.a0",
    "a1": "auditd.data.a1",
    "exe": "process.executable",
    "cfgpath": "auditd.data.cfgpath",
    # Windows Security event_data — Sekoia accepts these as-is under the
    # `winlog.event_data.*` namespace, preserving the original field name.
    "ObjectClass": "winlog.event_data.ObjectClass",
    "ObjectDN": "winlog.event_data.ObjectDN",
    "Details": "winlog.event_data.Details",
    "SubjectUserName": "user.name",
    "LogonType": "winlog.event_data.LogonType",
    "GrantedAccess": "winlog.event_data.GrantedAccess",
    "CallTrace": "winlog.event_data.CallTrace",
    "InterfaceUuid": "winlog.event_data.InterfaceUuid",
    # Web / proxy client-side W3C ELF
    "c-uri": "url.original",
    "c-useragent": "user_agent.original",
    # DNS
    "query": "dns.question.name",
}

# Stage 2: ``TargetObject`` maps to different ECS paths depending on the
# rule's ``logsource.category``. Sigma convention: registry-family categories
# treat TargetObject as the registry key path; file_event uses it as a file
# path (rare but seen in the wild).
TARGET_OBJECT_BY_CATEGORY: dict[str, str] = {
    "registry_set": "registry.path",
    "registry_add": "registry.path",
    "registry_delete": "registry.path",
    "registry_rename": "registry.path",
    "registry_event": "registry.path",
    "file_event": "file.path",
}

# Fields produced by our own Stage 2 transforms (Hashes value split, etc.)
# that are already ECS-shaped and must pass through the walker untouched.
_ECS_PASSTHROUGH_FIELDS: frozenset[str] = frozenset(
    {
        "process.hash.md5",
        "process.hash.sha1",
        "process.hash.sha256",
        "process.hash.sha512",
        "process.hash.imphash",
        "registry.path",
        "file.path",
    }
)

# Sigma Hashes values look like ``ALGO=DIGEST``; recognised algorithms are
# folded to their ECS ``process.hash.<algo>`` counterpart.
_HASH_ALGOS: frozenset[str] = frozenset({"md5", "sha1", "sha256", "sha512", "imphash"})

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


def _resolve_field(
    bare: str,
    mapping: dict[str, str],
    logsource_category: Optional[str],
) -> Optional[str]:
    """Return the ECS field name for ``bare``, or ``None`` if unmapped.

    Handles Stage 2 context-dependent fields (currently ``TargetObject``)
    and lets Stage-2-produced ECS paths pass through unchanged.
    """
    if bare == "TargetObject":
        return TARGET_OBJECT_BY_CATEGORY.get(logsource_category or "")
    if bare in _ECS_PASSTHROUGH_FIELDS:
        return bare
    return mapping.get(bare)


def _parse_hash_values(value) -> Optional[list[tuple[str, str]]]:
    """Parse a Sigma ``Hashes`` value into ``[(algo_lower, digest), ...]``.

    Accepts either a single string like ``"MD5=abc,SHA256=def"`` or a list of
    such strings. Returns ``None`` if any value doesn't match ``ALGO=DIGEST``
    or the algo is unknown — signals the caller to skip the rule.
    """
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, list):
        candidates: list = []
        for item in value:
            if not isinstance(item, str):
                return None
            candidates.extend(item.split(","))
    else:
        return None

    result: list[tuple[str, str]] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if "=" not in candidate:
            return None
        algo, digest = candidate.split("=", 1)
        algo = algo.strip().lower()
        digest = digest.strip()
        if algo not in _HASH_ALGOS or not digest:
            return None
        result.append((algo, digest))
    return result or None


def _apply_hashes_transform(selection_dict: dict) -> Optional[dict]:
    """Rewrite a selection dict's ``Hashes|<mods>`` key into individual
    ``process.hash.<algo>|<mods>`` keys.

    Semantics note: if the original value is a list of mixed algos (e.g.
    ``[MD5=x, SHA256=y]``), Sigma treats them as OR-matched under the same
    key. This transform emits them as AND-matched sibling keys within the
    same dict, which is a known approximation — real-world Valhalla rules
    that use Hashes almost always list values of a single algo, where the
    approximation is exact (the split preserves OR because same-key lists
    remain lists).

    Returns:
        - The updated dict on success.
        - ``None`` if the ``Hashes`` value is malformed (caller marks rule
          as unmapped and skips it).
        - The input dict unchanged if no ``Hashes*`` key is present.
    """
    hashes_key = None
    for k in selection_dict.keys():
        if isinstance(k, str) and (k == "Hashes" or k.startswith("Hashes|")):
            hashes_key = k
            break
    if hashes_key is None:
        return selection_dict

    _, mods = _split_field_key(hashes_key)
    parsed = _parse_hash_values(selection_dict[hashes_key])
    if parsed is None:
        return None

    # Group digests by algo so lists collapse into a single ECS key.
    by_algo: dict[str, list[str]] = {}
    for algo, digest in parsed:
        by_algo.setdefault(algo, []).append(digest)

    new_dict: dict = {k: v for k, v in selection_dict.items() if k != hashes_key}
    for algo, digests in by_algo.items():
        key = f"process.hash.{algo}{mods}"
        new_dict[key] = digests[0] if len(digests) == 1 else digests
    return new_dict


def _convert_selection(
    node,
    mapping: dict[str, str],
    unmapped: list[str],
    logsource_category: Optional[str] = None,
):
    """Recurse into a detection selection block or list of such blocks.

    Applies the Hashes value transform (Stage 2), then rewrites field-name
    keys via ``mapping`` while preserving Sigma modifiers. Context-dependent
    fields (currently ``TargetObject``) resolve against ``logsource_category``.
    Any bare field not resolvable is appended to ``unmapped``; the key is
    kept as-is (the caller decides to skip the rule).
    """
    if isinstance(node, dict):
        transformed = _apply_hashes_transform(node)
        if transformed is None:
            unmapped.append("Hashes")
            transformed = node  # keep going so we still surface other unmapped fields

        new_dict: dict = {}
        for k, v in transformed.items():
            if isinstance(k, str):
                bare, mods = _split_field_key(k)
                mapped = _resolve_field(bare, mapping, logsource_category)
                if mapped is None:
                    unmapped.append(bare)
                    new_key = k
                else:
                    new_key = f"{mapped}{mods}"
                new_dict[new_key] = _convert_selection(
                    v, mapping, unmapped, logsource_category
                )
            else:
                new_dict[k] = _convert_selection(
                    v, mapping, unmapped, logsource_category
                )
        return new_dict
    if isinstance(node, list):
        return [
            _convert_selection(item, mapping, unmapped, logsource_category)
            for item in node
        ]
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
        ``(converted_yaml, [])`` if every field in every selection block is
        resolvable, otherwise ``(None, [unique_unmapped_field_names])``. The
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

    logsource = parsed.get("logsource") or {}
    category = logsource.get("category") if isinstance(logsource, dict) else None

    unmapped: list[str] = []
    new_detection: dict = {}
    for k, v in detection.items():
        if k in _NON_SELECTION_KEYS:
            new_detection[k] = v
        else:
            new_detection[k] = _convert_selection(v, mapping, unmapped, category)

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
