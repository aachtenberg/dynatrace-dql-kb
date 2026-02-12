# Dynatrace New Dashboard (Grail) JSON Schema
# This is the NEW dashboard format (Dashboards app), NOT the Classic dashboard format.
# The Classic format uses a completely different schema with tile_type, bounds, etc.

## Overview
New Dynatrace dashboards (Grail/Platform) are stored as JSON documents.
They can be exported/imported via the UI or managed via the Document API
(or Terraform using the `dynatrace_document` resource type, NOT `dynatrace_dashboard`).

## Top-Level Structure
```json
{
  "version": 15,
  "variables": [],
  "tiles": {
    "<tile_id>": { ... },
    "<tile_id>": { ... }
  },
  "layouts": {
    "<layout_id>": { ... }
  }
}
```

### version
Integer. The dashboard schema version. Currently version 15 or higher.
This is NOT optional — the dashboard won't load without it.

### variables
Array of variable definitions for dashboard-level variables (filters).
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

IMPORTANT: As of Dashboards app version 1.10.0+, all variable values from query,
code, and CSV variables are returned as strings. If your query expects a number,
you may need explicit type conversion.

### tiles
Object with string keys (tile IDs like "1", "2", "3" etc.) mapped to tile objects.
Each tile represents one section of the dashboard.

### layouts
Object defining the spatial arrangement of tiles.

---

## Tile Types

### Data Tile (DQL Query)
The most common tile type. Runs a DQL query and visualizes the result.
```json
{
  "type": "data",
  "title": "CPU Usage by Host",
  "query": "timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}",
  "davis": {
    "enabled": false,
    "davisVisualization": {
      "isAvailable": true
    }
  },
  "visualization": "lineChart",
  "visualizationSettings": {
    "thresholds": [],
    "chartSettings": {
      "gapPolicy": "connect",
      "circleChartSettings": {
        "groupingThresholdType": "relative",
        "groupingThreshold": 0,
        "valueType": "relative"
      },
      "categoryOverrides": {},
      "fieldMapping": {
        "timestamp": "timeframe",
        "leftAxisValues": [],
        "leftAxisDimensions": [],
        "rightAxisValues": [],
        "rightAxisDimensions": [],
        "fields": []
      },
      "categoryColorAssignmentRules": [],
      "colorPalette": "categorical"
    },
    "singleValue": {
      "showLabel": true,
      "label": "",
      "prefixIcon": "",
      "recordField": "usage",
      "autoscale": true,
      "alignment": "center",
      "colorThresholdTarget": "value"
    },
    "table": {
      "rowDensity": "condensed",
      "enableSparklines": false,
      "hiddenColumns": [],
      "lineWrapIds": [],
      "firstVisibleRowIndex": 0,
      "columnWidths": {}
    },
    "unitsOverrides": [],
    "honeycomb": {
      "shape": "hexagon",
      "legend": {
        "hidden": false,
        "position": "auto"
      },
      "dataMappings": {},
      "colorMode": "color-palette",
      "colorPalette": "blue"
    }
  },
  "queryConfig": {
    "version": "",
    "additionalFilters": {},
    "selectArray": []
  },
  "subType": "dql"
}
```

### Markdown Tile
Static content formatted in markdown.
```json
{
  "type": "markdown",
  "title": "",
  "content": "## Dashboard Title\n\nThis dashboard shows **host health** metrics.\n\n[Link to docs](https://docs.dynatrace.com)"
}
```

### Code Tile
Runs custom JavaScript via Dynatrace functions.
```json
{
  "type": "code",
  "title": "Custom Data",
  "code": "// JavaScript code here",
  "visualization": "table",
  "visualizationSettings": { ... }
}
```

---

## Visualization Types
The `visualization` field on a data tile accepts these values:

- `"table"` — Tabular data display
- `"lineChart"` — Line chart (time series)
- `"barChart"` — Bar chart
- `"areaChart"` — Area chart
- `"pieChart"` — Pie chart
- `"donutChart"` — Donut chart
- `"singleValue"` — Large single number display
- `"honeycomb"` — Honeycomb/hexagon grid
- `"heatmap"` — Heatmap visualization
- `"histogram"` — Histogram
- `"map"` — Geographic map
- `"gauge"` — Gauge visualization
- `"topList"` — Top-N list
- `"graph"` — Graph/network visualization
- `"davisAnalysis"` — Davis AI analysis visualization

Not all visualization types are available for all query results.

---

## Layout Structure
```json
"layouts": {
  "0": {
    "x": 0,
    "y": 0,
    "w": 24,
    "h": 14,
    "tileId": "1"
  },
  "1": {
    "x": 0,
    "y": 14,
    "w": 12,
    "h": 10,
    "tileId": "2"
  },
  "2": {
    "x": 12,
    "y": 14,
    "w": 12,
    "h": 10,
    "tileId": "3"
  }
}
```

The dashboard uses a grid system:
- `x`: horizontal position (columns from left)
- `y`: vertical position (rows from top)
- `w`: width in grid units (full width = 24)
- `h`: height in grid units
- `tileId`: references a tile in the `tiles` object

---

## Complete Working Example

A minimal but complete dashboard with a DQL query tile and a markdown header:

```json
{
  "version": 15,
  "variables": [],
  "tiles": {
    "0": {
      "type": "markdown",
      "title": "",
      "content": "## Host Overview"
    },
    "1": {
      "type": "data",
      "title": "CPU Usage",
      "query": "timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}",
      "davis": {
        "enabled": false,
        "davisVisualization": {
          "isAvailable": true
        }
      },
      "visualization": "lineChart",
      "visualizationSettings": {
        "thresholds": [],
        "chartSettings": {
          "gapPolicy": "connect",
          "circleChartSettings": {
            "groupingThresholdType": "relative",
            "groupingThreshold": 0,
            "valueType": "relative"
          },
          "categoryOverrides": {},
          "fieldMapping": {
            "timestamp": "timeframe",
            "leftAxisValues": [],
            "leftAxisDimensions": [],
            "rightAxisValues": [],
            "rightAxisDimensions": [],
            "fields": []
          },
          "categoryColorAssignmentRules": [],
          "colorPalette": "categorical"
        },
        "singleValue": {
          "showLabel": true,
          "label": "",
          "prefixIcon": "",
          "autoscale": true,
          "alignment": "center",
          "colorThresholdTarget": "value"
        },
        "table": {
          "rowDensity": "condensed",
          "enableSparklines": false,
          "hiddenColumns": [],
          "lineWrapIds": [],
          "firstVisibleRowIndex": 0,
          "columnWidths": {}
        },
        "unitsOverrides": [],
        "honeycomb": {
          "shape": "hexagon",
          "legend": {
            "hidden": false,
            "position": "auto"
          },
          "dataMappings": {},
          "colorMode": "color-palette",
          "colorPalette": "blue"
        }
      },
      "queryConfig": {
        "version": "",
        "additionalFilters": {},
        "selectArray": []
      },
      "subType": "dql"
    },
    "2": {
      "type": "data",
      "title": "Error Logs (Last Hour)",
      "query": "fetch logs\n| filter timestamp >= now() - 1h\n| filter status == \"ERROR\"\n| summarize error_count = count(), by:{service.name}\n| sort error_count desc",
      "davis": {
        "enabled": false,
        "davisVisualization": {
          "isAvailable": true
        }
      },
      "visualization": "barChart",
      "visualizationSettings": {
        "thresholds": [],
        "chartSettings": {
          "gapPolicy": "connect",
          "circleChartSettings": {
            "groupingThresholdType": "relative",
            "groupingThreshold": 0,
            "valueType": "relative"
          },
          "categoryOverrides": {},
          "colorPalette": "categorical"
        },
        "singleValue": {
          "showLabel": true,
          "label": "",
          "prefixIcon": "",
          "autoscale": true,
          "alignment": "center",
          "colorThresholdTarget": "value"
        },
        "table": {
          "rowDensity": "condensed",
          "enableSparklines": false,
          "hiddenColumns": [],
          "lineWrapIds": [],
          "firstVisibleRowIndex": 0,
          "columnWidths": {}
        },
        "unitsOverrides": [],
        "honeycomb": {
          "shape": "hexagon",
          "legend": {
            "hidden": false,
            "position": "auto"
          },
          "dataMappings": {},
          "colorMode": "color-palette",
          "colorPalette": "blue"
        }
      },
      "queryConfig": {
        "version": "",
        "additionalFilters": {},
        "selectArray": []
      },
      "subType": "dql"
    }
  },
  "layouts": {
    "0": {
      "x": 0,
      "y": 0,
      "w": 24,
      "h": 3,
      "tileId": "0"
    },
    "1": {
      "x": 0,
      "y": 3,
      "w": 24,
      "h": 14,
      "tileId": "1"
    },
    "2": {
      "x": 0,
      "y": 17,
      "w": 24,
      "h": 10,
      "tileId": "2"
    }
  }
}
```

---

## Terraform Deployment

Use `dynatrace_document` (NOT `dynatrace_dashboard` which is for Classic):
```hcl
resource "dynatrace_document" "my_dashboard" {
  type    = "dashboard"
  name    = "My Dashboard"
  private = false  # IMPORTANT: without this, only the owner can see it
  content = file("${path.module}/my_dashboard.json")
}
```

Required Terraform provider config:
```hcl
provider "dynatrace" {
  dt_env_url               = var.dynatrace_env_url
  dt_api_token             = var.dynatrace_api_token
  automation_client_id     = var.automation_client_id
  automation_client_secret = var.automation_client_secret
}
```

---

## Classic vs New Dashboard Format

DO NOT confuse the two formats. They are completely different:

### Classic (LEGACY — `dynatrace_dashboard` in Terraform):
- Uses `dashboardMetadata`, `tiles` array with `tileType`, `bounds` (top, left, width, height)
- Tile types like: CUSTOM_CHARTING, MARKDOWN, DATA_EXPLORER, etc.
- Metric selectors use the old format: `builtin:host.cpu.usage:splitBy("dt.entity.host")`

### New/Grail (CURRENT — `dynatrace_document` in Terraform):
- Uses `version`, `tiles` object (keyed by string IDs), `layouts` object
- Tile types: `data`, `markdown`, `code`
- Queries use DQL: `timeseries avg(dt.host.cpu.usage), by:{dt.entity.host}`
- Visualizations specified as `visualization` field on each tile

If you see `tileType`, `bounds`, `filterConfig`, or metric selector strings,
you're looking at the CLASSIC format. The new format uses `type`, `query`,
`visualization`, and grid-based `layouts`.
