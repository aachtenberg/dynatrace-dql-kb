---
applyTo: "**/*.dql,**/*.md"
---

# DQL Query Syntax Instructions

When writing or editing DQL queries, use ONLY the syntax documented here.

## Query Structure
DQL queries are pipe-based. A starting command feeds into pipe commands:
```
<starting_command>
| <pipe_command>
| <pipe_command>
| ...
```

## Starting Commands (no pipe before these)
- `fetch <source>` — logs, events, bizevents, spans, dt.entity.*, dt.system.data_objects
- `timeseries <aggregation>(metricKey)` — metric time series data
- `metrics` — list available metric keys
- `data record(...)` — inline test data
- `describe <source>` — show schema

## Pipe Commands
- `filter <condition>` — keep matching records
- `filterOut <condition>` — remove matching records
- `fields <field1>, <field2>` — keep only these fields
- `fieldsAdd <name> = <expression>` — add/replace a field
- `fieldsRemove <field>` — drop a field
- `fieldsRename <new> = <old>` — rename a field
- `sort <field> asc|desc` — sort records
- `limit <n>` — cap result count
- `summarize <agg>(), by:{<field>}` — group and aggregate
- `dedup <field>` — deduplicate
- `parse <field>, "<pattern>"` — extract fields from text
- `expand <array_field>` — explode array into rows
- `lookup [<subquery>], sourceField:<f>, lookupField:<f>` — enrich with subquery
- `join [<subquery>], on:{<field>}, fields:{<field>}` — join with subquery
- `append [<subquery>]` — union results from subquery
- `makeTimeseries <agg>(), interval:<duration>` — chart non-metric data over time

## timeseries Command (for metrics ONLY)
```
timeseries [name=]aggregation(metricKey [,scalar:true] [,default:val] [,rate:1s] [,filter:{...}] [,rollup:type]),
    [by:{dimension1, dimension2}],
    [interval:duration],
    [from:-duration],
    [to:timestamp],
    [shift:-duration],
    [nonempty:true]
```

Examples:
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}, from:-7d, interval:1h
timeseries write_rate=avg(dt.host.disk.io.write, rate:1s), by:{dt.entity.host}
timeseries errors=sum(dt.service.request.count, default:0, filter:{status=="ERROR"}), nonempty:true, by:{dt.entity.service}
```

## Aggregation Functions
`count()`, `countIf(cond)`, `sum(f)`, `avg(f)`, `min(f)`, `max(f)`,
`percentile(f, n)`, `median(f)`, `stddev(f)`, `variance(f)`,
`countDistinct(f)`, `countDistinctApprox(f)`, `collectDistinct(f)`,
`collectArray(f)`, `takeFirst(f)`, `takeLast(f)`, `takeAny(f)`

## String Functions
`contains(f, "s")`, `startsWith(f, "s")`, `endsWith(f, "s")`,
`matchesPhrase(f, "s")`, `matchesValue(f, "pattern")`,
`lower(f)`, `upper(f)`, `trim(f)`, `substring(f, start, len)`,
`indexOf(f, "s")`, `replace(f, "old", "new")`, `concat(f1, f2)`,
`strlen(f)`, `splitString(f, "delim")`

## Conditional Functions
`if(cond, then, else)`, `coalesce(f1, f2, default)`,
`in(f, "v1", "v2")`, `isNull(f)`, `isNotNull(f)`

## Time
`now()`, `now() - 1h`, `bin(timestamp, 5m)`, `start()`, `end()`
Units: `s`, `m`, `h`, `d`, `w`, `M`, `q`, `y`

## Type Conversions
`toBoolean()`, `toLong()`, `toDouble()`, `toString()`, `toTimestamp()`, `toDuration()`
