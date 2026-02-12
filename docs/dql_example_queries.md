# DQL Example Queries — Current Syntax
# Verified against docs.dynatrace.com

## Host Monitoring (uses `timeseries` command for metrics)

### CPU usage by host (last hour)
```
timeseries usage=avg(dt.host.cpu.usage), by:{dt.entity.host}
| sort usage desc
```

### Top 3 hosts by CPU usage (scalar for table output)
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| sort usage desc
| limit 3
```

### CPU usage with min/max/avg per host
```
timeseries min_cpu=min(dt.host.cpu.usage),
    max_cpu=max(dt.host.cpu.usage),
    avg_cpu=avg(dt.host.cpu.usage),
    by:{dt.entity.host},
    interval:5m
```

### CPU usage with summary scalar alongside time series
```
timeseries usage=avg(dt.host.cpu.usage),
    usage_summary=avg(dt.host.cpu.usage, scalar:true),
    by:{dt.entity.host}
```

### Memory usage with 5-minute intervals
```
timeseries avg_mem=avg(dt.host.memory.usage),
    by:{dt.entity.host},
    interval:5m,
    from:-6h
```

### Disk usage
```
timeseries avg(dt.host.disk.usage), by:{dt.entity.host, dt.entity.disk}
```

### Disk I/O with rate per second
```
timeseries write_rate=avg(dt.host.disk.io.write, rate:1s),
    read_rate=avg(dt.host.disk.io.read, rate:1s),
    by:{dt.entity.host}
```

### Network traffic
```
timeseries avg(dt.host.network.io.receive, rate:1s),
    avg(dt.host.network.io.transmit, rate:1s),
    by:{dt.entity.host}
```

### Count number of hosts sending CPU data
```
timeseries usage=avg(dt.host.cpu.usage), by:{dt.entity.host}
| summarize host_count = count()
```

### Week-over-week CPU comparison using shift
```
timeseries current=avg(dt.host.cpu.usage), by:{dt.entity.host}
| join [timeseries lastWeek=avg(dt.host.cpu.usage), by:{dt.entity.host}, shift:-7d],
    on:{dt.entity.host}, fields:{lastWeek}
```

### Multiple metrics via append (preferred for different metrics)
```
timeseries cpu=avg(dt.host.cpu.usage), by:{dt.entity.host}
| append [timeseries mem=avg(dt.host.memory.usage), by:{dt.entity.host}]
| append [timeseries disk=avg(dt.host.disk.usage), by:{dt.entity.host}]
```

Note: The `append` command is preferred over querying multiple different metrics
with a single timeseries command, as it doesn't require equivalent by or filter
arguments and is more efficient from a DQL perspective.

---

## Log Analysis (uses `fetch` command)

### Error logs in last hour
```
fetch logs
| filter timestamp >= now() - 1h
| filter status == "ERROR"
| sort timestamp desc
| limit 100
```

### Error count by service (last 24h)
```
fetch logs
| filter timestamp >= now() - 24h
| filter status == "ERROR"
| summarize error_count = count(), by:{service.name}
| sort error_count desc
```

### Search for specific error pattern
```
fetch logs
| filter timestamp >= now() - 1h
| filter contains(content, "OutOfMemoryError")
| fields timestamp, host.name, service.name, content
| sort timestamp desc
```

### Log volume over time as time series (uses makeTimeseries)
```
fetch logs
| filter timestamp >= now() - 6h
| makeTimeseries log_count = count(), by:{status}, interval:15m
```

### Error rate as time series
```
fetch logs
| filter timestamp >= now() - 6h
| filter dt.entity.kubernetes_cluster == "KUBERNETES_CLUSTER-ABCDEFG"
| makeTimeseries error_logs = countIf(loglevel == "ERROR"),
    all_logs = count(),
    interval:15m
```

### Parse and extract from log content
```
fetch logs
| filter timestamp >= now() - 1h
| filter endsWith(log.source, "pgi.log")
| parse content, "LD IPADDR:ip ':' LONG:payload SPACE LD 'HTTP_STATUS' SPACE INT:http_status LD (EOL|EOS)"
| summarize total_payload=sum(payload),
    failed=countIf(http_status >= 400),
    successful=countIf(http_status < 400),
    by:{ip, host.name}
| fieldsAdd payload_mb = total_payload / 1048576.0
| fields ip, host.name, payload_mb, failed, successful
| sort failed desc
```

---

## Service & Trace Analysis

### Slowest service endpoints (p95 response time)
```
fetch spans
| filter timestamp >= now() - 1h
| filter span.kind == "server"
| summarize p95_duration = percentile(duration, 95),
    avg_duration = avg(duration),
    request_count = count(),
    by:{service.name, http.route}
| fieldsAdd p95_ms = p95_duration / 1000000
| sort p95_ms desc
| limit 20
```

### Failed requests by service
```
fetch spans
| filter timestamp >= now() - 1h
| filter http.status_code >= 500
| summarize error_count = count(), by:{service.name, http.route, http.status_code}
| sort error_count desc
```

### Service dependency map data
```
fetch spans
| filter timestamp >= now() - 1h
| filter span.kind == "client"
| summarize call_count = count(),
    avg_duration = avg(duration),
    by:{service.name, peer.service}
| sort call_count desc
```

### Request rate over time via makeTimeseries
```
fetch spans
| filter span.kind == "server"
| makeTimeseries request_rate=count(), by:{service.name}, interval:5m
```

Note: For spans, the `makeTimeseries` command uses the `start_time` field
(not `timestamp`) for calculating the timeseries.

---

## Business Events

### Business event volume over time
```
fetch bizevents
| filter timestamp >= now() - 24h
| makeTimeseries event_count=count(), by:{event.type}, interval:1h
```

### Purchase analysis
```
fetch bizevents
| filter event.type == "com.example.purchase"
| filter timestamp >= now() - 7d
| makeTimeseries total=count(),
    high_volume=countIf(price > 1000),
    max_price=max(price),
    by:{accountId},
    interval:1d
