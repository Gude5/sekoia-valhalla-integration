# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Removed
- **Breaking**: `sync-sigma-intelligence-center` trigger removed. The
  Intelligence Center path never went beyond an initial experiment; the
  Rules Catalog path (`sync-sigma-rules-catalog`) is the sole supported
  destination for Valhalla Sigma rules. Playbooks that referenced the
  removed trigger will fail to load on redeploy — migrate them to
  `sync-sigma-rules-catalog`.
- The supporting `sekoia_valhalla_integration_modules.stix` helper module
  (STIX object construction, only used by the removed trigger) is
  deleted along with its test file.

### Added
- Test `test_updated_content_reaches_put_body` covering the update
  path end-to-end: sync #1 seeds the id-map, the rule's content changes
  on the feed, sync #2 must PUT the stored sekoia_uuid with a body that
  reflects the new content. Closes a coverage gap — prior tests only
  counted PUT calls without inspecting the body or target UUID.
- New mapping `IsatapRouter` → `winlog.event_data.IsatapRouter`, closing
  the `windows/-/system` gap in the v0.3.1 field-acceptance probe.
  Follows the standard `winlog.event_data.*` passthrough pattern already
  used for 22 other Windows Security fields.
- (Considered and dropped: an AWS CloudTrail `requestParameters.*`
  transform rewriting nested Sigma keys into substring matches on the
  `aws.cloudtrail.flattened.request_parameters` JSON blob Sekoia's
  parser stores. A live count against the demo Valhalla feed showed
  only 4 rules reference `requestParameters.*` — 2 fully convertible,
  2 with unsupported shapes — so the yield didn't justify the code.
  Left a note on the AWS CloudTrail block in `ecs_field_maps.py` for
  future maintainers.)
- **RAW_TO_ECS_CUSTOM expanded from 32 to 68 entries**, targeting the
  highest-count unmapped fields from the live-feed histogram. New
  additions:
  - **Windows Security event_data** (~22 fields → `winlog.event_data.*`):
    `Data`, `ObjectName`, `ObjectType`, `RelativeTargetName`, `Status`,
    `ShareName`, `AccessMask`, `OpNum`, `AccessList`, `NewValue`,
    `AttributeLDAPDisplayName`, `AttributeValue`, `TaskName`, `Category`,
    `Contents`, `Configuration`, `ContextInfo`, `AuthenticationPackageName`,
    `ModifyingApplication`, `Level`, `Path`.
  - **Auditd extras**: `a2`, `a3`, `a4` → `auditd.data.a{2,3,4}`.
  - **Kubernetes dotted forms**: `objectRef.resource/namespace/name/apiGroup/subresource`
    → `kubernetes.audit.objectRef.*` (rules often use the fully-qualified
    dotted form directly).
  - **Cloud**: `eventType`/`EventType`/`OperationName` → `event.action`;
    `AuthenticationRequirement` and `ResultType` → Azure sign-in
    properties; `auditType.action`/`auditType.category` → Google Workspace
    event fields.
- `_ECS_PASSTHROUGH_FIELDS` now includes `gcp.audit.method_name`
  (and three related GCP audit fields) — Sigma rules that already write
  these in ECS form pass through untouched.
- `Signature` promoted from `CONTEXT_AWARE_FIELDS` to `RAW_TO_ECS_CUSTOM`
  as a static mapping. SigmaHQ's pipeline gates it on `driver_loaded`/
  `image_loaded` categories, but both variants map to the same ECS
  target — collapsing to static preserves that behaviour and adds a
  fallback for rules outside those categories.
- Removed redundant `QueryName` from CUSTOM (already in SigmaHQ Windows).

### Changed
- **ECS field-mapping tables moved out of `sigma_mapper` into a new
  `ecs_field_maps` module.** Split is data/logic: the four SigmaHQ
  pipeline dicts (`RAW_TO_ECS_SIGMAHQ_WINDOWS/MACOS/ZEEK/KUBERNETES`),
  `RAW_TO_ECS_CUSTOM`, the merge helpers (`_strip_caseless`,
  `_merge_sigmahq`), the merged runtime `RAW_TO_ECS`,
  `CONTEXT_AWARE_FIELDS`, and `_ECS_PASSTHROUGH_FIELDS` all live in
  `ecs_field_maps.py`. `sigma_mapper.py` drops from ~1200 lines to
  ~410 and keeps only the small constants (`SEVERITY_MAP`,
  `STATUS_EFFORT_MAP`, `TAG_ALERT_UUID_MAP`, `MARKER_TAG`, size
  limits) alongside the conversion functions. Test imports that
  referenced the pipeline dicts by name now target
  `ecs_field_maps` directly; `RAW_TO_ECS` remains reachable via
  `sigma_mapper` as a re-export. No behavior change.
