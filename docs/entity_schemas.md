# Entity and Data Source Schemas
# Populated from: fetch <source> | limit 1

## How to populate this file
Run each query in Dynatrace Notebooks. Each returns one record showing all
available fields. Copy the field names (column headers) into the sections below.

---

## Host Entity (dt.entity.host)
Query: `fetch dt.entity.host | limit 1`

<!-- Paste field names here -->

## Service Entity (dt.entity.service)
Query: `fetch dt.entity.service | limit 1`

<!-- Paste field names here -->

## Process Group (dt.entity.process_group)
Query: `fetch dt.entity.process_group | limit 1`

<!-- Paste field names here -->

## Process Group Instance (dt.entity.process_group_instance)
Query: `fetch dt.entity.process_group_instance | limit 1`

<!-- Paste field names here -->

## Cloud Application / K8s Workload (dt.entity.cloud_application)
Query: `fetch dt.entity.cloud_application | limit 1`

<!-- Paste field names here -->

## Kubernetes Cluster (dt.entity.kubernetes_cluster)
Query: `fetch dt.entity.kubernetes_cluster | limit 1`

<!-- Paste field names here -->

## Logs
Query: `fetch logs | limit 1`

<!-- Paste field names here -->

## Events
Query: `fetch events | limit 1`

<!-- Paste field names here -->

## Spans
Query: `fetch spans | limit 1`

<!-- Paste field names here -->

## Business Events
Query: `fetch bizevents | limit 1`

<!-- Paste field names here -->

---

## All Available Entity Types
Query: `fetch dt.system.data_objects | filter startsWith(name, "dt.entity.") | fields name | sort name asc`

<!-- Paste entity type names here -->
