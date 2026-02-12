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
- `load <resource>` — load lookup table data
- `describe <source>` — show schema
- `smartscapeNodes type:<type>` — load topology nodes
- `smartscapeEdges type:<type>` — load topology edges

## Pipe Commands
- `filter <condition>` — keep matching records
- `filterOut <condition>` — remove matching records
- `search "text"` — case-insensitive text search (after fetch only)
- `fields <field1>, <field2>` — keep only these fields (can create new computed fields)
- `fieldsAdd <name> = <expression>` — add/replace a field
- `fieldsKeep <field1>, <field2>` — keep existing fields only (won't create new ones)
- `fieldsRemove <field>` — drop a field
- `fieldsRename <new> = <old>` — rename a field
- `fieldsFlatten <record_field>` — flatten nested record into columns
- `sort <field> asc|desc` — sort records (default asc, place at end for performance)
- `limit <n>` — cap result count (don't use before aggregation)
- `summarize <agg>(), by:{<field>}` — group and aggregate
- `dedup <field>` — deduplicate (keep first occurrence)
- `parse <field>, "<DPL_pattern>"` — extract fields using Dynatrace Pattern Language
- `expand <array_field>` — explode array into rows
- `lookup [<subquery>], sourceField:<f>, lookupField:<f>` — enrich (first match only)
- `join [<subquery>], on:{<field>}, fields:{<field>}` — join with subquery
- `append [<subquery>]` — union results from subquery
- `joinNested [<subquery>], on:{<field>}` — join as nested array of records
- `makeTimeseries <agg>(), interval:<duration>` — chart non-metric data over time
- `fieldsSummary <field>` — field cardinality stats

## fetch Command
```
fetch dataObject [,bucket:name] [,from:timestamp] [,to:timestamp]
    [,timeframe:timeframe] [,samplingRatio:number] [,scanLimitGBytes:number]
```

## timeseries Command (for metrics ONLY)
```
timeseries [name=]aggregation(metricKey [,scalar:true] [,default:val] [,rate:1s] [,rollup:type] [,filter:{...}]),
    [by:{dimension1, dimension2}],
    [interval:duration],
    [bins:number],
    [from:-duration],
    [to:timestamp],
    [timeframe:timeframe],
    [shift:-duration],
    [nonempty:true],
    [bucket:name]
```

Examples:
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}, from:-7d, interval:1h
timeseries write_rate=avg(dt.host.disk.io.write, rate:1s), by:{dt.entity.host}
timeseries errors=sum(dt.service.request.count, default:0, filter:{status=="ERROR"}), nonempty:true, by:{dt.entity.service}
timeseries failed = avg(dt.requests.failed, rollup:sum)
```

## join types
- Inner (default): `| join [subquery], on:{field}, fields:{field}`
- Left outer: `| join [subquery], on:{field}, fields:{field}, kind:leftOuter`
- Outer: `| join [subquery], on:{field}, fields:{field}, kind:outer`

## Aggregation Functions
`count()`, `countIf(cond)`, `sum(f)`, `avg(f)`, `min(f)`, `max(f)`,
`percentile(f, n)`, `median(f)`, `stddev(f)`, `variance(f)`,
`countDistinctExact(f)`, `countDistinctApprox(f)`, `collectDistinct(f)`,
`collectArray(f)`, `correlation(f1, f2)`,
`takeFirst(f)`, `takeLast(f)`, `takeAny(f)`, `takeMax(f)`, `takeMin(f)`

## String Functions
`contains(f, "s")`, `startsWith(f, "s")`, `endsWith(f, "s")`,
`matchesPhrase(f, "s")`, `matchesValue(f, "pattern")`,
`lower(f)`, `upper(f)`, `trim(f)`, `trimStart(f)`, `trimEnd(f)`,
`substring(f, start, end)`, `indexOf(f, "s")`,
`replace(f, "old", "new")`, `replaceAll(f, "DPL", "new")`,
`replacePattern(f, "regex", "new")`,
`concat(f1, f2)`, `strlen(f)`, `splitString(f, "delim")`

## Conditional Functions
`if(cond, then, else)`, `coalesce(f1, f2, default)`,
`in(f, "v1", "v2")`, `isNull(f)`, `isNotNull(f)`, `isTrueOrNull(expr)`, `exists(f)`

## Math Functions
`abs(v)`, `ceil(v)`, `floor(v)`, `round(v, n)`, `pow(base, exp)`, `sqrt(v)`,
`log(v)`, `log10(v)`, `exp(v)`

## Time Functions
`now()`, `bin(timestamp, 5m)`, `start()`, `end()`, `duration(amount, unit)`,
`formatTimestamp(ts, "pattern", tz, locale)`, `toTimestamp(f)`,
`timestampFromMillis(ms)`, `timestampFromNanos(ns)`, `timestampFromSeconds(s)`,
`getHour(ts)`, `getMinute(ts)`, `getDay(ts)`, `getDayOfWeek(ts)`, `getDayOfYear(ts)`,
`getMonth(ts)`, `getYear(ts)`,
`timeframe(from:ts, to:ts)`, `timeframeStart(tf)`, `timeframeEnd(tf)`
Units: `s`, `m`, `h`, `d`, `w`, `M`, `q`, `y`

## Array Functions
`array(1,2,3)`, `arraySize(f)`, `arrayConcat(a1,a2)`, `arrayDistinct(f)`,
`arrayFirst(f)`, `arrayLast(f)`, `arrayContains(f,val)`, `arraySlice(f,start,end)`,
`arrayRemoveNulls(f)`, `arraySort(f)`

## Type Conversions
`toBoolean()`, `toLong()`, `toDouble()`, `toString()`, `toTimestamp()`,
`toDuration()`, `toIp()`, `toArray()`, `toRecord()`

## Hash Functions
`crc32(f)`, `md5(f)`, `sha1(f)`, `sha256(f)`, `sha512(f)`

## Network/IP Functions
`ipAddr(s)`, `ipInSubnet(ip,"cidr")`, `ipIsPrivate(ip)`, `ipIsPublic(ip)`,
`ipIsLoopback(ip)`, `ipIsLinkLocal(ip)`, `ipMask(ip,len)`, `isIpv4(v)`, `isIpv6(v)`

## Encoding Functions
`encodeBase64(v)`, `decodeBase64ToString(v)`, `decodeBase64ToBinary(v)`

## Entity Functions
`entityName(id)`, `entityAttr(id, "attr")`, `classicEntitySelector("selector")`

## Operators
- Comparison: `==`, `!=`, `>`, `>=`, `<`, `<=` (tri-state: null == x → null)
- Logical: `and`, `or`, `not` (tri-state boolean)
- Arithmetic: `+`, `-`, `*`, `/` (long/long=long truncated), `%`
- Pattern match: `~` (case-insensitive wildcard: `host.name ~ "prod*"`)
- Timestamp align: `@` (round down: `timestamp @ 1h`)
- Array element: `[]` (element-wise on timeseries arrays: `cpu[]`)

## DPL Matchers (for parse command)
Text: `LD`, `WORD`, `SPACE`, `EOL`, `EOS`, `'literal'`, `DATA`
Numeric: `INT`, `LONG`, `DOUBLE`, `HEX`
Structured: `IPADDR`, `IPV4ADDR`, `IPV6ADDR`, `TIMESTAMP`, `JSON`
Modifiers: `?` (optional), `{min,max}` (repeat)
Export: `MATCHER:fieldname` (e.g., `INT:status_code`)
