# DQL (Dynatrace Query Language) Syntax Reference
# Source: docs.dynatrace.com — verified against current documentation

## Overview
DQL is used to query Dynatrace Grail data lakehouse. Queries follow a pipe-based
syntax where data flows through a series of commands separated by the pipe `|` operator.

## CRITICAL: Metrics vs Logs/Events/Entities

DQL has different starting commands depending on what you're querying.
Getting this wrong is the #1 mistake LLMs make with DQL.

### For logs, events, entities, bizevents, spans:
Use `fetch` as the starting command:
```
fetch logs
fetch logs, from:now()-2h, to:now()
fetch events
fetch bizevents
fetch spans
fetch dt.entity.host
fetch dt.entity.service
fetch dt.system.data_objects
```

### For METRICS (time-series data like CPU, memory, disk, network):
Use `timeseries` as the starting command — NOT `fetch`:
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
timeseries max(dt.host.memory.usage), interval:5m
timeseries sum(dt.host.disk.io.write), by:{dt.entity.host}, from:-7d
```

The `timeseries` command combines loading, filtering, and aggregating metrics
into a time series output in a single command. It returns arrays of values
with a timeframe column.

### timeseries full syntax:
```
timeseries [column =] aggregation(metricKey [, filter:] [, default:] [, rollup:] [, rate:] [, scalar:])
    [, [column =] aggregation(metricKey, ...), ...]
    [, by:]
    [, filter:]
    [, union:]
    [, nonempty:]
    [, interval: | bins:]
    [, from:]
    [, to:]
    [, timeframe:]
    [, shift:]
    [, bucket:]
```

Parameters:
- `aggregation`: Required. One of: avg, sum, min, max, count, percentile, median, stddev, variance
- `metricKey`: Required. The metric identifier (e.g., dt.host.cpu.usage)
- `filter:{}`: Filter within a specific aggregation (e.g., `filter:{status=="ERROR"}`)
- `default:value`: Fill missing time slots with this value instead of null
- `rollup:type`: Specify time aggregation independently from main aggregation (e.g., `rollup:sum`)
- `rate:duration`: Convert counters to rate per duration (e.g., `rate:1s`)
- `scalar:true`: Return a single value per group instead of an array (needed for sorting/filtering)
- `by:{dim1, dim2}`: Group by dimensions. MUST use curly braces
- `nonempty:true`: Exclude series where all values are null
- `interval:duration`: Time bucket size (e.g., `interval:5m`, `interval:1h`)
- `bins:number`: Alternative to interval — specify number of time buckets
- `from:-duration`: Start of time range (e.g., `from:-7d`)
- `to:timestamp`: End of time range
- `timeframe:timeframe`: Explicit timeframe object
- `shift:-duration`: Shift the query window back in time (for comparisons)
- `bucket:name`: Filter to specific Grail bucket

### timeseries examples:
```
// CPU usage by host, last 7 days, 1-hour intervals
timeseries min_cpu=min(dt.host.cpu.usage),
    max(dt.host.cpu.usage, default:99.9),
    by:dt.entity.host,
    filter:in(dt.entity.host, "HOST-1", "HOST-2"),
    interval:1h,
    from:-7d

// Scalar result (single value per host, not array)
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}

// Summary stat across all hosts (scalar + no by)
timeseries usage=avg(dt.host.cpu.usage),
    usage_summary=avg(dt.host.cpu.usage, scalar:true),
    by:{dt.entity.host}

// Disk I/O with rate conversion
timeseries avg(dt.host.disk.io.write, rate:1s)

// Nonempty + default to handle missing data
timeseries http_503=sum(http_requests, default:0), filter:{code==503}, nonempty:true

// Rollup — average of the sums (independent time aggregation)
timeseries failed = avg(dt.requests.failed, rollup:sum)

// Time-shifted comparison (last week vs now)
timeseries curLogins = avg(custom.db.query), by:{query_name}, interval:1m
| filter query_name == "Login Count"
| join [timeseries prev7Days = avg(custom.db.query), by:{query_name}, interval:1m, shift:-7d
    | filter query_name == "Login Count"],
    on:{query_name}, fields:{prev7Days}