- `tests/` is no longer excluded from the pushed repo (was under the
  dev-only section of `.gitignore`). Sekoia's importer ignores the
  directory at runtime; shipping it makes CI-side verification and
  external review possible without a separate checkout.
- **Sync trigger parses each rule's YAML once** (previously twice — once
  in `_rule_passes_filter`, once in `convert_payload_to_ecs`). Extracted
  `convert_parsed_to_ecs(parsed: dict, ...)` in `sigma_mapper` as the
  core dict-accepting function; `convert_payload_to_ecs(yaml_str, ...)`
  remains as a thin YAML-parsing wrapper, kept for the test suite.
  `_rule_passes_filter` now takes a parsed dict.
- Malformed-YAML rules are no longer silently dropped by the filter;
  they are counted under `skipped_unmapped` with a `<yaml-parse-error>`
  bucket in `top_unmapped`, matching how the ECS converter already
  handled the same case.
- Renamed `STATUS_TO_EFFORT` → `STATUS_EFFORT_MAP` and dropped the
  separate `STATUS_RANK` dict. The sync trigger's status filter now
  uses effort directly (lower effort = higher maturity, so the
  comparison is inverted vs the old rank-based version). The trigger's
  internal attribute renamed `_min_status_rank` → `_max_status_effort`.
  No user-facing config change; `min_sigma_status` still accepts the
  same values.
- `DEFAULT_EFFORT` changed from `2` → `3` (used when a Sigma rule has
  no `status` field; filter never accepts such rules, so this only
  affects the `effort` value written on rules imported via non-filter
  paths).
- Renamed `TAG_TO_ALERT_UUID` → `TAG_ALERT_UUID_MAP`.
- Renamed the local counter `skipped_filter` → `filtered_out` in the
  sync loop, and updated the summary log label to match. The JSON
  event field `"skipped_filter"` is unchanged (downstream contract).
- **ECS field mappings rebased on SigmaHQ pySigma-backend-elasticsearch
  pipelines as source of truth.** The single `RAW_TO_ECS` dict is
  replaced by five: `RAW_TO_ECS_SIGMAHQ_WINDOWS` (72 entries copied
  verbatim from `windows.py`), `RAW_TO_ECS_SIGMAHQ_MACOS` (46 from
  `macos.py`), `RAW_TO_ECS_SIGMAHQ_ZEEK` (405 from `zeek.py`'s
  `ecs_zeek_beats()` variant), `RAW_TO_ECS_SIGMAHQ_KUBERNETES` (9 from
  `kubernetes.py`), plus `RAW_TO_ECS_CUSTOM` (68 bespoke entries for
  fields SigmaHQ doesn't cover — AWS CloudTrail, Azure logs, Linux
  auditd, Windows Security event_data, IIS/W3C-ELF `cs-*`, Google
  Workspace, Kubernetes dotted paths, `TargetImage`/`IntegrityLevel`/
  `ServiceName`, `SubjectUserName`, `userAgent`, `Signature`). Merged
  via `setdefault`: Windows first (majority-use Sigma product), CUSTOM
  second (overrides macOS defaults for shared fields like `TargetImage`),
  then macOS/Zeek/K8s to fill remaining gaps. Runtime map has 579
  entries — up from ~90. Adopts SigmaHQ's
  `.caseless` targets but strips the suffix at merge time since
  Sekoia's ECS schema doesn't expose those sub-fields.
- **Context-aware branch extended** from the previous single
  `TARGET_OBJECT_BY_CATEGORY` to a general
  `CONTEXT_AWARE_FIELDS: dict[str, dict[str, str]]`. Adds SigmaHQ's
  Windows PE-metadata fields (`Description`, `Product`, `Company`,
  `OriginalFileName`, `FileVersion` route to `process.pe.*` for
  `process_creation` and `file.pe.*` for `image_load`), the
  `sysmon_error` third-branch for `Description`, plus `Signature`
  (driver/image loaded → `file.code_signature.subject_name`) and
  `Initiated`/`Protocol` (network_connection only). `_resolve_field`
  consults this dict before the flat map.
