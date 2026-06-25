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
- Test suite (33 tests) covering the Valhalla client, Sekoia client, the STIX
  converter, the Sigma mapper, and both triggers end-to-end with mocked
  destinations.
