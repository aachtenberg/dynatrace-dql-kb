# Smartscape calls on this tenant

2026-09-24. Kept out of `docs/` so `dql_rag.py ingest` does not treat it as DQL reference.

No `SERVICE` nodes, and no spans in the last hour, so the `SERVICE` examples in `docs/smartscape_calls.md` return no rows. The same statements against `PROCESS` returned callers through `target_id`, one callee through `source_id`, and both `traverse` directions. `getNodeName()` filled in the process name.

`fetch dt.entity.service` returned no rows and was flagged `CLASSIC_ENTITY_MIGRATION_ADVISED`. Service questions written against `dt.entity.service` come back empty here for that reason. Use the Smartscape edges.