- **Breaking**: `alert_type_uuid` config field is removed from the
  `sync-sigma-rules-catalog` trigger. Each rule's `alert_type_uuid` is
  now auto-derived from the rule's Sigma MITRE tactic tags via a
  priority-ordered map (`attack.exfiltration` → `exfiltration`,
  `attack.command-and-control` → `c&c`, `attack.persistence` →
  `backdoor`, `attack.initial-access` → `exploit`, `attack.discovery` /
  `attack.reconnaissance` → `appscan`, everything else →
  `application-compromise`). UUIDs are hardcoded (the Sekoia Ecsirt
  taxonomy uses stable UUIDs across tenants). No user configuration
  needed; playbooks that previously set `alert_type_uuid` silently
  ignore the value on redeploy.
- `related_object_refs` is no longer sent in the Rules Catalog POST
  body. Sigma's `related[].id` values are Sigma-world UUIDs that don't
  correspond to any rule in the Sekoia tenant, so shipping them just
  created dangling references. Same reasoning as `community_uuid`.
- `min_sigma_level` and `min_sigma_status` are declared with plain
  `enum` (so Sekoia's form renderer displays them as dropdowns) plus
  `enumNames` mirroring the enum values so renderers that honour the
  react-jsonschema-form convention display the lowercase labels
  literally. Reverts an earlier `oneOf`-based experiment that gave
  correct labels but broke the dropdown rendering.
- `sync-sigma-rules-catalog` trigger now attaches a marker tag
  (`valhalla-integration`, exported as `sigma_mapper.MARKER_TAG`) to
  every rule it POSTs. The tag survives Sekoia API-key rotations and
  gives the delete trigger a stable discriminator independent of the
  volatile `created_by` field.
- `delete-catalog-rules` trigger has a new default **tag mode**:
  filters by the marker tag instead of `created_by`. New config
  `marker_tag` (default `valhalla-integration`). Setting it to empty
  falls back to the existing field-based `match_field`/`match_value`
  mode, useful for cleaning up rules that predate the marker tag.
  Summary event now carries `marker_tag`; the zero-match diagnostic in
  tag mode logs a histogram of tag names observed
  (`observed_tags`).
- `sync-sigma-rules-catalog` trigger gained two dropdown configs:
  `min_sigma_level` (default `informational`) and `min_sigma_status`
  (default `experimental`). Rules whose Sigma `level` is below the
  configured minimum (order: informational < low < medium < high <
  critical) or whose `status` is below the configured minimum (order:
  experimental < test < stable) are skipped. Sigma statuses
  `deprecated` and `unsupported` are not selectable in the UI and are
  never imported. Rules **missing** either the `level` or `status`
  field are always skipped, regardless of the thresholds. Filter hits
  are counted in the new `skipped_filter` counter on the summary event.
- `delete-catalog-rules` trigger's zero-match diagnostic now also logs
  the sample rule's field key set and a truncated JSON dump of the first
  rule. This exposes what fields the list endpoint actually returns, so
  operators can pick a real marker when the configured field turns out to
  be unpopulated (or absent from the list response).

- `delete-catalog-rules` trigger's filter is now generic: two config fields
  `match_field` (default `created_by`) and `match_value` (default empty).
  When `match_value` is empty the trigger runs in diagnostic-only mode and
  logs the top values observed for `match_field` in the tenant, so
  operators can spot their API key's UUID (visible as `created_by` on
  every rule the sync trigger created) without leaving Sekoia. Prior
  `author`-based filter is dropped because Sekoia's list endpoint doesn't
  return an `author` field. Summary event fields renamed from `author` →
  `match_field`+`match_value`; observed histogram now under
  `observed_<field>` (e.g. `observed_created_by`).
- `delete-catalog-rules` trigger no longer depends on a local id-map (which
  isn't visible across Sekoia's per-trigger persistent volumes). It now
  enumerates the Sekoia Rules Catalog via
  `GET /v1/sic/conf/rules-catalog/rules`, handles pagination, and filters
  rules by the configured field. Server-side filter is passed as
  `match[<field>]=<value>`; a client-side filter is applied as a safety
  net so we never delete a rule whose field doesn't match.
