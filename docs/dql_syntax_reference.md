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
metrics | filter contains(metricId, "cpu")

// Get metadata for specific metric
metrics | filter metricId == "dt.host.cpu.usage"
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
Loads data from the specified resource.
```
fetch logs
fetch logs, from:now()-2h, to:now()
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
Loads data from a specified resource. Used with lookup data.
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
Searches for records matching the specified search condition.
```
| search "OutOfMemoryError"
```

### dedup
Removes duplicates from a list of records.
```
| dedup host.name
| dedup host.name, service.name
```

---

## Selection and Modification Commands

### fields
Keeps only specified fields (like SQL SELECT).
```
| fields timestamp, host.name, value
```

### fieldsAdd
Evaluates an expression and appends or replaces a field.
```
| fieldsAdd duration_ms = duration / 1000000
| fieldsAdd status_category = if(status_code >= 500, "server_error",
    if(status_code >= 400, "client_error", "success"))
```

### fieldsKeep
Keeps selected fields (alias behavior similar to fields).
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
Parses a record field and puts the result into one or more fields.
```
| parse content, "LD IPADDR:ip ':' LONG:payload SPACE LD 'HTTP_STATUS' SPACE INT:http_status LD (EOL|EOS)"
| parse content, "JSON:json"
```

---

## Ordering Commands

### sort
Sorts the records.
```
| sort timestamp desc
| sort value asc
| sort host.name asc, timestamp desc
```

### limit
Limits the number of returned records.
```
| limit 100
```

---

## Structuring Commands

### expand
Expands an array into separate records.
```
data record(a = array(1, 2), b = "DQL"),
     record(a = array(3, 4, 5), b = "Dynatrace Query Language")
| expand a, limit: 2
```

### fieldsFlatten
Extracts/flattens fields from a nested record.
```
| fieldsFlatten nested_record, prefix: "flat_"
```

---

## Aggregation Commands

### summarize
Groups records and aggregates them.
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
Appends records from a sub-query.
```
timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}
| append [timeseries avg(dt.host.memory.usage), by:{dt.entity.host}]
```

### join
Joins records from source and sub-query.
```
timeseries curVal = avg(dt.host.cpu.usage), by:{dt.entity.host}
| join [timeseries prevWeek = avg(dt.host.cpu.usage), by:{dt.entity.host}, shift:-7d],
    on:{dt.entity.host}, fields:{prevWeek}
```

### lookup
Adds fields from a subquery by matching fields.
```
fetch logs
| lookup [fetch dt.entity.host | fields id, entity.name],
    sourceField:dt.entity.host, lookupField:id