```

---

## Entity Queries

### List all hosts
```
fetch dt.entity.host
| fields id, entity.name, tags
```

### List all services
```
fetch dt.entity.service
| fields id, entity.name, service.type
```

### List available data objects (tables)
```
fetch dt.system.data_objects
| filter type == "table"
```

### Enrich metrics with entity names via lookup
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
| fields entity.name, usage
| sort usage desc
```

---

## Kubernetes / Cloud

### Container CPU by namespace
```
timeseries avg(dt.containers.cpu.usage),
    by:{k8s.namespace.name, k8s.pod.name}
```

### Pod restart events
```
fetch events
| filter timestamp >= now() - 24h
| filter event.type == "K8S_EVENT"
| filter contains(content, "Restarted")
| summarize restart_count = count(), by:{k8s.pod.name, k8s.namespace.name}
| sort restart_count desc
```

### Kubernetes node CPU with annotation context
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
| lookup [fetch dt.entity.host
    | filter in(kubernetesLabels, "app.kubernetes.io/component")
    | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
```

---

## Advanced Patterns

### Failure rate calculation with nonempty + default
When calculating percentages, you need `nonempty:true` and `default:0`
to handle cases where one metric (e.g., errors) has no data:
```
timeseries total=sum(dt.service.request.count),
    errors=sum(dt.service.request.count, default:0, filter:{status=="ERROR"}),
    nonempty:true,
    by:{dt.entity.service}
| fieldsAdd failure_rate = errors[] / total[] * 100
```

### Iterative expressions on timeseries arrays
Use `[]` to perform element-wise operations on timeseries arrays:
```
timeseries cpu=avg(dt.host.cpu.usage), by:{dt.entity.host}
| fieldsAdd available_cpu = 100 - cpu[]
```

### Hosts with CPU above threshold (scalar for filtering)
```
timeseries cpu=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| filter cpu > 80
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
| fields entity.name, cpu
| sort cpu desc
```

### Service response time percentiles
```
timeseries p50=percentile(dt.service.request.response_time, 50),
    p90=percentile(dt.service.request.response_time, 90),
    p99=percentile(dt.service.request.response_time, 99),
    by:{dt.entity.service},
    interval:5m
```

### Error log spike detection (logs → makeTimeseries → summarize)
```
fetch logs
| filter timestamp >= now() - 24h
| filter status == "ERROR"
| makeTimeseries error_count=count(), by:{service.name}, interval:1h
| fieldsAdd max_errors = arrayMax(error_count)
| filter max_errors > 100
```

### Top error messages by frequency
```
fetch logs
| filter timestamp >= now() - 1h
| filter status == "ERROR"
| summarize error_count = count(), by:{content}
| sort error_count desc
| limit 10
```

### Logs from specific hosts
```
fetch logs
| filter timestamp >= now() - 1h
| filter in(host.name, {"web-server-01", "web-server-02", "api-server-01"})
| filter status == "ERROR"
| fields timestamp, host.name, service.name, content
| sort timestamp desc
```

### Distinct services per host
```
fetch logs
| filter timestamp >= now() - 24h
| summarize services = collectDistinct(service.name), by:{host.name}
| fieldsAdd service_count = arraySize(services)
| sort service_count desc
```

### Join logs with entity metadata
```
fetch logs
| filter timestamp >= now() - 1h
| filter status == "ERROR"
| summarize error_count = count(), by:{dt.entity.host}
| lookup [fetch dt.entity.host | fields id, entity.name, tags],
    sourceField:dt.entity.host, lookupField:id
| fields entity.name, error_count, tags
| sort error_count desc
```

### Memory and CPU together on same chart (append pattern)
```
timeseries cpu=avg(dt.host.cpu.usage), by:{dt.entity.host}
| append [timeseries mem=avg(dt.host.memory.usage), by:{dt.entity.host}]
```

### Process group instance count over time
```
timeseries count=sum(dt.process.count), by:{dt.entity.process_group}
```

### HTTP request error rate by service
```
timeseries total=sum(dt.service.request.count),
    errors=sum(dt.service.request.failure_count, default:0),
    nonempty:true,
    by:{dt.entity.service}
| fieldsAdd error_rate = errors[] / total[] * 100
```

### Dedup pattern — latest log per host
```
fetch logs
| filter timestamp >= now() - 1h
| sort timestamp desc
| dedup host.name
| fields timestamp, host.name, status, content
```

### Using fieldsRename to clean up output
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
| fieldsRename hostname = entity.name, cpu_percent = usage
| fields hostname, cpu_percent
| sort cpu_percent desc
```

### Conditional field with if()
```
fetch logs
| filter timestamp >= now() - 1h
| fieldsAdd severity = if(status == "ERROR", "critical",
    if(status == "WARN", "warning", "info"))
| summarize count(), by:{severity}
```

### Expand array into rows
```
fetch dt.entity.host
| fields id, entity.name, tags
| expand tags
```

### Metric discovery — find all host metrics
```
metrics
| filter startsWith(metricId, "dt.host.")
| fields metricId, description, unit
| sort metricId asc
```

### Metric discovery — find all service metrics
```
metrics
| filter startsWith(metricId, "dt.service.")
| fields metricId, description, unit
```

### Describe schema of a data source
```
describe logs
```

### List all data objects (tables) in the environment
```
fetch dt.system.data_objects
| filter type == "table"
| fields name, type
| sort name asc
```
