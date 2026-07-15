# ECS field-name mapping — SigmaHQ → Elastic Common Schema

Sekoia's detection engine validates the `detection:` block against its
ECS-based event schema. Raw SigmaHQ field names like `CommandLine` or
`EventID` are rejected with `HTTP 400 RUL143 "not a valid ECS field"`.
Before POSTing a rule, the sync trigger walks every key in the
`detection:` block and renames it via the mappings below.

Rules that reference any field NOT in the mapping (or a Stage-2 branch)
are skipped — their unmapped field names roll up into the
`top_unmapped` histogram on the sync summary event.

Implementation: [`convert_payload_to_ecs()`](../sekoia_valhalla_integration_modules/sigma_mapper.py)
in `sigma_mapper.py`. Sigma field modifiers (`|contains`, `|endswith`,
`|re`, `|base64offset`, chained combinations) are preserved on the
ECS-renamed field.

## Provenance

The mapping is split into five source dicts. Precedence highest-first:

| # | Dict                              | Source                                                                                                | Entries |
|---|-----------------------------------|-------------------------------------------------------------------------------------------------------|---------|
| 1 | `RAW_TO_ECS_SIGMAHQ_WINDOWS`      | [SigmaHQ pySigma-backend-elasticsearch `windows.py`](https://github.com/SigmaHQ/pySigma-backend-elasticsearch/blob/main/sigma/pipelines/elasticsearch/windows.py) static `field_mappings` block | 72      |
| 2 | `RAW_TO_ECS_CUSTOM`               | Bespoke — fields SigmaHQ doesn't cover (AWS CloudTrail, Azure logs, Linux auditd, Windows Security event_data, IIS/W3C ELF cs-*, Google Workspace, Kubernetes dotted paths, `TargetImage`, `Signature`, etc.) | 68      |
| 3 | `RAW_TO_ECS_SIGMAHQ_MACOS`        | [SigmaHQ `macos.py`](https://github.com/SigmaHQ/pySigma-backend-elasticsearch/blob/main/sigma/pipelines/elasticsearch/macos.py) `field_mappings` (ESF)                                            | 46      |
| 4 | `RAW_TO_ECS_SIGMAHQ_ZEEK`         | [SigmaHQ `zeek.py`](https://github.com/SigmaHQ/pySigma-backend-elasticsearch/blob/main/sigma/pipelines/elasticsearch/zeek.py) `ecs_zeek_beats()` pipeline (Filebeat ≥ 7.6.1) | 405     |
| 5 | `RAW_TO_ECS_SIGMAHQ_KUBERNETES`   | [SigmaHQ `kubernetes.py`](https://github.com/SigmaHQ/pySigma-backend-elasticsearch/blob/main/sigma/pipelines/elasticsearch/kubernetes.py) audit-log pipeline                                    | 9       |

Merged into the runtime `RAW_TO_ECS` (**579** entries) via
`setdefault` — the first dict to define a source field wins. Windows
wins over macOS/Zeek on shared names because Valhalla's feed is
majority Windows. Custom sits between Windows and the rest so we can
override macOS-specific targets for fields that Windows uses too
(e.g. `TargetImage` — macOS pipeline maps to `target.process.executable`;
CUSTOM keeps it at `process.executable` for Windows Sigma rules).

### `.caseless` sub-fields

SigmaHQ's Windows and macOS pipelines target `.caseless` multi-fields
(e.g. `process.executable.caseless`) for case-insensitive matches.
Sekoia's ECS schema doesn't expose those sub-fields, so the merge
strips the suffix and ships the base field
(`process.executable`). This is a deliberate departure — see
`_strip_caseless()`. If Sekoia ever adds `.caseless` support, remove
the strip.

### Zeek scope

Only the **`ecs_zeek_beats`** variant is adopted (Filebeat ≥ 7.6.1).
The Corelight and raw-JSON variants are skipped. During extraction:

- Wildcard targets (containing `*`, e.g. `zeek.*.arg`) are dropped —
  they're not usable as literal ECS field names.
- List targets (e.g. `dst: [destination.address, destination.ip]`)
  collapse to the last element, which is usually the more ECS-canonical
  choice.

## Context-aware branches

`CONTEXT_AWARE_FIELDS` is consulted **before** `RAW_TO_ECS`. Any field
listed here bypasses the flat lookup and resolves via
`logsource.category`. If the rule's category isn't listed for that
field, the rule is treated as unmapped and skipped.

### `TargetObject` — bespoke (Sigma convention)

| `logsource.category` | ECS field       |
|----------------------|-----------------|
| `registry_set`       | `registry.path` |
| `registry_add`       | `registry.path` |
| `registry_delete`    | `registry.path` |
| `registry_rename`    | `registry.path` |
| `registry_event`     | `registry.path` |
| `file_event`         | `file.path`     |

### PE metadata — SigmaHQ `ecs_windows_variable_mappings`

SigmaHQ routes these fields differently depending on whether the rule
is a process_creation (target = executing process) vs. image_load
(target = the DLL/file being loaded).

| Sigma field         | `process_creation`               | `image_load`                     | Other        |
|---------------------|----------------------------------|----------------------------------|--------------|
| `Description`       | `process.pe.description`         | `file.pe.description`            | `sysmon_error` → `winlog.event_data.Description` |
| `Product`           | `process.pe.product`             | `file.pe.product`                | —            |
| `Company`           | `process.pe.company`             | `file.pe.company`                | —            |
| `OriginalFileName`  | `process.pe.original_file_name`  | `file.pe.original_file_name`     | —            |
| `FileVersion`       | `process.pe.file_version`        | `file.pe.file_version`           | —            |

### Network — SigmaHQ

| Sigma field | `logsource.category`  | ECS field           |
|-------------|-----------------------|---------------------|
| `Initiated` | `network_connection`  | `network.direction` |
| `Protocol`  | `network_connection`  | `network.transport` |

## Value transforms

### `Hashes` — value split by algorithm

Sigma stores hashes as `ALGO=DIGEST` in a single field
(`Hashes|contains: "MD5=abc,SHA256=def"`). The converter parses these
into per-algorithm ECS keys:

| Detected algorithm (`ALGO=…`) | ECS field                |
|-------------------------------|--------------------------|
| `MD5`                         | `process.hash.md5`       |
| `SHA1`                        | `process.hash.sha1`      |
| `SHA256`                      | `process.hash.sha256`    |
| `SHA512`                      | `process.hash.sha512`    |
| `IMPHASH`                     | `process.hash.imphash`   |

Semantics:
- Multi-value lists of a single algorithm are preserved as lists
  (OR-semantics intact).
- Mixed-algorithm lists become AND-matched sibling keys (documented
  approximation of the OR semantics — see source comments).
- Unknown algorithms or malformed values cause the rule to be **skipped**.

Recognised algorithms: `_HASH_ALGOS = {"md5", "sha1", "sha256", "sha512", "imphash"}`.

## Skip semantics

A rule is skipped when its `detection:` block contains **any** field
that:

- doesn't hit `CONTEXT_AWARE_FIELDS` (or hits it with a non-matching
  category), AND
- isn't already in `_ECS_PASSTHROUGH_FIELDS` (Stage 2 output shape),
  AND
- isn't a key in the merged `RAW_TO_ECS`.

Every unmapped bare field name is aggregated into the `top_unmapped`
histogram on the sync summary event. The 20 most-common values are
surfaced so operators know which entries to add next (in `RAW_TO_ECS_CUSTOM`
— never in the SigmaHQ dicts, which are read-only mirrors).