```

### metrics command (for discovering available metrics):
```
// List available metrics
metrics

// Find metrics matching a pattern
metrics | filter contains(metric.key, "cpu")

// Get metadata for specific metric
metrics | filter metric.key == "dt.host.cpu.usage"
```

### makeTimeseries (for creating time series from NON-metric data):
Use `makeTimeseries` to chart logs, events, spans over time.
Do NOT use it for actual metrics — use `timeseries` for that.
```
fetch logs
| filter status == "ERROR"
| makeTimeseries error_count=count(), interval:5m

fetch logs
| makeTimeseries error_logs = countIf(loglevel == "ERROR"),
    all_logs = count(),
    interval:15m

fetch bizevents
| filter event.type == "com.example.purchase"
| makeTimeseries purchase_count=count(), by:{product_category}, interval:1h
```

makeTimeseries syntax:
```
makeTimeseries [by: { [expression, ...] }]
    [, interval]
    [, bins]
    [, from]
    [, to]
    [, timeframe]
    [, time]
    [, spread]
    [, nonempty]
    [, scalar:]
    aggregation, ...
```

IMPORTANT: `makeTimeseries` aggregation functions require numeric inputs.
It produces arrays of numbers (tracks changes over time), so it will NOT work
with functions like `collectDistinct` that produce arrays of non-numeric values.

---

## Data Source Commands

### fetch
Loads data from the specified data object.

Full syntax:
```
fetch dataObject [, bucket:name] [, from:timestamp] [, to:timestamp]
    [, timeframe:timeframe] [, samplingRatio:number] [, scanLimitGBytes:number]
```

Parameters:
- `bucket:name`: Filter to a specific Grail bucket
- `from:timestamp`: Start of time range (e.g., `from:now()-2h`)
- `to:timestamp`: End of time range
- `timeframe:timeframe`: Explicit timeframe
- `samplingRatio:number`: Return 1/N of available records (reported in dt.system.sampling_ratio)
- `scanLimitGBytes:number`: Stop processing after scanning this many GB of data

Valid data objects for fetch:
- `logs` — log records
- `events` — event records
- `bizevents` — business event records
- `spans` — distributed trace spans
- `dt.entity.host` — host entities
- `dt.entity.service` — service entities
- `dt.entity.process_group` — process group entities
- `dt.entity.process_group_instance` — process group instance entities
- `dt.entity.cloud_application` — Kubernetes workloads
- `dt.entity.cloud_application_namespace` — Kubernetes namespaces
- `dt.entity.kubernetes_cluster` — Kubernetes clusters
- Any `dt.entity.*` type
- `dt.system.data_objects` — list available data objects

Examples:
```
fetch logs
fetch logs, from:now()-2h, to:now()
fetch logs, samplingRatio:10
fetch logs, scanLimitGBytes:5
fetch logs, bucket:"default_logs"
fetch events
fetch bizevents
fetch spans
fetch dt.entity.host
fetch dt.entity.service
fetch dt.system.data_objects | filter type == "table"
```

### data
Generates sample data during query runtime (useful for testing).
```
data record(a = 1, b = "hello"), record(a = 2, b = "world")
```

### load
Loads data from a specified resource. Used with lookup tables.
```
lookup [load dt.lookup.my_lookup_table], sourceField:key, lookupField:id
```

### describe
Describes the on-read schema extraction definition for a given data object.
```
describe logs
describe dt.entity.host
```

---

## Filter and Search Commands

### filter
Reduces records by keeping only those matching the condition.
```
| filter host.name == "my-host"
| filter value > 90
| filter timestamp >= now() - 1h
| filter status == "ERROR" and service.name == "payment-service"
| filter contains(content, "OutOfMemory")
| filter in(host.name, {"host-1", "host-2", "host-3"})
| filter isNotNull(error.message)
```

### filterOut
Removes records that match a specific condition (inverse of filter).
```
| filterOut contains(content, "healthcheck")
| filterOut status == "INFO"
```

### search
Case-insensitive search across fields. Works like a search bar.
Must appear after fetch (with only filter, filterOut, fieldsKeep, fieldsRemove,
fieldsRename, limit, or append allowed between fetch and search).
```
fetch logs
| search "OutOfMemoryError"

