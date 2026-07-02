# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added
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
- Test suite (122 tests) covering the Valhalla client, Sekoia client, the
  STIX converter, the Sigma mapper (including the new ECS converter and
  Stage 2 extensions), and both triggers end-to-end with mocked destinations.
