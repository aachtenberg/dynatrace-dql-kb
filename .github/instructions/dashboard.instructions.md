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

**Data tile (DQL query):**
```json
{
  "type": "data",
  "title": "CPU Usage",
  "query": "timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}",
  "visualization": "lineChart",
  "subType": "dql",
  "davis": { "enabled": false, "davisVisualization": { "isAvailable": true } },
  "visualizationSettings": { "thresholds": [], "chartSettings": { "gapPolicy": "connect" } },
  "queryConfig": { "version": "", "additionalFilters": {}, "selectArray": [] }
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
All `query` fields use DQL syntax. Follow the DQL rules from copilot-instructions.md.
Metrics use `timeseries`, logs use `fetch logs`, etc.

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