fetch logs
| filter loglevel == "ERROR"
| search "payment"
```

### dedup
Removes duplicates from a list of records. Keeps first occurrence.
```
| dedup host.name
| dedup host.name, service.name
```

---

## Selection and Modification Commands

### fields
Keeps only specified fields. Can also create new computed fields.
```
| fields timestamp, host.name, value
| fields name = entity.name, cpu = usage
```

### fieldsAdd
Evaluates an expression and appends or replaces a field.
```
| fieldsAdd duration_ms = duration / 1000000
| fieldsAdd status_category = if(status_code >= 500, "server_error",
    if(status_code >= 400, "client_error", "success"))
```

### fieldsKeep
Keeps selected fields. Unlike `fields`, does not create new fields if they don't exist.
```
| fieldsKeep timestamp, host.name
```

### fieldsRemove
Removes fields from the result.
```
| fieldsRemove internal_id, debug_info
```

### fieldsRename
Renames a field.
```
| fieldsRename new_name = old_name
```

---

## Extraction and Parsing Commands

### parse
Parses a record field using Dynatrace Pattern Language (DPL) and outputs extracted fields.

Syntax: `parse field, "DPL_pattern"`

```
| parse content, "LD IPADDR:ip ':' LONG:payload SPACE LD 'HTTP_STATUS' SPACE INT:http_status LD (EOL|EOS)"
| parse content, "JSON:json"
| parse content, "LD 'user=' LD:username SPACE"
```

#### Dynatrace Pattern Language (DPL) Matchers

DPL is used with the `parse` command. A matcher extracts data when given an export name (`MATCHER:fieldname`).

**Text matchers:**
- `LD` — Line data: matches any characters until the next matcher. Must be followed by another matcher
- `WORD` — Matches a word (non-whitespace characters)
- `SPACE` — Matches space and tab characters
- `EOL` — End of line
- `EOS` — End of string
- `'literal'` — Matches a literal string (single-quoted)

**Numeric matchers:**
- `INT` — Integer (-2147483648 to 2147483647)
- `LONG` — Long integer
- `DOUBLE` — Floating point number
- `HEX` — Hexadecimal number

**Structured matchers:**
- `IPADDR` — IPv4 or IPv6 address
- `IPV4ADDR` — IPv4 address only
- `IPV6ADDR` — IPv6 address only
- `TIMESTAMP` — Timestamp in various formats
- `JSON` — JSON object or array
- `DATA` — Matches everything (greedy)

**Modifiers (appended to matchers):**
- `?` — Optional (e.g., `SPACE?`)
- `{min,max}` — Repeat range

Examples:
```
// Parse Apache log line
| parse content, "IPADDR:client_ip SPACE LD SPACE LD SPACE '[' TIMESTAMP('dd/MMM/yyyy:HH:mm:ss'):ts SPACE LD ']' SPACE '\"' LD:method SPACE LD:path SPACE LD '\"' SPACE INT:status_code SPACE INT:bytes"

// Parse key-value pair
| parse content, "LD 'error_code=' INT:error_code"

// Parse JSON content
| parse content, "JSON:parsed_json"
| fieldsFlatten parsed_json
```

---

## Ordering Commands

### sort
Sorts the records. Default order is ascending. Case-sensitive.
For heterogeneous data, sort order by type: boolean < long/double < binary < string < timestamp < duration < timeframe < uid < ip < array < record.
```
| sort timestamp desc
| sort value asc
| sort host.name asc, timestamp desc
```

Best practice: Place `sort` at the end of the query for performance.

### limit
Limits the number of returned records.
```
| limit 100
```

Best practice: Do not use `limit` before aggregation unless intentional — it will produce wrong aggregates.

---

## Structuring Commands

### expand
Expands an array into separate records — one row per array element.
```
| expand tags
| expand a, limit: 2