- SekoiaClient's `iter_rules` signature is now
  `iter_rules(match_field=None, match_value=None, page_size=100)`.
- **Breaking**: The module-level `base_url` (Valhalla) config field is
  removed. The Valhalla API URL is now hardcoded to
  `https://valhalla.nextron-systems.com` in the client
  (`VALHALLA_BASE_URL`). Existing playbooks whose module config sets
  `base_url` will silently ignore the value on redeploy; there is
  nothing to migrate.

- **Breaking**: `delete-catalog-rules` is now a **Trigger**, not an Action.
  Playbooks that invoked the action step must be replaced by enabling the
  new trigger with `confirm=true` in its configuration. Runs the cleanup
  once on start (deletes every rule the sync trigger created, identified
  via the local id-map), emits a summary event
  (`valhalla-sigma-catalog-delete`), then idles on a configurable interval
  (`frequency`, default 24h). Subsequent runs are cheap no-ops after the
  first pass empties the id-map. Same safety default: `confirm=false` is
  dry-run-only, no API calls.

### Fixed
- `description` is truncated to Sekoia's 1000-character API limit before
  POSTing. Rules whose Sigma description exceeds 1000 chars (a small tail
  — one rule against the full Valhalla feed) were previously rejected
  with `HTTP 400 VA301 String should have at most 1000 characters`; they
  are now truncated with a `…` suffix, mirroring the existing 100-char
  `name` truncation.
