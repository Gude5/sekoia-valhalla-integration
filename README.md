# Sekoia Valhalla Integration

Sekoia automation module that syncs the [Nextron Valhalla](https://valhalla.nextron-systems.com) Sigma rule feed into the [Sekoia](https://www.sekoia.io) Rules Catalog. Rules are pulled on a schedule, field names are rewritten from Sigma logsource conventions to Sekoia's ECS-based schema, and each rule is POSTed on first sight and PUT on subsequent syncs.

## Why use it

Sekoia's Rules Catalog does not ship a commercial Sigma feed as a first-party source. Valhalla is Nextron's catalog of Sigma and YARA rules. This integration feeds the Sigma half of it into Sekoia, where the rules run in the detection engine next to native Sekoia content — no hand-authoring, no importing rules one at a time.

Roughly 82% of the free community feed converts to executable Sekoia rules on the current mapping tables. The remainder either targets logsources with no clean ECS equivalent or uses context-ambiguous field names and is skipped rather than pushed in a broken state.

## Prerequisites

- Sekoia workspace with API access. Note your region — `https://api.sekoia.io` (FRA1) is the default; FRA2 / MCO1 / UAE1 use `https://app.<region>.sekoia.io/api`.
- Sekoia API key with the `Manage rules and alert filters` permission (Settings → Workspace → API Keys).
- Valhalla API key from [valhalla.nextron-systems.com](https://valhalla.nextron-systems.com). The public demo key `1111…` (sixty-four ones) is the built-in default and grants the community feed.

## How to use

1. In Sekoia, go to **Configure → Integrations**, search for **Valhalla**, and install it.
2. **Configure → Playbooks → + New playbook**. Start from scratch, then pick the **Sync Valhalla Sigma rules into Sekoia Rules Catalog** trigger.
3. Create an account for the trigger with your Valhalla API key, Sekoia API key, and Sekoia base URL.
4. Set trigger arguments: `frequency` (default 24h), `enabled` (default `false` — rules land disabled so you review before they fire), `min_sigma_level`, `min_sigma_status`.
5. Save and turn the playbook on. The first sync runs immediately; imported rules appear in **Detect → Rules Catalog**, tagged `valhalla-integration`.

To roll back, enable the **Delete all Valhalla-imported rules from the Sekoia Rules Catalog** trigger with `confirm=true`. It filters by the `valhalla-integration` marker tag and never touches user-created or Sekoia-verified rules. Defaults to dry-run.

## Triggers

| Docker parameter | Purpose |
|---|---|
| `sync-sigma-rules-catalog` | Pulls the Valhalla Sigma feed on `frequency`, converts each rule to ECS, POSTs new rules and PUTs previously-synced ones. Emits a `valhalla-sigma-catalog-sync` summary event with `created` / `updated` / `failed` / `skipped_unmapped` / `skipped_filter` / `top_unmapped`. |
| `delete-catalog-rules` | Deletes every rule this integration created. Default mode filters by the `valhalla-integration` marker tag; advanced mode filters on any top-level field via `match_field`/`match_value`. Dry-run unless `confirm=true`. |

## Module configuration

| Field | Secret | Description |
|---|---|---|
| `valhalla_api_key` | yes | Valhalla API key. Defaults to the public demo key. |
| `sekoia_api_key` | yes | Sekoia bearer token. Required by both triggers. |
| `sekoia_base_url` | no | Sekoia API base URL. Defaults to `https://api.sekoia.io` (FRA1). |

The Valhalla API URL is hardcoded to `https://valhalla.nextron-systems.com`.

## Repository layout

```
main.py                                        # entry point; registers both triggers
manifest.json                                  # module manifest (version, config schema, secrets)
trigger_sync_sigma_rules_catalog.json          # sync trigger manifest
trigger_delete_catalog_rules.json              # delete trigger manifest
sekoia_valhalla_integration_modules/
  client.py                                    # Valhalla HTTP client
  sekoia_client.py                             # Sekoia Rules Catalog HTTP client (pooled session + retries)
  sigma_mapper.py                              # Sigma YAML → Sekoia catalog payload conversion
  ecs_field_maps.py                            # Sigma field name → ECS field name tables
  models.py                                    # module + trigger base classes
  triggers/
    sync_sigma_rules_catalog.py
    delete_catalog_rules.py
tests/                                         # pytest suite (shipped; Sekoia's importer ignores it at runtime)
docs/                                          # mapping references and internal design notes
```

## Development

```
uv sync                # install deps
uv run pytest          # run the test suite
```

The `Dockerfile` builds the runtime image Sekoia executes. Bump `version` in `manifest.json` on every push-worthy change — Sekoia's importer rejects same-version reimports.

### Dependency management (uv *and* poetry)

The module ships **two lockfiles**, because its two consumers want different things:

| Lockfile | Used by |
|---|---|
| `uv.lock` | the `Dockerfile` (`uv sync --frozen`) and local development |
| `poetry.lock` | Sekoia's module importer, which rejects a module that ships no `poetry.lock` |

Runtime dependencies are declared once, in PEP 621 `[project].dependencies` — both tools read it. Dev dependencies must be declared **twice** (`[dependency-groups].dev` for uv, `[tool.poetry.group.dev.dependencies]` for poetry, which doesn't yet read PEP 735 groups).

After changing any dependency, regenerate both:

```
uv lock && poetry lock
```

Two resolvers over one dependency set drift silently — the first generation of this pair already disagreed on a transitive package. `tests/test_lockfiles.py` fails if the lockfiles disagree on a runtime version or if the two dev lists diverge, so `uv run pytest` catches it.