data record(a = array(1, 2), b = "DQL"),
     record(a = array(3, 4, 5), b = "Dynatrace Query Language")
| expand a, limit: 2
```

### fieldsFlatten
Extracts fields from a nested record into flat columns.
```
| fieldsFlatten nested_record
| fieldsFlatten nested_record, prefix: "flat_"
```

---

## Aggregation Commands

### summarize
Groups records and aggregates them.

Full syntax:
```
summarize [field =] aggregation, ... [, by: {[field =] expression, ...}]
```

If summarize has no input records and no `by:` clause, it still returns a single record.

```
| summarize count(), by:{host.name}
| summarize avg(value), max(value), min(value), by:{host.name}
| summarize count(), by:{bin(timestamp, 5m)}
| summarize percentile(duration, 95), by:{service.name}
| summarize event_count = count(), by:{country=client.loc_cc, customer}
```

### fieldsSummary
Calculates the cardinality of field values.
```
| fieldsSummary host.name, service.name
```

---

## Correlation and Join Commands

### append
Appends records from a sub-query (union operation).
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
| append [timeseries avg(dt.host.memory.usage), by:{dt.entity.host}]
```

### join
Joins records from source and sub-query. Default is inner join.

Full syntax:
```
join [subquery], on:{field1, field2}, fields:{field1, field2}
    [, kind:inner|leftOuter|outer]
    [, prefix:"right."]
    [, executionOrder:auto|leftFirst|rightFirst]
```

Join types:
- `inner` (default) — only matching records from both sides
- `leftOuter` — all records from left, matching from right (unmatched right fields are null)
- `outer` — all records from both sides

```
// Inner join (default)
timeseries curVal = avg(dt.host.cpu.usage), by:{dt.entity.host}
| join [timeseries prevWeek = avg(dt.host.cpu.usage), by:{dt.entity.host}, shift:-7d],
    on:{dt.entity.host}, fields:{prevWeek}

// Left outer join
fetch dt.entity.host
| join [fetch dt.entity.process_group_instance | fields host=runs_on, pgName=entity.name],
    on:{id}, leftFields:{id, entity.name}, rightFields:{host, pgName},
    kind:leftOuter
```

### lookup
Adds fields from a subquery by matching a source field to a lookup field.
Only returns the first match.

Full syntax:
```
lookup [subquery], sourceField:field, lookupField:field
    [, prefix:"prefix_"]
    [, fields:{field1, field2}]
    [, executionOrder:auto|leftFirst|rightFirst]
```

```
// Enrich metrics with entity names
timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
| fields entity.name, usage

// Lookup from a lookup table
| lookup [load dt.lookup.my_table], sourceField:key, lookupField:id, prefix:"lkp_"
```

### joinNested
Adds matching results from sub-query as an array of nested records.
Useful when you want to preserve one-to-many relationships without expanding rows.

```
fetch dt.entity.process_group
| joinNested [fetch dt.entity.service | fields id, entity.name, runs_on],
    on:{id}, leftFields:{id}, rightFields:{runs_on},
    fields:{services = record(id, entity.name)}
```

---

## Smartscape Commands

### smartscapeNodes
Loads Smartscape topology nodes.
```
smartscapeNodes type:HOST
smartscapeNodes type:SERVICE
smartscapeNodes type:*
```

### smartscapeEdges
Loads Smartscape topology edges.
```
smartscapeEdges type:*
```

### traverse
Traverses source nodes to target nodes in a specified direction.

---

