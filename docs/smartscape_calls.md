# Spans to Smartscape calls

Checked 2026-09-24. The classic id on a span joins to `id_classic` on the Smartscape node. `calls` and `called_by` are the `calls` edge, walked forward or backward.

## Which id the span has

Current spans store the Smartscape id in `dt.smartscape.service`. Use that as the edge key.

Older spans store the classic id in `dt.entity.service` (`SERVICE-…`). That string is a different id when the node type was renamed. The node keeps the old id in `id_classic`. A process node here is `id = PROCESS-…` and `id_classic = PROCESS_GROUP_INSTANCE-…`: same suffix, different type prefix. `toSmartscapeId()` on the classic string does not find that node. Look the classic id up:

```
fetch spans, from: now()-1h
| filter isNotNull(dt.entity.service)
| lookup [
    smartscapeNodes SERVICE
    | fields id, id_classic
  ],
  sourceField: dt.entity.service,
  lookupField: id_classic,
  fields: { id }
| fieldsAdd service_id = lookup.id
```

`toSmartscapeId("SERVICE-…")` is for a classic id whose type prefix did not change.

## calls and called_by

These are not arrays on the span, and they are not in the node `references` record. `references` holds static edges. On a process node here that record is `runs_on.host` and `runs_on.container`.

Service calls are dynamic `calls` edges. There is no `called_by` edge type. Callers are `calls` with this service on the target side:

```
smartscapeEdges "calls"
| filter source_type == "SERVICE" and target_type == "SERVICE"
| filter target_id == toSmartscapeId("SERVICE-0123456789ABCDEF")
| fieldsAdd caller_id = source_id, caller = getNodeName(source_id)
```

Services it calls use the same edge with `source_id` filtered instead of `target_id`. From the node, callers are `traverse calls, SERVICE, direction:backward` and callees are `direction:forward`.

`lookup` keeps one match per span. Several callers need `join` or `joinNested` onto `smartscapeEdges "calls"`: match `service_id` to `target_id` for callers and to `source_id` for callees.

## What this tenant returned

No `SERVICE` nodes, and no spans in the last 6 hours. The live `calls` edges are `PROCESS → PROCESS`.

`fetch dt.entity.service` returned no rows and was flagged `CLASSIC_ENTITY_MIGRATION_ADVISED`. The `calls` and `called_by` records on `dt.entity.service` in `entity_schemas.md` are not the path that returns data here.
