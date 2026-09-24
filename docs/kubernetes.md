# Kubernetes container metrics

Group `dt.kubernetes.*` metrics by `k8s.namespace.name`.

Do not group them by `dt.entity.cloud_application_namespace` or `dt.entity.kubernetes_namespace`. Those are entity ids and drop namespaces. `k8s.namespace.name` returned every namespace.

`dt.containers.cpu.usage` returned no rows. Use `dt.kubernetes.container.cpu_usage`.

k3s keeps `kubernetesDistribution` as `KUBERNETES`. Match `contains(kubernetesVersion, "+k3s")`.

## Container CPU by namespace

Chart (no `scalar:true`):

```
timeseries avg(dt.kubernetes.container.cpu_usage), by:{k8s.namespace.name}, from:-1h
```

Table:

```
timeseries cpu=avg(dt.kubernetes.container.cpu_usage, scalar:true), by:{k8s.namespace.name}, from:-1h
| sort cpu desc
```

## Other splits that returned data

`k8s.cluster.name`, `k8s.workload.name`, `k8s.pod.name`, `k8s.node.name`, `k8s.container.name`.

## Restarts

```
timeseries restarts=sum(dt.kubernetes.container.restarts, scalar:true), by:{k8s.namespace.name, k8s.pod.name}, from:-6h
| filter restarts > 0
| sort restarts desc
```

## k3s clusters

```
fetch dt.entity.kubernetes_cluster
| filter contains(kubernetesVersion, "+k3s")
| fields entity.name, kubernetesVersion
```