## Aggregation Functions
Used with `summarize`, `makeTimeseries`, and `timeseries`:
```
count()                        // count records
countIf(condition)             // count records matching condition
sum(field)                     // sum values
avg(field)                     // average
min(field)                     // minimum (works on numbers, strings, timestamps, durations, booleans)
max(field)                     // maximum (works on numbers, strings, timestamps, durations, booleans)
percentile(field, 95)          // nth percentile
median(field)                  // 50th percentile (median)
stddev(field)                  // standard deviation
variance(field)                // variance (returns double)
collectDistinct(field)         // collect unique values into array (NOT for makeTimeseries)
collectArray(field)            // collect values into array (NOT for makeTimeseries)
countDistinct(field)           // count unique values (legacy — use countDistinctExact or countDistinctApprox)
countDistinctApprox(field)     // approximate unique count (faster, for large datasets)
countDistinctExact(field)      // exact unique count (up to 1M values)
correlation(field1, field2)    // Pearson correlation coefficient
takeFirst(field)               // first non-null value in existing order
takeLast(field)                // last non-null value in existing order
takeAny(field)                 // any value in group (non-deterministic, for record types)
takeMax(field)                 // value associated with max of another field
takeMin(field)                 // value associated with min of another field
```

IMPORTANT: `makeTimeseries` only accepts aggregation functions that return numbers.
Do NOT use collectDistinct, collectArray with makeTimeseries.

## String Functions
```
contains(field, "text")              // substring match (case-sensitive)
startsWith(field, "prefix")          // prefix match
endsWith(field, "suffix")            // suffix match
matchesPhrase(field, "text")         // phrase match using token matchers (optimized for log search)
matchesValue(field, "pattern")       // pattern match with wildcards (* and ?)
lower(field)                         // lowercase
upper(field)                         // uppercase
trim(field)                          // remove leading/trailing whitespace
trimStart(field)                     // remove leading whitespace
trimEnd(field)                       // remove trailing whitespace
substring(field, start, end)         // extract substring (start inclusive, end exclusive)
indexOf(field, "text")               // find position of substring (-1 if not found)
replace(field, "old", "new")         // replace exact substring matches
replaceAll(field, "DPL_pattern", "new")  // replace all substrings matching DPL pattern
replacePattern(field, "regex", "new")    // replace using regex pattern
concat(field1, field2, ...)          // concatenate strings
strlen(field)                        // string length
splitString(field, "delimiter")      // split string into array
```

## Math Functions
```
abs(value)                     // absolute value
ceil(value)                    // smallest integer >= value
floor(value)                   // largest integer <= value
round(value, decimals)         // round to N decimal places
pow(base, exponent)            // power
sqrt(value)                    // square root
log(value)                     // natural logarithm (base e)
log10(value)                   // base-10 logarithm
exp(value)                     // e^x (exponential function)
```

## Conditional Functions
```
if(condition, then_value, else_value)    // conditional expression
coalesce(field1, field2, default)        // first non-null value
in(field, "val1", "val2", "val3")        // membership test (inline values)
in(field, {"val1", "val2", "val3"})      // membership test (set syntax)
isNull(field)                            // true if field is null
isNotNull(field)                         // true if field is not null
isTrueOrNull(expression)                 // true if expression is true or null
```

## Array Functions
```
array(1, 2, 3)                 // create array literal
arraySize(field)               // number of elements
arrayConcat(arr1, arr2)        // merge arrays (skips nulls and non-array inputs)
arrayDistinct(field)           // unique elements (sorted: numbers ascending, strings lexicographic)
arrayFirst(field)              // first non-null element
arrayLast(field)               // last non-null element
arrayContains(field, val)      // check if value in array
arraySlice(field, start, end)  // sub-array
arrayRemoveNulls(field)        // remove null elements
arraySort(field)               // sort array elements
```

