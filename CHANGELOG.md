# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added
- `delete-catalog-rules` trigger's zero-match diagnostic now also logs
  the sample rule's field key set and a truncated JSON dump of the first
  rule. This exposes what fields the list endpoint actually returns, so
  operators can pick a real marker when the configured field turns out to
  be unpopulated (or absent from the list response).

### Changed
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
