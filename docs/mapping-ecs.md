# ECS field-name mapping — SigmaHQ → Elastic Common Schema

Sekoia's detection engine validates the `detection:` block against its
ECS-based event schema. Raw SigmaHQ field names like `CommandLine` or
`EventID` are rejected with `HTTP 400 RUL143 "not a valid ECS field"`.
Before POSTing a rule, the sync trigger walks every key in the
`detection:` block and renames it via the mappings below.

Rules that reference any field NOT in the mapping (or a Stage-2 branch)
are skipped — their unmapped field names roll up into the
`top_unmapped` histogram on the sync summary event. Current yield
against the Valhalla demo feed: **2961 / 3591 = 82.5%**.

Implementation: [`convert_payload_to_ecs()`](../sekoia_valhalla_integration_modules/sigma_mapper.py) in `sigma_mapper.py`. Sigma
field modifiers (`|contains`, `|endswith`, `|re`, `|base64offset`, and
chained combinations) are preserved on the ECS-renamed field.

## Tier 1: direct 1:1 mappings

Defined in `RAW_TO_ECS`. Groupings mirror the source comments in the file.

### Process

| SigmaHQ            | ECS                                |
| ------------------ | ---------------------------------- |
| `Image`            | `process.executable`               |
| `CommandLine`      | `process.command_line`             |
| `OriginalFileName` | `process.pe.original_file_name`    |
| `ParentImage`      | `process.parent.executable`        |
| `ParentCommandLine`| `process.parent.command_line`      |
| `ProcessName`      | `process.name`                     |
| `CurrentDirectory` | `process.working_directory`        |
| `IntegrityLevel`   | `process.integrity_level`          |
| `User`             | `user.name`                        |
| `SourceImage`      | `process.executable`               |
| `TargetImage`      | `process.executable`               |

### Users

| SigmaHQ          | ECS                |
| ---------------- | ------------------ |
| `TargetUserName` | `user.target.name` |
| `SubjectUserName`| `user.name`        |

### Event metadata

| SigmaHQ         | ECS                    |
| --------------- | ---------------------- |
| `EventID`       | `event.code`           |
| `Provider_Name` | `winlog.provider_name` |
| `EventLog`      | `winlog.channel`       |

### Files / DLLs / pipes

| SigmaHQ          | ECS                       |
| ---------------- | ------------------------- |
| `TargetFilename` | `file.path`               |
| `ImageLoaded`    | `dll.path`                |
| `ImagePath`      | `process.executable`      |
| `PipeName`       | `file.name`               |

### PE metadata (Sysmon image_load)

| SigmaHQ       | ECS                    |
| ------------- | ---------------------- |
| `Description` | `file.pe.description`  |
| `Product`     | `file.pe.product`      |
| `Company`     | `file.pe.company`      |

### PowerShell

| SigmaHQ           | ECS                                     |
| ----------------- | --------------------------------------- |
| `ScriptBlockText` | `powershell.file.script_block_text`     |

### Network / DNS

| SigmaHQ               | ECS                    |
| --------------------- | ---------------------- |
| `DestinationIp`       | `destination.ip`       |
| `DestinationPort`     | `destination.port`     |
| `DestinationHostname` | `destination.domain`   |
| `SourceIp`            | `source.ip`            |
| `IpAddress`           | `source.ip`            |
| `QueryName`           | `dns.question.name`    |
| `query`               | `dns.question.name`    |
| `Initiated`           | `network.direction`    |

### Web / proxy — W3C ELF (server-side)

| SigmaHQ        | ECS                          |
| -------------- | ---------------------------- |
| `cs-method`    | `http.request.method`        |
| `cs-referer`   | `http.request.referrer`      |
| `cs-uri-query` | `url.query`                  |
| `cs-uri-stem`  | `url.path`                   |
| `cs-uri`       | `url.original`               |
| `sc-status`    | `http.response.status_code`  |
| `userAgent`    | `user_agent.original`        |

### Web / proxy — W3C ELF (client-side)

| SigmaHQ       | ECS                    |
| ------------- | ---------------------- |
| `c-uri`       | `url.original`         |
| `c-useragent` | `user_agent.original`  |

