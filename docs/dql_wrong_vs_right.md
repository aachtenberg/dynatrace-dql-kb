# DQL: Wrong vs Right — Common LLM Hallucinations

This document exists because LLMs consistently generate broken DQL.
Every example below is a real mistake that LLMs make.
The WRONG version looks plausible but WILL NOT WORK.

---

## 1. Using fetch for metrics

WRONG:
```
fetch dt.host.cpu.usage
| filter value > 90
```

RIGHT:
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
```

WRONG:
```
fetch metrics
| filter metricId == "dt.host.cpu.usage"
```

RIGHT (to query metric data):
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
```

RIGHT (to discover available metrics):
```
metrics | filter contains(metricId, "cpu")
```

---

## 2. Missing curly braces on by:

WRONG:
```
| summarize count(), by: host.name
```

WRONG:
```
| summarize count(), by: (host.name)
```

WRONG:
```
| summarize count(), by:[host.name]
```

RIGHT:
```
| summarize count(), by:{host.name}
```

RIGHT (multiple fields):
```
| summarize count(), by:{host.name, service.name}
```

This applies everywhere by: is used: summarize, makeTimeseries, timeseries.

---

## 3. Using SQL syntax

WRONG:
```
SELECT host.name, avg(cpu_usage)
FROM dt.host.cpu.usage
WHERE timestamp > now() - 1h
GROUP BY host.name
ORDER BY avg(cpu_usage) DESC
```

RIGHT:
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| sort usage desc
```

WRONG:
```
SELECT * FROM logs WHERE status = 'ERROR'
```

RIGHT:
```
fetch logs
| filter status == "ERROR"
```

DQL has NO: SELECT, FROM, WHERE, GROUP BY, HAVING, ORDER BY, JOIN (SQL-style), LIMIT (SQL-style).
DQL equivalents: fields, fetch, filter, summarize by:{}, (none), sort, limit.

---

## 4. Using makeTimeseries for metrics

WRONG:
```
fetch dt.host.cpu.usage
| makeTimeseries avg(value), interval:5m
```

RIGHT:
```
timeseries avg(dt.host.cpu.usage), interval:5m, by:{dt.entity.host}
```

makeTimeseries is ONLY for non-metric data (logs, events, spans):
```
fetch logs
| filter status == "ERROR"
| makeTimeseries error_count=count(), interval:5m
```

---

## 5. Unquoted string values in filters

WRONG:
```
| filter status == ERROR
| filter host.name == my-host-01
| filter loglevel == WARN
```

RIGHT:
```
| filter status == "ERROR"
| filter host.name == "my-host-01"
| filter loglevel == "WARN"
```

---

## 6. Using where instead of filter

WRONG:
```
fetch logs
| where status == "ERROR"
```

RIGHT:
```
fetch logs
| filter status == "ERROR"
```

There is no `where` command in DQL. It's `filter`.

---

## 7. Using group by instead of summarize by:{}

WRONG:
```
fetch logs
| group by host.name
| count()
```

RIGHT:
```
fetch logs
| summarize count(), by:{host.name}
```

---

## 8. Using order by instead of sort

WRONG:
```
| order by timestamp desc
```

RIGHT:
```
| sort timestamp desc
```

---

## 9. Using select instead of fields

WRONG:
```
| select timestamp, host.name, content
```

RIGHT:
```
| fields timestamp, host.name, content
```

---

## 10. Inventing metric names

WRONG (these metrics DO NOT EXIST):
```
timeseries avg(cpu_usage)
timeseries avg(host.cpu.percent)
timeseries avg(system.cpu.utilization)
timeseries avg(dt.host.cpu)
timeseries avg(dt.cpu.usage)
```

RIGHT (actual Dynatrace metric keys):
```
timeseries avg(dt.host.cpu.usage)
```

Common REAL metric keys:
- dt.host.cpu.usage
- dt.host.cpu.system
- dt.host.cpu.user
- dt.host.cpu.idle
- dt.host.memory.usage
- dt.host.memory.available
- dt.host.disk.usage
- dt.host.disk.io.read
- dt.host.disk.io.write
- dt.host.network.io.receive
- dt.host.network.io.transmit
- dt.service.request.count
- dt.service.request.response_time
- dt.service.request.failure_count
- dt.containers.cpu.usage
- dt.containers.memory.usage

To discover metrics in your environment:
```
metrics
metrics | filter contains(metricId, "cpu")
metrics | filter contains(metricId, "host")
```

---

## 11. Wrong time range syntax

WRONG (on timeseries):
```
timeseries avg(dt.host.cpu.usage)
| filter timestamp >= now() - 1h
```

RIGHT (on timeseries — use from: parameter):
```
timeseries avg(dt.host.cpu.usage), from:-1h
```

WRONG (on fetch):
```
fetch logs, timeRange: "last 1 hour"
```

RIGHT (on fetch — use from:/to: or filter):
```
fetch logs, from:now()-1h
```
or:
```
fetch logs
| filter timestamp >= now() - 1h
```

---

## 12. Using count without parentheses

WRONG:
```
| summarize count by:{host.name}
```

RIGHT:
```
| summarize count(), by:{host.name}
```

All aggregation functions need parentheses: count(), sum(field), avg(field), min(field), max(field).

---

## 13. Using timeseries without an aggregation function

WRONG:
```
timeseries dt.host.cpu.usage
```

RIGHT:
```
timeseries avg(dt.host.cpu.usage)
```

timeseries ALWAYS requires an aggregation: avg(), sum(), min(), max(), percentile(), count().

---

## 14. Mixing up entity fetch vs metric query

WRONG (trying to get CPU from entity table):
```
fetch dt.entity.host
| fields entity.name, cpu_usage
```

RIGHT (entities don't have metric values — query metrics separately):
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
```

Entity tables (dt.entity.host, dt.entity.service) contain metadata (name, tags, properties).
Metric values come from `timeseries`.

---

## 15. Using collectDistinct with makeTimeseries

WRONG:
```
fetch logs
| makeTimeseries unique_hosts=collectDistinct(host.name), interval:5m
```

RIGHT:
```
fetch logs
| makeTimeseries unique_host_count=countDistinct(host.name), interval:5m
```

makeTimeseries requires NUMERIC aggregation functions. collectDistinct returns arrays of values, not numbers.

---

## 16. Forgetting scalar:true when you want a single value per group

When timeseries returns arrays (time series data) but you want a single number:

WRONG (returns arrays, can't sort or compare directly):
```
timeseries usage=avg(dt.host.cpu.usage), by:{dt.entity.host}
| sort usage desc
```

RIGHT (scalar:true collapses to single value):
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| sort usage desc
```

---

## 17. Using pipe before the first command

WRONG:
```
| fetch logs
| filter status == "ERROR"
```

RIGHT:
```
fetch logs
| filter status == "ERROR"
```

The first command (fetch, timeseries, data, metrics) does NOT have a pipe before it.