```

### joinNested
Adds matching results from sub-query as an array of nested records.

---

## Smartscape Commands

### smartscapeNodes
Loads Smartscape nodes.
```
smartscapeNodes type:HOST
smartscapeNodes type:*
```

### smartscapeEdges
Loads Smartscape edges.
```
smartscapeEdges type:*
```

### traverse
Traverses source nodes to target nodes in a specified direction.

---

## Time Functions
```
now()                    // current timestamp
now() - 1h              // 1 hour ago
now() - 30m             // 30 minutes ago
now() - 7d              // 7 days ago
bin(timestamp, 5m)      // bucket timestamps into 5-minute intervals
start()                 // start timestamp of timeseries bucket
end()                   // end timestamp of timeseries bucket
timeframe(from:now()-2h, to:now())  // explicit timeframe
```

Calendar durations: d (day), w (week), M (month), q (quarter), y (year)
Can be used in calculations but not as field values.

## String Functions
```
contains(field, "text")        // substring match (case-sensitive)
startsWith(field, "prefix")    // prefix match
endsWith(field, "suffix")      // suffix match
matchesPhrase(field, "text")   // phrase match in logs (optimized for log search)
matchesValue(field, "pattern") // pattern match with wildcards (* and ?)
lower(field)                   // lowercase
upper(field)                   // uppercase
trim(field)                    // remove leading/trailing whitespace
trimStart(field)               // remove leading whitespace
trimEnd(field)                 // remove trailing whitespace
substring(field, start, length) // extract substring
indexOf(field, "text")         // find position of substring (-1 if not found)
replace(field, "old", "new")   // replace first occurrence
replaceAll(field, "old", "new") // replace all occurrences (NOT regex)
replacePattern(field, "regex", "new") // replace using regex pattern
concat(field1, field2, ...)    // concatenate strings
strlen(field)                  // string length
splitString(field, "delimiter") // split string into array
```

## Math Functions
```
abs(value)                     // absolute value
ceil(value)                    // round up
floor(value)                   // round down
round(value, decimals)         // round to N decimal places
pow(base, exponent)            // power
sqrt(value)                    // square root
log(value)                     // natural logarithm
log10(value)                   // base-10 logarithm
```

## Aggregation Functions
Used with `summarize`, `makeTimeseries`, and `timeseries`:
```
count()                     // count records
countIf(condition)          // count records matching condition
sum(field)                  // sum values
avg(field)                  // average
min(field)                  // minimum
max(field)                  // maximum
percentile(field, 95)       // 95th percentile
median(field)               // 50th percentile (median)
stddev(field)               // standard deviation
variance(field)             // variance
collectDistinct(field)      // collect unique values into array (NOT for makeTimeseries)
collectArray(field)         // collect values into array (NOT for makeTimeseries)
countDistinct(field)        // count unique values
countDistinctApprox(field)  // approximate unique count (faster)
countDistinctExact(field)   // exact unique count (up to 1M)
correlation(field1, field2) // Pearson correlation
takeFirst(field)            // first value in group
takeLast(field)             // last value in group
takeAny(field)              // any value in group (non-deterministic)
takeMax(field)              // value associated with max of another field
takeMin(field)              // value associated with min of another field
```

IMPORTANT: `makeTimeseries` only accepts aggregation functions that return numbers.
Do NOT use collectDistinct, collectArray with makeTimeseries.

## Conditional Functions
```
if(condition, then_value, else_value)
coalesce(field1, field2, default)    // first non-null value
in(field, "val1", "val2", "val3")    // membership test
in(field, {"val1", "val2", "val3"})  // membership test (set syntax)
isNull(field)
isNotNull(field)
```

## Array Functions
```
array(1, 2, 3)             // create array literal
arraySize(field)           // number of elements
arrayConcat(arr1, arr2)    // merge two arrays
arrayDistinct(field)       // unique elements
arrayFirst(field)          // first element
arrayLast(field)           // last element
arrayContains(field, val)  // check if value in array
arraySlice(field, start, end) // sub-array
```

## Timestamp Functions
```
now()                            // current timestamp
toTimestamp(field)               // convert to timestamp
formatTimestamp(field, "pattern") // format timestamp as string
getHour(timestamp)               // extract hour (0-23)
getDay(timestamp)                // extract day of month
getMonth(timestamp)              // extract month (1-12)
getYear(timestamp)               // extract year
getDayOfWeek(timestamp)          // day of week (1=Monday, 7=Sunday)
```

## Comparison Operators
```
==      // equals
!=      // not equals
>       // greater than
>=      // greater than or equal
<       // less than
<=      // less than or equal
```

## Logical Operators
```
and     // logical AND
or      // logical OR
not     // logical NOT
```

## Arithmetic Operators
```
+       // addition
-       // subtraction
*       // multiplication
/       // division
%       // modulo
```

## Data Types
DQL is strongly typed:
- Boolean: true, false
- Long: signed 64-bit integer
- Double: 64-bit floating point
- String: text (always in double quotes: "value")
- Timestamp: point in time with nanosecond precision
- Duration: amount + time unit (e.g., 5m, 1h, 7d)
- Timeframe: start and end timestamps
- Array: collection of same-type items
- Record: nested key-value structure
- IP address: IPv4 or IPv6

Type conversion functions: toBoolean(), toLong(), toDouble(), toString(),
toTimestamp(), toDuration()

---

## Complete List of Valid Starting Commands
A DQL query MUST begin with one of these (no pipe before them):
- `fetch` — load logs, events, bizevents, spans, entities
- `timeseries` — load and aggregate metric data
- `metrics` — list available metric keys
- `data` — generate inline sample data
- `smartscapeNodes` — load topology nodes
- `smartscapeEdges` — load topology edges
- `describe` — show schema for a data object

Everything else (filter, summarize, fields, sort, etc.) is a PIPE command
that MUST follow a starting command with `|`.
