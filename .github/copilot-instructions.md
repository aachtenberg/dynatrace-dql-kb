# Dynatrace Query Language (DQL) — Copilot Instructions

When generating DQL queries, follow these rules exactly. DQL is NOT SQL.

## Starting Commands

| Data type | Command | Example |
|-----------|---------|---------|
| Metrics (CPU, memory, disk, network, request counts) | `timeseries` | `timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}` |
| Logs | `fetch logs` | `fetch logs \| filter status == "ERROR"` |
| Events | `fetch events` | `fetch events \| filter event.type == "K8S_EVENT"` |
| Business events | `fetch bizevents` | `fetch bizevents \| filter event.type == "com.example.purchase"` |
| Spans/traces | `fetch spans` | `fetch spans \| filter span.kind == "server"` |
| Entities | `fetch dt.entity.*` | `fetch dt.entity.host \| fields id, entity.name` |
| Metric discovery | `metrics` | `metrics \| filter contains(metricId, "cpu")` |
| Chart logs/events over time | `makeTimeseries` (after fetch) | `fetch logs \| makeTimeseries count(), interval:5m` |

## Critical Rules

1. **Metrics use `timeseries`, NEVER `fetch`.**
   `timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}` — CORRECT
   `fetch dt.host.cpu.usage` — WRONG, WILL NOT WORK

2. **`by:` always uses curly braces.**
   `by:{host.name}` — CORRECT
   `by: host.name` or `by:(host.name)` — WRONG

3. **Strings must be quoted in filters.**
   `filter status == "ERROR"` — CORRECT
   `filter status == ERROR` — WRONG

4. **No SQL syntax.** DQL is pipe-based. No SELECT, FROM, WHERE, GROUP BY, ORDER BY.
   - `fields` not SELECT
   - `filter` not WHERE
   - `summarize ... by:{}` not GROUP BY
   - `sort` not ORDER BY

5. **Time ranges differ by command.**
   - timeseries: `timeseries avg(dt.host.cpu.usage), from:-1h`
   - fetch: `fetch logs | filter timestamp >= now() - 1h`

6. **`makeTimeseries` is ONLY for non-metric data** (logs, events, spans).
   Never use it for actual metrics like dt.host.cpu.usage.

7. **timeseries always needs an aggregation function.**
   `timeseries avg(dt.host.cpu.usage)` — CORRECT
   `timeseries dt.host.cpu.usage` — WRONG

8. **Use `scalar:true` when you need a single number** (for sorting, filtering, tables).
   `timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}`

9. **Array operations use `[]`** for element-wise math on timeseries arrays.
   `| fieldsAdd available = 100 - cpu[]`

## Common Metric Keys

- `dt.host.cpu.usage`, `dt.host.cpu.system`, `dt.host.cpu.user`, `dt.host.cpu.idle`
- `dt.host.memory.usage`, `dt.host.memory.available`
- `dt.host.disk.usage`, `dt.host.disk.io.read`, `dt.host.disk.io.write`
- `dt.host.network.io.receive`, `dt.host.network.io.transmit`
- `dt.service.request.count`, `dt.service.request.response_time`, `dt.service.request.failure_count`
- `dt.containers.cpu.usage`, `dt.containers.memory.usage`

Discover more: `metrics | filter contains(metricId, "keyword")`

## Wrong → Right Quick Reference

| Wrong | Right | Why |
|-------|-------|-----|
| `fetch dt.host.cpu.usage` | `timeseries avg(dt.host.cpu.usage)` | Metrics use timeseries |
| `by: host.name` | `by:{host.name}` | Curly braces required |
| `filter status == ERROR` | `filter status == "ERROR"` | Strings need quotes |
| `\| where status == "ERROR"` | `\| filter status == "ERROR"` | No `where` in DQL |
| `\| select timestamp, host.name` | `\| fields timestamp, host.name` | No `select` in DQL |
| `\| order by timestamp desc` | `\| sort timestamp desc` | No `order by` in DQL |
| `\| group by host.name` | `\| summarize count(), by:{host.name}` | No `group by` in DQL |
| `timeseries dt.host.cpu.usage` | `timeseries avg(dt.host.cpu.usage)` | Aggregation required |
| `makeTimeseries avg(dt.host.cpu.usage)` | `timeseries avg(dt.host.cpu.usage)` | makeTimeseries is for logs/events |

## Key Patterns

**Enrich metrics with entity names:**
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
| fields entity.name, usage
| sort usage desc
```

**Multiple metrics on one chart (use append):**
```
timeseries cpu=avg(dt.host.cpu.usage), by:{dt.entity.host}
| append [timeseries mem=avg(dt.host.memory.usage), by:{dt.entity.host}]
```

**Error rate over time from logs (use makeTimeseries):**
```
fetch logs
| filter timestamp >= now() - 6h
| makeTimeseries error_count=countIf(status == "ERROR"),
    total=count(),
    interval:15m
```

**Week-over-week comparison (use shift + join):**
```
timeseries current=avg(dt.host.cpu.usage), by:{dt.entity.host}
| join [timeseries lastWeek=avg(dt.host.cpu.usage), by:{dt.entity.host}, shift:-7d],
    on:{dt.entity.host}, fields:{lastWeek}
```

For full syntax reference, see `docs/dql_syntax_reference.md`.
For more examples, see `docs/dql_example_queries.md`.
