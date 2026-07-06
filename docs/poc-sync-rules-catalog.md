# POC — Valhalla Sigma → Sekoia Rules Catalog

## How it works

The POC is a Sekoia automation module that pulls the Nextron Valhalla Sigma
feed and pushes each rule into the tenant's **Rules Catalog**, where
Sekoia's detection engine can compile and run it.

The `sync-sigma-rules-catalog` trigger fires on a configurable interval
(default 24h). Each run:

1. **Fetch.** `POST /api/v1/getsigma` against Valhalla with an API key
   returns the community Sigma feed (~3,600 rules).
2. **Filter.** Rules whose Sigma `level` or `status` is below the
   configured threshold (`min_sigma_level`, `min_sigma_status`) are
   skipped. Rules missing either field are also skipped.
3. **Convert.** Every remaining rule is split in two:
   - **Metadata → structured JSON:** Sigma `title`, `description`, `level`,
     `status`, `tags`, `falsepositives`, `related` are lifted to top-level
     Sekoia fields (`name`, `description`, `severity`, `effort`, `tags`,
     `false_positives`, `related_object_refs`). Length caps enforced
     (name 100 chars, description 1000 chars, truncated with `…`). A
     synthetic marker tag `valhalla-integration` is appended so the
     delete trigger can identify our rules independently of the API key
     that created them.
   - **Detection block → ECS field names:** raw SigmaHQ keys inside
     `detection:` (`CommandLine`, `EventID`, `TargetFilename`, …) are
     renamed to their Elastic Common Schema counterparts
     (`process.command_line`, `event.code`, `file.path`, …), because
     Sekoia's engine validates the block against ECS. Sigma field
     modifiers (`|contains`, `|endswith`, …) are preserved.
4. **Push.** Each rule is POSTed to
   `/v1/sic/conf/rules-catalog/rules` on first sight; subsequent runs PUT
   to the same UUID. A local id-map (`valhalla_id → sekoia_uuid`)
   distinguishes the two paths and self-heals stale entries (Sekoia
   returns HTTP 403 for deleted UUIDs; the trigger drops them and POSTs
   fresh).

Cleanup is a separate `delete-catalog-rules` trigger that enumerates
the tenant's Rules Catalog and deletes every rule carrying the marker
tag. A field-based fallback (`match_field`/`match_value`) is available
for cleaning up rules that predate the marker (e.g., imported by an
older version of the integration).

Config lives in two places: the module-level integration (Valhalla API
key, Sekoia URL + API key — the Valhalla URL is hardcoded) and the
trigger-level playbook (alert type UUID, on-push enabled flag,
frequency, plus the `min_sigma_level` / `min_sigma_status` filters
that gate which rules from the feed are imported).

Yield against the live Valhalla demo feed: **2,961 / 3,591 rules
(~82.5%)** import cleanly, `failed=0`.

## What's missing

- **~630 rules skipped** — their detection blocks reference Sigma field
  names the ECS map doesn't cover yet (top offenders: `Data`,
  `ObjectName`, `Payload`, `logtype`, `action`). Expanding
  `RAW_TO_ECS` is the highest-yield improvement.
- **No `datasources` linkage.** Sigma `logsource` (`{product, category}`)
  is dropped because Sekoia expects tenant-registered data-source UUIDs
  we can't derive.
- **No `community_uuid`.** Setting an arbitrary Valhalla ID trips
  Sekoia's AU202 scope check; the value is silently overridden anyway.
- **Rules land disabled.** Operators opt-in per rule in the Sekoia UI —
  no auto-enable path.
- **Sigma correlation rules unsupported.** Multi-rule correlations
  aren't handled by the converter and would land malformed.
- **Rules Catalog only.** Sync to the Intelligence Center is a separate
  trigger; delete/cleanup a third.

## See also

- [mapping-metadata.md](mapping-metadata.md) — Sigma → Sekoia JSON body fields
- [mapping-ecs.md](mapping-ecs.md) — SigmaHQ → ECS field-name conversions