## Time Functions
```
now()                                   // current timestamp (fixed at query start)
bin(timestamp, 5m)                      // bucket timestamps into intervals
start()                                 // start timestamp of timeseries bucket
end()                                   // end timestamp of timeseries bucket
duration(amount, unit)                  // create duration from amount and unit
formatTimestamp(ts, format, tz, locale) // format timestamp as string (Java DateTimeFormatter patterns)
toTimestamp(field)                      // convert to timestamp
timestampFromMillis(ms)                 // timestamp from Unix epoch milliseconds
timestampFromNanos(ns)                  // timestamp from Unix epoch nanoseconds
timestampFromSeconds(s)                 // timestamp from Unix epoch seconds
getHour(timestamp)                      // extract hour (0-23)
getMinute(timestamp)                    // extract minute (0-59)
getDay(timestamp)                       // extract day of month (1-31)
getDayOfWeek(timestamp)                 // day of week (1=Monday, 7=Sunday)
getDayOfYear(timestamp)                 // day of year (1-366)
getMonth(timestamp)                     // extract month (1-12)
getYear(timestamp)                      // extract year
timeframe(from:ts, to:ts)              // create explicit timeframe
timeframeStart(tf)                      // extract start from timeframe
timeframeEnd(tf)                        // extract end from timeframe
```

Time unit suffixes: `s` (second), `m` (minute), `h` (hour), `d` (day), `w` (week), `M` (month), `q` (quarter), `y` (year)

## General Functions
```
exists(field)                          // true if field exists on the record
record(key1=val1, key2=val2)           // create a record (key-value structure)
typeof(expression)                     // returns the data type name as string
```

## Entity Functions
```
entityName(entityId)                   // returns the display name of an entity
entityAttr(entityId, "attribute")      // returns an attribute value for an entity
classicEntitySelector("selector")      // returns entities matching a classic entity selector string
```

## Cryptographic/Hash Functions
```
crc32(field)                           // CRC32 hash of string
md5(field)                             // MD5 hash of string
sha1(field)                            // SHA-1 hash of string
sha256(field)                          // SHA-256 hash of string
sha512(field)                          // SHA-512 hash of string
```

## Network/IP Functions
```
ipAddr(string)                         // create IP address from string
ipInSubnet(ip, "subnet/mask")          // check if IP is in subnet
ipIsPrivate(ip)                        // check if IP is private (RFC 1918)
ipIsPublic(ip)                         // check if IP is public
ipIsLoopback(ip)                       // check if IP is loopback
ipIsLinkLocal(ip)                      // check if IP is link-local
ipMask(ip, prefixLength)              // mask IP address to prefix length
isIpv4(value)                          // check if value is IPv4
isIpv6(value)                          // check if value is IPv6
```

## Conversion/Casting Functions
```
toBoolean(value)                       // convert to boolean (0=false, other numbers=true)
toLong(value)                          // convert to long integer
toDouble(value)                        // convert to double
toString(value)                        // convert to string representation
toTimestamp(value)                     // convert to timestamp
toDuration(value)                      // convert to duration
toIp(value)                            // convert string to IP address
toArray(value)                         // returns value if it is an array
toRecord(value)                        // convert to record
```

## Encoding Functions
```
encodeBase64(value)                    // encode string/binary to Base64
decodeBase64ToString(value)            // decode Base64 to plain string
decodeBase64ToBinary(value)            // decode Base64 to binary data
```

---

## Operators

### Comparison Operators
```
==      // equals (tri-state: if either side is null, result is null)
!=      // not equals (tri-state)
>       // greater than
>=      // greater than or equal
<       // less than
<=      // less than or equal
```

### Logical Operators (tri-state boolean: true, false, null)
```
and     // logical AND (null AND false = false, null AND true = null)
or      // logical OR (null OR true = true, null OR false = null)
not     // logical NOT (not null = null)
```

### Arithmetic Operators
```
+       // addition
-       // subtraction
*       // multiplication
/       // division (long/long = long with truncation; use toDouble() for fractional results)
%       // modulo
```

### Pattern Matching Operator
```
~       // case-insensitive wildcard match (returns boolean)
        // Example: | filter host.name ~ "prod*web*"
```

### Timestamp Alignment Operator
```
@       // align/round down timestamp to time unit
        // Example: | fieldsAdd aligned = timestamp @ 1h
```

### Assignment Operator
```
=       // assigns a name to a computed field
        // Example: | summarize error_count = count(), by:{host.name}
```

### Array Element Access
```
[]      // element-wise array operation (for timeseries array results)
        // Example: | fieldsAdd available = 100 - cpu[]
```

---

