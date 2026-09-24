# Spans to Smartscape calls

How to get from a span's service id to the Smartscape `calls` edges, i.e. which services call it and which it calls. Syntax follows the Dynatrace docs for [Smartscape commands](https://docs.dynatrace.com/docs/platform/grail/dynatrace-query-language/commands/smartscape-commands). Verified with `PROCESS` nodes.

## Which id the span has

Current spans store the Smartscape id in `dt.smartscape.service`. Use that as the edge key.

Older spans store the classic id in `dt.entity.service` (`SERVICE-…`). Where a Smartscape node type kept its classic prefix, `toSmartscapeId()` turns that string into the node id:

```
toSmartscapeId("SERVICE-0123456789ABCDEF")
```

Where the type was renamed, it does not. The node keeps the old id in `id_classic`. Seen on a tenant (2026-09-24): a process node is `id = PROCESS-…` with `id_classic = PROCESS_GROUP_INSTANCE-…`, same suffix, different prefix, and `toSmartscapeId()` on the classic string found nothing. For a renamed type, look the classic id up:

```
fetch spans, from:now()-1h
| filter isNotNull(dt.entity.service)
| lookup [
    smartscapeNodes SERVICE
    | fields service_id = id, id_classic
  ],
  sourceField:dt.entity.service,
  lookupField:id_classic,
  fields:{service_id}
```

`fields:{id}` adds a column named `id`. `lookup.id` is not a field, and `prefix` cannot be combined with `fields`. The same `lookup` against a `PROCESS` node, fed the classic `PROCESS_GROUP_INSTANCE-…` id, returned the `PROCESS-…` id.

## calls and called_by

These are not arrays on the span, and they are not in the node `references` record. `references` holds static edges; on a process node (seen on a tenant) that record is `runs_on.host` and `runs_on.container`.

Service calls are dynamic `calls` edges. There is no `called_by` edge type. Callers are `calls` edges with this service on the target side:

```
smartscapeEdges calls
| filter source_type == "SERVICE" and target_type == "SERVICE"
| filter target_id == toSmartscapeId("SERVICE-0123456789ABCDEF")
| fieldsAdd caller_id = source_id, caller = getNodeName(source_id)
```

Services it calls: the same query with `source_id` filtered instead of `target_id`. From the node, callers are `traverse {calls}, {SERVICE}, direction:backward` and callees `direction:forward`. Unbraced `traverse calls, PROCESS` still returns rows, with a notice that the arguments should be in curly braces. The same unbraced form on `SERVICE` runs and emits that notice.

`lookup` keeps one match per span. Several callers need `join` or `joinNested` onto `smartscapeEdges calls`: match `service_id` to `target_id` for callers and to `source_id` for callees.

On tenants moving off the classic entity model, `fetch dt.entity.service` can return nothing, and its `calls` / `called_by` records (listed in `entity_schemas.md`) are then not the path that returns data. Use the Smartscape edges above.
