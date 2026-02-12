# DQL Tips, Common Patterns, and Common Mistakes

## The #1 Mistake: Using fetch for metrics

WRONG — This is what LLMs trained on old data will generate:
```
fetch dt.host.cpu.usage
| filter value > 90
| fieldsAdd timestamp, host.name
```

RIGHT — Use the `timeseries` command for metrics:
```
timeseries cpu=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| filter cpu > 90
```

Rule of thumb:
- `fetch` → logs, events, bizevents, spans, entities
- `timeseries` → metric time series data (dt.host.cpu.*, dt.host.memory.*, etc.)
- `makeTimeseries` → create time series from non-metric data (logs, events, spans)
- `metrics` → discover available metric keys

## Time Ranges
Always specify a time filter to avoid scanning too much data:

For fetch commands:
```
| filter timestamp >= now() - 1h
```

For timeseries commands (use the from: parameter):
```
timeseries avg(dt.host.cpu.usage), from:-1h
timeseries avg(dt.host.cpu.usage), from:-7d, interval:1h
```

Time units: s (seconds), m (minutes), h (hours), d (days), w (weeks),
M (months), q (quarters), y (years)

Use `bin(timestamp, 5m)` with summarize for time-series aggregations on
non-metric data.

## Performance Tips
- Put `filter` commands as early as possible in the pipeline
- Use `limit` when you only need a sample
- Prefer `fields` to select only needed columns
- Use `bin()` with reasonable intervals (5m, 15m, 1h) for time-series
- The `timeseries` command auto-calculates appropriate intervals; override with `interval:` or `bins:` if needed
- Chaining `append` for multiple metrics is more efficient than querying multiple metrics in one `timeseries`

## Common Mistakes

### 1. Using fetch for metrics
See above — always use `timeseries` for metric data.

### 2. Using makeTimeseries for metrics
`makeTimeseries` is for creating time series from non-metric data like logs.
For actual metrics, use `timeseries`.

### 3. Using summarize instead of makeTimeseries for charting
`summarize` produces a single aggregated record. If you want to chart values
over time, use `makeTimeseries` (for logs/events) or `timeseries` (for metrics).

### 4. Forgetting the by: syntax uses curly braces
```
// WRONG
| summarize count(), by: host.name

// RIGHT
| summarize count(), by:{host.name}
```

### 5. Not handling missing data in timeseries
When calculating percentages or ratios, use `nonempty:true` and `default:0`:
```
timeseries errors=sum(http_requests, default:0),
    filter:{code==503},
    nonempty:true
```

### 6. Using collectDistinct with makeTimeseries
`makeTimeseries` requires numeric aggregation functions. `collectDistinct`
produces arrays of values, not numbers. Use `countDistinct` instead.

### 7. Forgetting quotes around string values in filter
```
// WRONG
| filter status == ERROR

// RIGHT
| filter status == "ERROR"
```

## Combining Conditions
```
| filter status == "ERROR" and service.name == "checkout"
| filter status == "ERROR" or status == "WARN"
| filter not contains(content, "healthcheck")
```

## Null Handling
```
| filter isNotNull(error.message)
| fieldsAdd safe_value = coalesce(value, 0)
```

## Working with Entities
Entity data is accessed via `dt.entity.*` types:
```
fetch dt.entity.host
| fields id, entity.name, tags
```

Use `lookup` to enrich metric data with entity names:
```
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
```

## Iterative Expressions (operating on arrays)
When `timeseries` returns arrays, use `[]` for element-wise operations:
```
timeseries cpu=avg(dt.host.cpu.usage), by:{dt.entity.host}
| fieldsAdd available = 100 - cpu[]
```

## Discovering What's Available
```
// List all core tables
fetch dt.system.data_objects
| filter type == "table"

// List all available metrics
metrics

// Find specific metrics
metrics | filter contains(metric.key, "cpu")

// Describe a table's schema
describe logs
```
