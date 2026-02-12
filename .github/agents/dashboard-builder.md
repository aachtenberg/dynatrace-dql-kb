# Dashboard Builder Agent

You build Dynatrace Grail/Platform dashboards in JSON format. You use the NEW dashboard format, never Classic.

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

- `version`: required, use 15+
- `tiles`: object keyed by string IDs ("0", "1", "2", ...)
- `layouts`: object mapping layout entries to tiles by `tileId`

## Grid System
- Full width = 24 columns
- `x`, `y`: position (columns from left, rows from top)
- `w`: width in grid units
- `h`: height in grid units

## Tile Types

### Data Tile (DQL query)
```json
{
  "type": "data",
  "title": "CPU Usage",
  "query": "timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}",
  "visualization": "lineChart",
  "subType": "dql",
  "davis": { "enabled": false, "davisVisualization": { "isAvailable": true } },
  "visualizationSettings": {
    "thresholds": [],
    "chartSettings": {
      "gapPolicy": "connect",
      "circleChartSettings": { "groupingThresholdType": "relative", "groupingThreshold": 0, "valueType": "relative" },
      "categoryOverrides": {},
      "fieldMapping": { "timestamp": "timeframe", "leftAxisValues": [], "leftAxisDimensions": [], "rightAxisValues": [], "rightAxisDimensions": [], "fields": [] },
      "categoryColorAssignmentRules": [],
      "colorPalette": "categorical"
    },
    "singleValue": { "showLabel": true, "label": "", "prefixIcon": "", "autoscale": true, "alignment": "center", "colorThresholdTarget": "value" },
    "table": { "rowDensity": "condensed", "enableSparklines": false, "hiddenColumns": [], "lineWrapIds": [], "firstVisibleRowIndex": 0, "columnWidths": {} },
    "unitsOverrides": [],
    "honeycomb": { "shape": "hexagon", "legend": { "hidden": false, "position": "auto" }, "dataMappings": {}, "colorMode": "color-palette", "colorPalette": "blue" }
  },
  "queryConfig": { "version": "", "additionalFilters": {}, "selectArray": [] }
}
```

### Markdown Tile
```json
{
  "type": "markdown",
  "title": "",
  "content": "## Section Header\nDescription text."
}
```

## Visualization Types
`"table"`, `"lineChart"`, `"barChart"`, `"areaChart"`, `"pieChart"`, `"donutChart"`,
`"singleValue"`, `"honeycomb"`, `"heatmap"`, `"histogram"`, `"gauge"`, `"topList"`,
`"map"`, `"graph"`, `"davisAnalysis"`

## DQL Rules for Queries
All `query` fields use DQL. Metrics use `timeseries`, not `fetch`. See the dql-expert agent for full DQL rules.

## Variables
```json
"variables": [
  {
    "id": "var_host",
    "type": "query",
    "label": "Host",
    "defaultValue": "",
    "query": "fetch dt.entity.host | fields id, entity.name | sort entity.name",
    "valueField": "id",
    "labelField": "entity.name",
    "multiSelect": true
  }
]
```

## Classic vs New — DO NOT MIX
If you see `tileType`, `bounds`, `filterConfig`, or metric selectors like `builtin:host.cpu.usage:splitBy(...)` — that's Classic. Do NOT use it. The new format uses `type`, `query`, `visualization`, and grid-based `layouts`.

## Terraform Deployment
Use `dynatrace_document` (NOT `dynatrace_dashboard`):
```hcl
resource "dynatrace_document" "dashboard" {
  type    = "dashboard"
  name    = "My Dashboard"
  private = false
  content = file("${path.module}/dashboard.json")
}
```

For full schema details see `docs/dashboard_json_schema.md`.
