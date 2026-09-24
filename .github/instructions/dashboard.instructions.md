---
applyTo: "**/*dashboard*.json,**/*dashboard*.md"
---

# Dynatrace Grail Dashboard JSON Instructions

When generating Dynatrace dashboard JSON, use the NEW Grail/Platform format (NOT Classic).

## Top-Level Structure
```json
{
  "version": 15,
  "variables": [],
  "tiles": {
    "0": { ... },
    "1": { ... }
  },
  "layouts": {
    "0": { "x": 0, "y": 0, "w": 24, "h": 14, "tileId": "0" }
  }
}
```

`version` is required (use 15+). `tiles` keys are string IDs. `layouts` maps to tiles by `tileId`.

## Grid System
- Full width = 24 columns
- `x`, `y`: position (columns from left, rows from top)
- `w`, `h`: size in grid units

## Tile Types

**Data tile — threshold table:**
```json
{
  "type": "data",
  "title": "Hosts above 90% CPU",
  "query": "timeseries usage=avg(dt.host.cpu.usage, scalar:true), by:{dt.entity.host}, from:-1h | filter usage > 90",
  "visualization": "table",
  "subType": "dql"
}
```

**Data tile — line chart.** No `scalar:true`. Kubernetes container metrics use `k8s.namespace.name`, not the namespace entity id.
```json
{
  "type": "data",
  "title": "Container CPU by namespace",
  "query": "timeseries avg(dt.kubernetes.container.cpu_usage), by:{k8s.namespace.name}, from:-1h",
  "visualization": "lineChart",
  "subType": "dql"
}
```

**Markdown tile:**
```json
{
  "type": "markdown",
  "title": "",
  "content": "## Section Header\nDescription text here."
}
```

## Visualization Types
`"table"`, `"lineChart"`, `"barChart"`, `"areaChart"`, `"pieChart"`, `"donutChart"`,
`"singleValue"`, `"honeycomb"`, `"heatmap"`, `"histogram"`, `"gauge"`, `"topList"`,
`"map"`, `"graph"`, `"davisAnalysis"`

## DQL in Queries
The `query` string is DQL, and it has to carry every constraint from the request.

- Metrics use `timeseries`, never `fetch`.
- `by:{...}` always has curly braces.
- A time window goes on the `timeseries` command: `from:-1h`.
- A threshold is a `filter` on a named scalar: `scalar:true`, then `| filter usage > 90`.
- `fetch logs` for logs. Quote string values.
- Kubernetes container metrics: `by:{k8s.namespace.name}`. Not an entity id.

## Classic vs New — DO NOT MIX
If you see `tileType`, `bounds`, `filterConfig`, or metric selectors like
`builtin:host.cpu.usage:splitBy(...)` — that's the CLASSIC format. Do not use it.
The new format uses `type`, `query`, `visualization`, and grid-based `layouts`.

## Terraform
Use `dynatrace_document` (NOT `dynatrace_dashboard` which is Classic):
```hcl
resource "dynatrace_document" "dashboard" {
  type    = "dashboard"
  name    = "My Dashboard"
  private = false
  content = file("${path.module}/dashboard.json")
}
```