### Services

| SigmaHQ           | ECS                  |
| ----------------- | -------------------- |
| `ServiceName`     | `service.name`       |
| `ServiceFileName` | `service.executable` |

### Code signatures

| SigmaHQ           | ECS                            |
| ----------------- | ------------------------------ |
| `Signed`          | `code_signature.signed`        |
| `Signature`       | `code_signature.subject_name`  |
| `SignatureStatus` | `code_signature.status`        |

### Cloud events (AWS CloudTrail / Azure activity logs)

| SigmaHQ               | ECS                                                    |
| --------------------- | ------------------------------------------------------ |
| `eventName`           | `event.action`                                         |
| `eventSource`         | `event.provider`                                       |
| `operationName`       | `event.action`                                         |
| `errorCode`           | `aws.cloudtrail.error_code`                            |
| `properties.message`  | `azure.activitylogs.properties.message`                |
| `status`              | `event.outcome`                                        |
| `riskEventType`       | `azure.signinlogs.properties.risk_event_type`          |

### Linux auditd

| SigmaHQ   | ECS                        |
| --------- | -------------------------- |
| `SYSCALL` | `auditd.data.syscall`      |
| `type`    | `auditd.log.record_type`   |
| `a0`      | `auditd.data.a0`           |
| `a1`      | `auditd.data.a1`           |
| `exe`     | `process.executable`       |
| `cfgpath` | `auditd.data.cfgpath`      |

### Windows Security event_data

Sekoia accepts these as-is under the `winlog.event_data.*` namespace,
preserving the original field name.

| SigmaHQ         | ECS                              |
| --------------- | -------------------------------- |
| `ObjectClass`   | `winlog.event_data.ObjectClass`  |
| `ObjectDN`      | `winlog.event_data.ObjectDN`     |
| `Details`       | `winlog.event_data.Details`      |
| `LogonType`     | `winlog.event_data.LogonType`    |
| `GrantedAccess` | `winlog.event_data.GrantedAccess`|
| `CallTrace`     | `winlog.event_data.CallTrace`    |
| `InterfaceUuid` | `winlog.event_data.InterfaceUuid`|

## Tier 2: context-aware branches

### `TargetObject` — resolves by `logsource.category`

Sigma's convention: registry-family categories treat `TargetObject` as
the registry key path; `file_event` uses it as a file path (rare).
Rules with any other logsource category are **skipped** (`TargetObject`
returns `None` from `_resolve_field`).

| `logsource.category` | ECS field       |
| -------------------- | --------------- |
| `registry_set`       | `registry.path` |
| `registry_add`       | `registry.path` |
| `registry_delete`    | `registry.path` |
| `registry_rename`    | `registry.path` |
| `registry_event`     | `registry.path` |
| `file_event`         | `file.path`     |

Defined in `TARGET_OBJECT_BY_CATEGORY`.

### `Hashes` — value split by algorithm

Sigma stores hashes as `ALGO=DIGEST` in a single field
(`Hashes|contains: "MD5=abc,SHA256=def"`). The converter parses these
into per-algorithm ECS keys:

| Detected algorithm (`ALGO=…`) | ECS field                |
| ----------------------------- | ------------------------ |
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

## Fields that pass through untouched

Set `_ECS_PASSTHROUGH_FIELDS`. Used so a Stage-2 transform emitting an
already-ECS name doesn't re-trigger the mapping walk:

- `process.hash.md5` / `.sha1` / `.sha256` / `.sha512` / `.imphash`
- `registry.path`
- `file.path`

## Skipping behaviour

A rule is skipped when its `detection:` block contains **any** field
that:

- isn't a key in `RAW_TO_ECS`, AND
- doesn't hit a Stage-2 branch (`TargetObject` with matched logsource,
  or valid `Hashes` values), AND
- isn't already in `_ECS_PASSTHROUGH_FIELDS`.

Every unmapped bare field name is aggregated into the
`top_unmapped` histogram on the sync summary event. The 20 most-common
values are surfaced so operators know which entries to add next.
