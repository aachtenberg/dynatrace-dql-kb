# Metric Keys Reference
# Populated from: metrics | sort metric.key asc

## How to populate this file
Run in Dynatrace Notebooks:
```
metrics | sort metric.key asc
```
Copy the full output and paste it below, replacing this placeholder section.

You can also export subsets:
```
metrics | filter startsWith(metric.key, "dt.host.") | sort metric.key asc
metrics | filter startsWith(metric.key, "dt.service.") | sort metric.key asc
metrics | filter startsWith(metric.key, "dt.kubernetes.") | sort metric.key asc
```

---

<!-- Paste your metrics output below this line -->
