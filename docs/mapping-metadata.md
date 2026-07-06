# Metadata mapping — Sigma → Sekoia Rules Catalog JSON

Every Valhalla Sigma rule is broken into two parts before it lands in Sekoia:

1. **Rule-level metadata** (title, description, tags, severity, …) → lifted
   to top-level Sekoia JSON fields on the Rules Catalog `POST` body. This
   document lists every such lift.
2. **The `detection:` block** → kept in `payload` after ECS field-name
   conversion. See [mapping-ecs.md](mapping-ecs.md).

Implementation: [`sigma_rule_to_catalog_payload()`](../sekoia_valhalla_integration_modules/sigma_mapper.py) in `sigma_mapper.py`.

## Fields always shipped

| Sekoia JSON field  | Source                             | Notes                                                                                                          |
| ------------------ | ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `name`             | Sigma `title`                      | Truncated to 100 chars with `…` suffix (`MAX_NAME_LENGTH`). Falls back to `rule.name` → `rule.filename` → `"unnamed"`. |
| `type`             | literal `"sigma"`                  | Sekoia's rule-type discriminator.                                                                              |
| `description`      | Sigma `description`                | Truncated to 1000 chars with `…` suffix (`MAX_DESCRIPTION_LENGTH`). Empty string when the Sigma rule has none.  |
| `payload`          | Sigma `detection:` block           | Only the detection block, YAML-serialised with the `detection:` keyword preserved. Field names ECS-converted.  |
| `severity`         | Sigma `level`                      | See severity mapping below. Missing → `0`.                                                                     |
| `effort`           | Sigma `status`                     | See effort mapping below. Missing → `2` (test).                                                                |
| `alert_type_uuid`  | trigger config                     | Not derived from Sigma — supplied via the sync trigger's `alert_type_uuid` argument.                           |
| `enabled`          | trigger config                     | Defaults to `false` — rules opt-in in the Sekoia UI.                                                           |

## Fields shipped only when the Sigma source has them

| Sekoia JSON field     | Source                | Notes                                                                                                          |
| --------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------- |
| `tags`                | Sigma `tags`          | Passed through as a list of strings.                                                                           |
| `related_object_refs` | Sigma `related[].id`  | Sigma's `related` is a list of `{id, type}` dicts; only the UUID `id` values are forwarded. Rules whose entries lack an `id` do not ship the field. |
| `false_positives`     | Sigma `falsepositives`| List of strings is joined with newlines; a bare string is passed through. Missing → field omitted.             |

## Fields intentionally NOT shipped

| Sekoia JSON field | Why omitted                                                                                                                                                                                                             |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `community_uuid`  | Setting an arbitrary Valhalla rule ID triggered Sekoia's AU202 scope check when combined with other metadata fields, and Sekoia overrode our value with its own default (`4039e5c6-…`) anyway. Verified via curl bisect. |
| `datasources`     | Sekoia expects a list of tenant-registered data-source **UUIDs**, not the free-form Sigma `logsource` dict. Can't derive UUIDs from `{product, category}` without tenant-specific context. Sigma `logsource` remains visible via the payload YAML. |

## Severity mapping — Sigma `level` → Sekoia `severity`

| Sigma `level`   | Sekoia `severity` |
| --------------- | ----------------- |
| `informational` | 10                |
| `low`           | 30                |
| `medium`        | 50                |
| `high`          | 70                |
| `critical`      | 90                |
| _(missing)_     | 0                 |

Defined in `SEVERITY_MAP` / `DEFAULT_SEVERITY`.

## Effort mapping — Sigma `status` → Sekoia `effort`

| Sigma `status`  | Sekoia `effort` |
| --------------- | --------------- |
| `stable`        | 1               |
| `test`          | 2               |
| `experimental`  | 3               |
| `unsupported`   | 4               |
| `deprecated`    | 4               |
| _(missing)_     | 2               |

Defined in `STATUS_TO_EFFORT` / `DEFAULT_EFFORT`.
