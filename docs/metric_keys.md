# Metric Keys Reference
# Populated from: metrics | sort metricId asc

## How to populate this file
Run in Dynatrace Notebooks:
```
metrics | sort metricId asc
```
Copy the full output and paste it below, replacing this placeholder section.

You can also export subsets:
```
metrics | filter startsWith(metricId, "dt.host.") | sort metricId asc
metrics | filter startsWith(metricId, "dt.service.") | sort metricId asc
metrics | filter startsWith(metricId, "dt.kubernetes.") | sort metricId asc
```

---

<!-- Paste your metrics output below this line -->
