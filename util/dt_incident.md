# Incident brief

A utility, separate from the knowledge base and the MCP image. It resolves a ticket's name to a real entity, then writes a markdown note an L2 engineer can paste back: open Davis problems, a baseline comparison, error-log templates, events from just before the window, and for a service the Smartscape callers and callees. The Python script reuses `dt_fetch.py`'s Grail client and `.env`. Stdlib only — no virtualenv and no pip install. `util/dt_incident.sh` runs from the repo root and forwards every argument.

```bash
./util/dt_incident.sh resolve "payments-api"
./util/dt_incident.sh brief "payments-api"
./util/dt_incident.sh brief P-12345
./util/dt_incident.sh brief --entity-id SERVICE-ABCDEF1234567890 --window 6h
./util/dt_incident.sh brief "prod/payments" --out /tmp/brief.md
./util/dt_incident.sh --help
```

`resolve` only looks up entities. `brief` picks one and writes the note to stdout, or to `--out`. The note contains real names. Don't commit it.

## What it looks up

| Input | What happens |
|-------|----------------|
| A name | Hosts, services, process groups, process group instances, Kubernetes workloads, and clusters. An exact-name query runs first, then a contains query, so the exact row is not crowded out by similar names. |
| `namespace/workload` | The namespace has to match as well. A same-named workload in another namespace is listed as `other-ns`. |
| `HOST-…`, `SERVICE-…`, and the other classic ids | Lookup by id. |
| `P-12345` | `brief` only. Reads that Davis problem and focuses one affected entity: service, then workload, then host. |

When several names tie, `brief` prints the list and exits 3. Re-run with `--pick N`, using the numbers from `resolve` or from that list. `--type service` (or `host`, `workload`, `process_group`, `process_group_instance`, `k8s_cluster`) restricts the search.

## What the note contains

Signals cover `--window` (default `1h`), compared with the same length of time yesterday (`shift:-24h`) and last week (`shift:-168h`). Grail does not accept a calendar day in `shift:`.

| Section | For | Query shape |
|---------|-----|-------------|
| Problems | Every entity | Active Davis problems on that id, plus ones that closed inside the window. Lookback `--problems-from` (default `7d`). |
| Signals | Service | Request count, failure rate, average response time. Response time is stored in microseconds and shown in milliseconds. |
| Signals | Host | CPU, memory, disk used percent, availability. Availability is a ratio on current tenants (1 means up) and is shown as a percentage. |
| Signals | Workload | Container CPU, memory working set, and pods with restarts. |
| Signals | Cluster | `dt.kubernetes.cluster.readyz`. |
| Pod restarts | Service or process whose name exactly matches one workload | `dt.kubernetes.container.restarts` for that workload. |
| Error logs | Every entity | Up to 200 lines, then rough templates (numbers, hex, and UUIDs collapsed). |
| Change window | Every entity | Events in the `--change-before` interval (default `30m`) immediately before the signal window. |
| Blast radius | Service | Smartscape `calls` edges, callers and callees, with request count and failure rate for the current window. |

A section Grail rejects is skipped. The rest of the note is still written, and every query, including the failed ones, is at the bottom.

Host disk uses `dt.host.disk.used.percent`, which is the key `dt_fetch.py` records. Service request keys are the built-in `dt.service.request.*` metrics. A tenant without those keys gets a skip line instead of an empty table.

## Cost

Entity lookups are small. The expensive reads are logs and events, capped at `--scan-limit-gb` (default 5) with `scanLimitGBytes` on the `fetch`. `-1` lifts the cap; that scan is billable. Counts in the log section are inside the sample of at most 200 lines, not a full count of the window.

Names shorter than 4 characters are not used as a log or event text search. Pass an entity id, or a longer name.

Required scopes are the same read scopes as `dt_fetch.py`: `storage:entities:read`, `storage:metrics:read`, `storage:events:read`, `storage:logs:read`, `storage:buckets:read`. Problems use the events read scope.

## Things to know

- The signal window is relative to now. If a problem started earlier than `--window`, the note says so.
- Log lines count as errors when the level is ERROR, FATAL, SEVERE, or CRITICAL, or when the text contains those words, or `Exception` (including `NullPointerException`). Field names such as `loglevel` vary by tenant; a missing field yields no level match and the text check still runs.
- Call edges follow [docs/smartscape_calls.md](../docs/smartscape_calls.md): `calls` with this service as the target are callers, and as the source are callees. There is no `called_by` edge. `toSmartscapeId()` is tried along with the classic id.
- A problem that affects several entities of one kind does not pick for you. `--pick` does.
- Exit 0 is a note, or a resolve list. Exit 1 is no match or a query the lookup itself could not run. Exit 3 is an ambiguous name.