## Data Types
DQL is strongly typed. Tri-state boolean logic applies: comparisons with null produce null.

- **Boolean**: `true`, `false` (null is a third state in logical operations)
- **Long**: signed 64-bit integer (-2^63 to 2^63-1)
- **Double**: 64-bit IEEE 754 floating point
- **String**: text (always in double quotes: `"value"`)
- **Timestamp**: point in time with nanosecond precision
- **Duration**: amount + time unit (e.g., `5m`, `1h`, `7d`)
- **Timeframe**: start and end timestamps
- **Array**: ordered collection of values
- **Record**: nested key-value structure
- **IP address**: IPv4 or IPv6
- **Binary**: raw binary data
- **UID**: unique identifier

---

## Complete List of Valid Starting Commands
A DQL query MUST begin with one of these (no pipe before them):
- `fetch` — load logs, events, bizevents, spans, entities
- `timeseries` — load and aggregate metric data
- `metrics` — list available metric keys
- `data` — generate inline sample data
- `load` — load lookup table data
- `smartscapeNodes` — load topology nodes
- `smartscapeEdges` — load topology edges
- `describe` — show schema for a data object

Everything else (filter, summarize, fields, sort, etc.) is a PIPE command
that MUST follow a starting command with `|`.

## Complete List of Pipe Commands
These commands MUST be preceded by `|`:
- `filter` — keep matching records
- `filterOut` — remove matching records
- `search` — case-insensitive text search
- `fields` — select/compute fields
- `fieldsAdd` — add/replace fields
- `fieldsKeep` — keep existing fields only
- `fieldsRemove` — drop fields
- `fieldsRename` — rename fields
- `fieldsFlatten` — flatten nested records
- `fieldsSummary` — field cardinality stats
- `sort` — order records
- `limit` — cap record count
- `summarize` — group and aggregate
- `dedup` — deduplicate records
- `parse` — extract fields with DPL
- `expand` — explode array into rows
- `makeTimeseries` — chart non-metric data over time
- `append` — union with sub-query
- `join` — join with sub-query
- `lookup` — enrich from sub-query/lookup table
- `joinNested` — join as nested array
- `traverse` — traverse Smartscape topology

## Common Metric Keys
```
// Host CPU
dt.host.cpu.usage                     // overall CPU usage %
dt.host.cpu.system                    // system/kernel CPU %
dt.host.cpu.user                      // user-space CPU %
dt.host.cpu.idle                      // idle CPU %
dt.host.cpu.iowait                    // I/O wait CPU %
dt.host.cpu.steal                     // steal CPU % (VMs)

// Host Memory
dt.host.memory.usage                  // memory usage %
dt.host.memory.available              // available memory bytes
dt.host.memory.used                   // used memory bytes

// Host Disk
dt.host.disk.usage                    // disk usage %
dt.host.disk.io.read                  // disk read bytes
dt.host.disk.io.write                 // disk write bytes
dt.host.disk.iops.read                // disk read IOPS
dt.host.disk.iops.write               // disk write IOPS

// Host Network
dt.host.network.io.receive            // network bytes received
dt.host.network.io.transmit           // network bytes transmitted
dt.host.network.packets.receive       // network packets received
dt.host.network.packets.transmit      // network packets transmitted

// Service
dt.service.request.count              // request count
dt.service.request.response_time      // response time
dt.service.request.failure_count      // failure count
dt.service.request.failure_rate       // failure rate

// Containers
dt.containers.cpu.usage               // container CPU usage
dt.containers.memory.usage            // container memory usage
dt.containers.memory.resident_set_size // container RSS

// Kubernetes
dt.kubernetes.node.cpu_allocatable    // K8s node allocatable CPU
dt.kubernetes.node.memory_allocatable // K8s node allocatable memory
dt.kubernetes.container.cpu_usage     // K8s container CPU
dt.kubernetes.container.memory_usage  // K8s container memory
dt.kubernetes.workload.requests_total // K8s workload request count
```

Discover more metrics: `metrics | filter contains(metric.key, "keyword")`
