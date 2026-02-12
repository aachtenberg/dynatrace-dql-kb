# Entity Schemas Reference
# Populated from: describe <entity_type>

## How to populate this file
Run each query in Dynatrace Notebooks and paste the output below.

---

## Host Entity (dt.entity.host)
Query: `describe dt.entity.host`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Service Entity (dt.entity.service)
Query: `describe dt.entity.service`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Process Group (dt.entity.process_group)
Query: `describe dt.entity.process_group`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Process Group Instance (dt.entity.process_group_instance)
Query: `describe dt.entity.process_group_instance`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Cloud Application / K8s Workload (dt.entity.cloud_application)
Query: `describe dt.entity.cloud_application`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Kubernetes Cluster (dt.entity.kubernetes_cluster)
Query: `describe dt.entity.kubernetes_cluster`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Logs Schema
Query: `describe logs`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Events Schema
Query: `describe events`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Spans Schema
Query: `describe spans`

| field | type |
|-------|------|
| <!-- paste output here --> |

## Business Events Schema
Query: `describe bizevents`

| field | type |
|-------|------|
| <!-- paste output here --> |

---

## All Available Entity Types
Query: `fetch dt.system.data_objects | filter startsWith(name, "dt.entity.") | fields name | sort name asc`

| name |
|------|
| <!-- paste output here --> |
