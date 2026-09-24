# Common questions and the DQL to start from

Plain-language questions mapped to the data source and a query shape that runs.
Start from these and adapt them. Field names marked "check" vary by tenant:
confirm them in `entity_schemas.md` (or with `describe <source>`) before relying
on them.

## Open problems, issues, incidents, alerts, outages

People say "issues", "incidents", "alerts", "anything alerting right now?" or
"is anything broken" for Davis problems. They are the `dt.davis.problems` data object, not a metric and not a
`problems` or `issues` table.

```
fetch dt.davis.problems, from:-7d
| filter event.status == "ACTIVE"
| fields event.start, display_id, event.name, event.category, affected_entity_ids
| sort event.start desc
```

How many are open, by category:

```
fetch dt.davis.problems, from:-7d
| filter event.status == "ACTIVE"
| summarize open = count(), by:{event.category}
```

Problems closed in the last 24 hours: filter `event.status == "CLOSED"` with
`from:-24h`. Check the field names in the "Davis Problems" section of
`entity_schemas.md`.

## High CPU, memory or disk on hosts

Metrics, so `timeseries`, never `fetch`:

```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}, from:-1h
| filter usage > 90
| lookup [fetch dt.entity.host], sourceField:dt.entity.host, lookupField:id, prefix:"", fields:{entity.name}
| fields entity.name, usage
| sort usage desc
```

Swap the metric for memory (`dt.host.memory.usage`) or disk (`dt.host.disk.usage`).
Check the key exists in `metric_keys.md`.

## Errors in logs

```
fetch logs, from:-1h
| filter loglevel == "ERROR"
| summarize errors = count(), by:{host.name}
| sort errors desc
| limit 20
```

`loglevel` and `host.name` are common log attributes but check them: sample with
`fetch logs, from:-15m | limit 3`.

Search the text of log lines: `fetch logs, from:-1h | search "timeout" | limit 50`.

## Failing or slow services

```
timeseries total=sum(dt.service.request.count, scalar:true),
    failed=sum(dt.service.request.failure_count, scalar:true, default:0),
    by:{dt.entity.service}, from:-1h
| fieldsAdd failure_pct = failed / total * 100
| filter total > 0
| sort failure_pct desc
| limit 10
```

Slowest by response time: `avg(dt.service.request.response_time, scalar:true)`.

## Kubernetes

Container CPU by namespace:

```
timeseries cpu=avg(dt.kubernetes.container.cpu_usage, scalar:true), by:{k8s.namespace.name}, from:-1h
| sort cpu desc
```

Restarting containers:

```
timeseries restarts=sum(dt.kubernetes.container.restarts, scalar:true), by:{k8s.namespace.name, k8s.pod.name}, from:-24h
| filter restarts > 0
| sort restarts desc
```

## Which data sources exist here

```
fetch dt.system.data_objects
```

Then `describe <name>` for the fields of one of them.