- `community_uuid` is no longer sent in the Rules Catalog POST body.
  Setting it in combination with other metadata fields (`tags`,
  `description`, `false_positives`) triggered Sekoia's AU202 scope
  check on every rule (an arbitrary Valhalla rule ID isn't a valid
  reference into Sekoia's community catalog, and attaching a rule to
  such a reference requires a permission we don't hold). Sekoia was
  also silently overriding our value with its own default
  (`4039e5c6-…`) on the rules that did get through, so the field was
  never functional anyway. Every field-level bisect against a live
  tenant confirmed the AU202 was gated on the presence of
  `community_uuid`.
- `sync-sigma-rules-catalog` trigger now self-heals stale id-map entries.
  When Sekoia returns HTTP 403 (code AU202) or 404 on a PUT — indicating
  the target UUID no longer exists for this API key (usually because the
  tenant was cleaned up via `delete-catalog-rules`) — the trigger drops
  the entry from the local map and POSTs the rule as new. Previously
  every stale entry counted as a hard failure, and the map had to be
  wiped manually before rules could be reimported. SekoiaClient gained a
  new `SekoiaRuleNotFoundError` exception (subclass of `SekoiaAPIError`)
  raised on 403/404 from `update_rule`; `SekoiaAPIError` also now
  carries the HTTP `status_code` on the exception object.
- `datasources` is no longer sent in the Rules Catalog POST body. Sekoia's
  schema expects a list of tenant-registered data-source **UUIDs**, not
  the free-form Sigma `logsource` dict. Previously every rule with a
  `logsource:` block was rejected with
  `HTTP 400 VA301 — UUID input should be a string, bytes or UUID object`
  at `datasources[0]`. The Sigma logsource metadata remains visible in
  the payload YAML if needed downstream; mapping to Sekoia data-source
  UUIDs would require a tenant-specific lookup we can't derive from Sigma.
- `related_object_refs` is now shipped as a list of UUID strings
  (extracted from each Sigma `related` entry's `id` field), matching
  Sekoia's expected list-of-UUIDs shape. Sigma's `related` entries are
  dicts of `{id, type}`; only the UUID `id` is forwarded. Rules whose
  `related` entries have no `id` no longer ship the field.

- Module-level configuration: `api_key` (Valhalla, defaults to the public demo
  key), `base_url` (Valhalla, defaults to https://valhalla.nextron-systems.com),
  `sekoia_api_key` (Sekoia bearer token), `sekoia_base_url` (Sekoia API,
  defaults to https://api.sekoia.io). `api_key` and `sekoia_api_key` are
  marked as secrets.
- Thin Valhalla HTTP client wrapping `POST /api/v1/getsigma`
  (form-encoded body, demo-key compatible).
- Thin Sekoia HTTP client for the Rules Catalog: bearer-auth
  `POST` / `PUT /v1/sic/conf/rules-catalog/rules`.
- Sigma-to-STIX converter (`pattern_type=sigma`, STIX 2.1 indicators bundled
  per pull, deterministic UUIDv5 indicator IDs).
- Sigma-to-Rules-Catalog mapper: parses the rule's YAML to derive `name`,
  `description`, severity (`level` → 20/30/40/70/90 mapping); falls back
  gracefully on malformed YAML.
- Trigger `sync-sigma-intelligence-center` — periodically pulls the Valhalla
  Sigma feed, builds a STIX bundle, and emits it via `send_event` with a
  `bundle_path` for ingestion into the Sekoia Intelligence Center. Dedup
  state persisted in `valhalla-sigma-ic-seen.json` keyed on the Valhalla
  rule `id`.
- Trigger `sync-sigma-rules-catalog` — periodically pulls the Valhalla Sigma
  feed and POSTs each rule into the Sekoia Rules Catalog
  (`POST /v1/sic/conf/rules-catalog/rules`); subsequent pulls PUT to refresh
  existing rules. State map `valhalla_id → sekoia_uuid` persisted in
  `valhalla-sigma-catalog-uuid-map.json`. Rules land with `enabled=false` by
  default; configurable. Per-rule errors are logged and the sync continues.
- Both triggers run on a configurable interval (`frequency`, default 24h)
  via APScheduler `BlockingScheduler`.
- Sigma-to-ECS field-name converter (`convert_payload_to_ecs`) for the Rules
  Catalog trigger. Rewrites the `detection:` block of each rule from raw
  SigmaHQ field names (`CommandLine`, `Image`, `EventID`, `TargetFilename`,
  `ScriptBlockText`, `DestinationIp`, …) to their Elastic Common Schema
  equivalents (`process.command_line`, `process.executable`, `event.code`,
  `file.path`, `powershell.file.script_block_text`, `destination.ip`, …)
  before POSTing. Sigma field modifiers (`|contains`, `|endswith`, `|re`,
  `|base64offset`, chained combinations) are preserved. Rules that reference
  any field not in the current 30-entry mapping are skipped and their
  unmapped field names are aggregated into a `top_unmapped` telemetry
  histogram on the sync summary event. Measured yield against the Valhalla
  demo feed: ~62% of the ~3,591 rules convert successfully.
- Rules-Catalog sync summary event now carries `created`, `updated`,
  `failed`, `skipped_unmapped`, `total_rules`, and `top_unmapped` — the last
  a map of `{field_name: count}` for the 20 most-common unmapped fields.
  Operators can use it to prioritise the next fields to add to the map.
- Extended the ECS field mapping with 12 more Sigma → ECS entries, informed
  by a category-acceptance probe against a live Sekoia tenant: PE metadata
  (`Description` → `file.pe.description`, `Product`, `Company`), Sysmon
  network direction (`Initiated`), Windows security target user
  (`TargetUserName`), and W3C-ELF web/proxy fields (`cs-method`, `cs-referer`,
  `cs-uri-query`, `cs-uri-stem`, `cs-uri`, `sc-status`, `userAgent`).
- Field-name parser now accepts hyphens (needed for W3C-ELF `cs-*` /
  `sc-*` fields when combined with Sigma modifiers such as `|contains`).
- Stage 2 converter additions:
  - **Context-aware `TargetObject`** — resolves to `registry.path` for
    Sigma rules with `logsource.category` in
    `registry_set`/`registry_add`/`registry_delete`/`registry_rename`/`registry_event`,
    and to `file.path` for `file_event`. Rules with unrecognised logsource
    contexts remain skipped.
  - **`Hashes` value split** — Sigma's `Hashes|contains: 'MD5=abc,SHA256=def'`
    (string or list form) is rewritten into individual
    `process.hash.md5`, `process.hash.sha1`, `process.hash.sha256`,
    `process.hash.sha512`, `process.hash.imphash` keys. Multi-value lists of
    a single algorithm are preserved as lists (OR-semantics intact);
    mixed-algo lists become AND-matched sibling keys (documented approximation).
    Unknown algorithms or malformed values cause the rule to be skipped.
- Added 24 more ECS field mappings, empirically confirmed by a
  candidate-mapping probe against a live Sekoia tenant:
  - AWS CloudTrail / Azure activity logs: `eventName` → `event.action`,
    `eventSource` → `event.provider`, `operationName` → `event.action`,
    `errorCode` → `aws.cloudtrail.error_code`, `properties.message` →
    `azure.activitylogs.properties.message`, `status` → `event.outcome`,
    `riskEventType` → `azure.signinlogs.properties.risk_event_type`.
  - Linux auditd: `SYSCALL`, `type`, `a0`, `a1`, `exe`, `cfgpath` → their
    `auditd.data.*` / `auditd.log.record_type` counterparts (`exe` collapses
    onto `process.executable`).
  - Windows Security event_data: `ObjectClass`, `ObjectDN`, `Details`,
    `LogonType`, `GrantedAccess`, `CallTrace`, `InterfaceUuid` land under
    the `winlog.event_data.*` namespace; `SubjectUserName` → `user.name`.
  - Web / proxy client-side (W3C ELF): `c-uri` → `url.original`,
    `c-useragent` → `user_agent.original`. DNS: `query` → `dns.question.name`.
- Known limitation: `type` and `status` are very generic Sigma field names.
  Rules that use them outside their expected context (auditd for `type`,
  Azure for `status`) will convert to a technically-valid ECS name that may
  not match intended events. Override on a per-tenant basis via
  `custom_field_mapping` (planned feature) if hit in practice.
- Truncate rule `name` to Sekoia's 100-character API limit before POSTing.
  Rules whose Sigma title exceeds 100 characters (e.g.
  `CVE-2023-1389 Potential Exploitation Attempt - Unauthenticated Command
  Injection In TP-Link Archer AX21`) were previously rejected with
  `HTTP 400 VA301`; they are now truncated with a `…` suffix so operators
  can still recognise the source rule.
- **Rules Catalog POST body restructured** to fit Sekoia's structured
  schema: the `payload` field now carries **only** the ECS-converted
  `detection:` block (YAML-serialised, `detection:` keyword preserved).
  Sigma metadata that used to live inside the payload YAML is now lifted
  into individual Sekoia top-level fields:
  - `name` ← Sigma `title` (100-char truncation preserved)
  - `description` ← Sigma `description`
  - `severity` ← Sigma `level`, remapped: `informational=10`, `low=30`,
    `medium=50`, `high=70`, `critical=90`, missing level → `0`
  - `effort` ← Sigma `status`: `stable=1`, `test=2`, `experimental=3`,
    `unsupported=4`, `deprecated=4`, missing status → `2` (test)
  - `community_uuid` ← Valhalla rule `id` (optional; only shipped when set)
  - `tags` ← Sigma `tags` list (optional)
  - `datasources` ← Sigma `logsource` dict (optional)
  - `related_object_refs` ← Sigma `related` list (optional)
  - `false_positives` ← Sigma `falsepositives` list, joined with newlines
    (optional)
  - `type` unchanged (`"sigma"`)
- Optional fields are omitted entirely from the POST body when the source
  Sigma rule doesn't carry the corresponding data.
- `convert_payload_to_ecs()` now returns the parsed rule dict directly
  (with an ECS-converted `detection` block) instead of a re-serialised
  YAML string. The trigger and any other caller must adjust accordingly.
- New Action **`delete-catalog-rules`** — on-demand cleanup that deletes
  every rule the `sync-sigma-rules-catalog` trigger created in the tenant,
  identified via the persisted `valhalla_id → sekoia_uuid` map. Never touches
  user-created custom rules or Sekoia's verified catalog. Defaults to
  dry-run: `confirm=false` returns a report of what WOULD be deleted; set
  `confirm=true` in the playbook arguments to actually delete. Successful
  deletes are removed from the local state map, so the next sync run
  POSTs (rather than PUTs) every rule. Sekoia returning 404 on a DELETE is
  treated as idempotent success.
- SekoiaClient gained a `delete_rule(sekoia_uuid)` method wrapping
  `DELETE /v1/sic/conf/rules-catalog/rules/<uuid>`.
- Test suite covers the Valhalla client, Sekoia client (including the new
  delete method), the STIX converter, the Sigma mapper (ECS converter +
  Stage 2 extensions), both triggers, and the new delete action end-to-end
  with mocked destinations.
