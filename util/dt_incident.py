"""
dt_incident.py — Resolve a name to a Dynatrace entity, and write an incident brief.

Uses the same Grail client and .env as dt_fetch.py. Stdlib only.

    ./util/dt_incident.sh resolve "payments-api"
    ./util/dt_incident.sh brief "payments-api"
    ./util/dt_incident.sh brief P-12345
    ./util/dt_incident.sh brief --entity-id SERVICE-ABC --window 6h
    ./util/dt_incident.sh --help

`resolve` prints the entities that match. `brief` picks one and writes a
markdown note: open problems, a baseline comparison, error-log templates,
events from the change window, and (for a service) Smartscape callers and
callees. Every query is in the note. A section that Grail rejects is skipped
and the rest of the note is still written.

The brief contains real entity names. It goes to stdout unless you pass --out.
"""

import argparse
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import dt_fetch

# Longer prefixes first so PROCESS_GROUP_INSTANCE is not read as PROCESS_GROUP.
_ID_KIND = (
    ("PROCESS_GROUP_INSTANCE-", "process_group_instance"),
    ("PROCESS_GROUP-", "process_group"),
    ("CLOUD_APPLICATION-", "workload"),
    ("KUBERNETES_CLUSTER-", "k8s_cluster"),
    ("SERVICE-", "service"),
    ("HOST-", "host"),
)
_LEAD_TS = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s*")
ENTITY_ID = re.compile(
    r"^(?:" + "|".join(prefix[:-1] for prefix, _kind in _ID_KIND) + r")-[0-9A-Za-z]+$",
    re.IGNORECASE)
GENERIC_ID = re.compile(r"^[A-Z][A-Z0-9_]*-[0-9A-F]{8,}$", re.IGNORECASE)
PROBLEM_ID = re.compile(r"^P-\d+$", re.IGNORECASE)
_DURATION = re.compile(r"^(\d+)([smhd])$")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HEX = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_NUM = re.compile(r"\b\d[\d.]*\b")
# Exception is a suffix in Java class names (NullPointerException), so it is not
# a whole word. The others are whole words so "errorless" does not match.
_ERROR_WORD = re.compile(
    r"\b(ERROR|FATAL|SEVERE|CRITICAL)\b|Exception", re.IGNORECASE)

KIND_ORDER = (
    "service",
    "workload",
    "host",
    "process_group",
    "process_group_instance",
    "k8s_cluster",
)

# name_fields are searched and scored. extra_fields are printed, not searched.
# id_field is the dimension logs, events, and metrics use for that entity.
KINDS = {
    "service": {
        "source": "dt.entity.service",
        "name_fields": ("entity.name", "entity.detected_name"),
        "extra_fields": ("serviceType",),
        "id_field": "dt.entity.service",
    },
    "host": {
        "source": "dt.entity.host",
        "name_fields": ("entity.name", "entity.detected_name", "oneAgentCustomHostName"),
        "extra_fields": (),
        "id_field": "dt.entity.host",
    },
    "process_group": {
        "source": "dt.entity.process_group",
        "name_fields": ("entity.name", "entity.detected_name"),
        "extra_fields": (),
        "id_field": "dt.entity.process_group",
    },
    "process_group_instance": {
        "source": "dt.entity.process_group_instance",
        "name_fields": ("entity.name", "entity.detected_name"),
        "extra_fields": ("processType",),
        "id_field": "dt.entity.process_group_instance",
    },
    "workload": {
        "source": "dt.entity.cloud_application",
        "name_fields": ("entity.name",),
        "extra_fields": ("namespaceName", "kubernetesClusterName"),
        "id_field": None,
    },
    "k8s_cluster": {
        "source": "dt.entity.kubernetes_cluster",
        "name_fields": ("entity.name",),
        "extra_fields": ("kubernetesVersion",),
        "id_field": None,
    },
}

# Host disk is dt.host.disk.used.percent in tenant metric keys. The DQL notes
# also mention dt.host.disk.usage, which this tenant's metric list does not have.
HOST_METRICS = (
    ("cpu", "avg(dt.host.cpu.usage, scalar:true)", "cpu %"),
    ("mem", "avg(dt.host.memory.usage, scalar:true)", "memory %"),
    ("disk", "avg(dt.host.disk.used.percent, scalar:true)", "disk %"),
    ("avail", "avg(dt.host.availability, scalar:true)", "availability %"),
)
SERVICE_METRICS = (
    ("total", "sum(dt.service.request.count, scalar:true)", "requests"),
    ("failed", "sum(dt.service.request.failure_count, scalar:true, default:0)", "failed"),
    ("rt", "avg(dt.service.request.response_time, scalar:true)", "avg response"),
)
WORKLOAD_METRICS = (
    ("cpu", "avg(dt.kubernetes.container.cpu_usage, scalar:true)", "cpu usage"),
    ("mem", "avg(dt.kubernetes.container.memory_working_set, scalar:true)", "working set"),
)
CLUSTER_METRICS = (
    ("ready", "avg(dt.kubernetes.cluster.readyz, scalar:true)", "readyz"),
)
WINDOWS = (("current", None), ("yesterday", "24h"), ("last week", "168h"))
_ERROR_LEVELS = {"ERROR", "FATAL", "SEVERE", "CRITICAL"}
_LOG_LEVEL_FIELDS = ("loglevel", "status", "severity", "log.level")
_LOG_TEXT_FIELDS = ("content", "message", "body")


class Ambiguous(Exception):
    def __init__(self, matches):
        self.matches = matches


@dataclass
class Match:
    kind: str
    entity_id: str
    name: str
    score: int
    how: str
    detail: str
    namespace: str = ""


class Grail:
    """Runs DQL and keeps every query, including ones Grail rejected."""

    def __init__(self):
        self.queries = []  # (label, dql, error or None)

    def run(self, label, dql, **kw):
        log(f"  {label}")
        try:
            result = dt_fetch.run_dql_result(dql, **kw)
        except RuntimeError as e:
            self.queries.append((label, dql, one_line(e)))
            raise
        stopped = _scan_note(result)
        if stopped:
            msg = one_line(stopped)
            self.queries.append((label, dql, msg))
            raise RuntimeError(msg)
        self.queries.append((label, dql, None))
        return result.get("records") or []

    def run_soft(self, label, dql, **kw):
        try:
            return self.run(label, dql, **kw), None
        except RuntimeError as e:
            return None, e


def log(msg):
    print(msg, file=sys.stderr)


def one_line(exc, limit=300):
    text = " ".join(str(exc).split())
    return text[:limit]


def dql_str(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_duration(text, label):
    """Return (seconds, token). Token is safe to paste into DQL."""
    m = _DURATION.fullmatch(text.strip())
    if not m or int(m.group(1)) < 1:
        raise SystemExit(
            f"{label} must look like 30m, 1h, or 7d (got {text!r})")
    n = int(m.group(1))
    unit = m.group(2)
    seconds = n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return seconds, f"{n}{unit}"


def scalar(value):
    """Unwrap a one-element timeseries array. None stays None."""
    if isinstance(value, list):
        nums = []
        for item in value:
            got = scalar(item)
            if isinstance(got, (int, float)):
                nums.append(got)
        if not nums:
            return None
        if len(nums) == 1:
            return nums[0]
        return sum(nums) / len(nums)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def cell(value):
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("|", "\\|").strip()


def fmt_pct(value):
    if value is None:
        return ""
    return f"{value:.1f}%"


def fmt_avail(value):
    """dt.host.availability is a ratio on current tenants (1 means up).

    A value above 1 is already a percentage and is left as-is.
    """
    if value is None:
        return ""
    if value <= 1:
        value *= 100
    return fmt_pct(value)


def fmt_count(value):
    if value is None:
        return ""
    return f"{int(round(value)):,}"


def fmt_ms(microseconds):
    """dt.service.request.response_time is stored in microseconds."""
    if microseconds is None:
        return ""
    ms = microseconds / 1000.0
    if ms >= 100:
        return f"{ms:,.0f} ms"
    if ms >= 10:
        return f"{ms:.1f} ms"
    return f"{ms:.2f} ms"


def fmt_bytes(value):
    if value is None:
        return ""
    n = float(value)
    for unit, size in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if abs(n) >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n:.0f} B"


def fmt_num(value):
    if value is None:
        return ""
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def fmt_ts(value):
    if value is None:
        return ""
    text = str(value).replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1] + " UTC"
    return text


def md_table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    align = "| --- | " + " | ".join("---:" for _ in headers[1:]) + " |"
    body = ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return "\n".join([head, align, *body])


def _scan_note(result):
    notes = (result.get("metadata", {}).get("grail", {}) or {}).get("notifications") or []
    stopped = None
    for note in notes:
        msg = note.get("message") or ""
        log(f"  [grail] {note.get('severity', '')}: {msg}")
        low = msg.lower()
        if "scan" in low and any(w in low for w in ("stop", "limit", "exceed")):
            stopped = msg
    return stopped


def score_name(needle, value, primary):
    """Score one name field. Exact beats prefix beats contains."""
    if not value or not needle:
        return 0, ""
    n = needle.lower()
    v = str(value).lower()
    if v == n:
        return (100, "exact") if primary else (90, "exact")
    if primary and v.startswith(n):
        return 70, "prefix"
    if n in v:
        return (50, "contains") if primary else (40, "contains")
    return 0, ""


def score_row(needle, namespace, row, kind):
    spec = KINDS[kind]
    best, how = 0, ""
    if namespace and kind == "workload":
        ns = str(row.get("namespaceName") or "").lower()
        name = str(row.get("entity.name") or "").lower()
        if name == needle.lower():
            if ns == namespace.lower():
                return 100, "exact"
            return 60, "other-ns"
    for i, field in enumerate(spec["name_fields"]):
        rank, why = score_name(needle, row.get(field), primary=(i == 0))
        if rank > best:
            best, how = rank, why
    return best, how


def detail_of(kind, row):
    if kind == "workload":
        parts = [row.get("namespaceName") or "", row.get("kubernetesClusterName") or ""]
        return " / ".join(p for p in parts if p)
    if kind == "service":
        return str(row.get("serviceType") or "")
    if kind == "process_group_instance":
        return str(row.get("processType") or "")
    if kind == "k8s_cluster":
        return str(row.get("kubernetesVersion") or "")
    return ""


def match_from_row(kind, row, needle, namespace, how=None, score=None):
    name = row.get("entity.name") or row.get("id") or ""
    entity_id = row.get("id") or ""
    if not entity_id:
        return None
    if score is None:
        score, how = score_row(needle, namespace, row, kind)
    if score <= 0:
        return None
    return Match(
        kind=kind,
        entity_id=str(entity_id),
        name=str(name),
        score=score,
        how=how or "",
        detail=detail_of(kind, row),
        namespace=str(row.get("namespaceName") or ""),
    )


def sort_matches(matches):
    seen = set()
    uniq = []
    for m in matches:
        key = (m.kind, m.entity_id)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(m)
    uniq.sort(key=lambda m: (-m.score, KIND_ORDER.index(m.kind), m.name.lower(), m.entity_id))
    return uniq


def pick_subject(matches, pick, prefer_kind=False):
    """Pick the subject. A score tie is ambiguous unless prefer_kind is set.

    prefer_kind is for a Davis problem that affects several entities: focus
    the service, then the workload, then the host, and list the rest.
    """
    if pick is not None:
        if pick < 1 or pick > len(matches):
            raise SystemExit(f"--pick {pick} is outside 1..{len(matches)}")
        return matches[pick - 1]
    if not matches:
        return None
    if len(matches) == 1 or matches[0].score > matches[1].score:
        return matches[0]
    if prefer_kind:
        top = matches[0].score
        best_kind = min(
            (m.kind for m in matches if m.score == top),
            key=KIND_ORDER.index)
        chosen = [m for m in matches if m.kind == best_kind and m.score == top]
        if len(chosen) == 1:
            return chosen[0]
    raise Ambiguous(matches)


def _fields_for(kind):
    spec = KINDS[kind]
    cols = ["id", "entity.name", *spec["name_fields"], *spec["extra_fields"]]
    # name_fields already include entity.name; keep the list unique and ordered.
    seen = set()
    out = []
    for col in cols:
        if col not in seen:
            seen.add(col)
            out.append(col)
    return ", ".join(out)


def search_dql(kind, needle, exact=False):
    """Exact match and contains are separate queries.

    A single contains query limited to 25 rows can drop the exact name when
    many entities share the substring. strlen() is not a Grail function, so
    the exact query is what keeps that row.
    """
    spec = KINDS[kind]
    lit = dql_str(needle.lower())
    if exact:
        clauses = " or ".join(
            f"lower({field}) == {lit}" for field in spec["name_fields"])
    else:
        clauses = " or ".join(
            f"contains(lower({field}), {lit})" for field in spec["name_fields"])
    return (
        f"fetch {spec['source']}\n"
        f"| filter {clauses}\n"
        f"| sort entity.name asc\n"
        f"| limit 25\n"
        f"| fields {_fields_for(kind)}"
    )


def ids_dql(kind, entity_ids):
    quoted = ", ".join(dql_str(i) for i in entity_ids)
    return (
        f"fetch {KINDS[kind]['source']}\n"
        f"| filter in(id, {quoted})\n"
        f"| fields {_fields_for(kind)}\n"
        f"| limit {len(entity_ids)}"
    )


def _kinds(kind):
    if kind:
        if kind not in KINDS:
            raise SystemExit(f"unknown type {kind!r}; choose from {', '.join(KIND_ORDER)}")
        return (kind,)
    return KIND_ORDER


def resolve_name(g, needle, namespace, kind):
    matches = []
    errors = []
    for k in _kinds(kind):
        for exact in (True, False):
            label = f"resolve {k} {'exact' if exact else 'contains'}"
            rows, err = g.run_soft(label, search_dql(k, needle, exact=exact))
            if err:
                errors.append(err)
                continue
            for row in rows:
                m = match_from_row(k, row, needle, namespace)
                if m:
                    matches.append(m)
    return sort_matches(matches), errors


def kind_for_id(entity_id):
    upper = str(entity_id).upper()
    for prefix, kind in _ID_KIND:
        if upper.startswith(prefix):
            return kind
    return None


def resolve_ids(g, entity_ids, kind):
    ids = [i for i in entity_ids if i][:20]
    if not ids:
        return [], []
    kinds = _kinds(kind)
    if not kind:
        implied = {kind_for_id(i) for i in ids}
        if len(implied) == 1 and None not in implied:
            kinds = tuple(implied)
    matches = []
    errors = []
    for k in kinds:
        rows, err = g.run_soft(f"resolve id {k}", ids_dql(k, ids))
        if err:
            errors.append(err)
            continue
        for row in rows:
            m = match_from_row(k, row, "", "", how="id", score=100)
            if m:
                matches.append(m)
    return sort_matches(matches), errors


def classify(text):
    """Return ('problem', id) or ('id', id) or ('name', name, namespace)."""
    raw = " ".join(text.split())
    if not raw:
        raise SystemExit("give an entity name, an entity id, or a problem id like P-123")
    if PROBLEM_ID.fullmatch(raw):
        return ("problem", raw.upper())
    if ENTITY_ID.fullmatch(raw) or GENERIC_ID.fullmatch(raw):
        return ("id", raw.upper())
    if "/" in raw:
        ns, name = raw.split("/", 1)
        ns, name = ns.strip(), name.strip()
        if len(name) < 2:
            raise SystemExit("the name after / needs at least 2 characters")
        return ("name", name, ns)
    if len(raw) < 2:
        raise SystemExit("the name needs at least 2 characters")
    return ("name", raw, "")


def metric_filter(match):
    if match.kind == "workload":
        filt = f"k8s.workload.name == {dql_str(match.name)}"
        if match.namespace:
            filt += f" and k8s.namespace.name == {dql_str(match.namespace)}"
        return filt
    if match.kind == "k8s_cluster":
        return f"k8s.cluster.name == {dql_str(match.name)}"
    field = KINDS[match.kind]["id_field"]
    return f"{field} == {dql_str(match.entity_id)}"


def _shift(shift):
    return f", shift:-{shift}" if shift else ""


def signal_dql(metrics, filt, window, shift):
    parts = ", ".join(f"{key}={expr}" for key, expr, _hdr in metrics)
    # Several aggregations in one timeseries have to sit in a brace group.
    # Without it Grail still runs the query and warns that the parameters
    # should be grouped.
    if len(metrics) > 1:
        parts = "{" + parts + "}"
    return f"timeseries {parts}, filter:{{{filt}}}, from:-{window}{_shift(shift)}"


def one_metric_dql(expr, filt, window, shift):
    return f"timeseries value={expr}, filter:{{{filt}}}, from:-{window}{_shift(shift)}"


def load_window(g, label, metrics, filt, window, shift):
    """Return (values, failed_keys). On a batch failure, query each metric."""
    rows, err = g.run_soft(label, signal_dql(metrics, filt, window, shift))
    if err is None:
        row = rows[0] if rows else {}
        return {key: scalar(row.get(key)) for key, _e, _h in metrics}, set()
    values = {}
    failed = set()
    for key, expr, _hdr in metrics:
        one, one_err = g.run_soft(
            f"{label} {key}", one_metric_dql(expr, filt, window, shift))
        if one_err:
            values[key] = None
            failed.add(key)
        else:
            row = one[0] if one else {}
            values[key] = scalar(row.get("value"))
    return values, failed


def load_signals(g, label, metrics, filt, window):
    series = {}
    failed = {}
    for name, shift in WINDOWS:
        values, bad = load_window(g, f"{label} {name}", metrics, filt, window, shift)
        series[name] = values
        failed[name] = bad
    return series, failed


def volume_note(current, baselines):
    """One sentence on failure rate versus request volume.

    current and each baseline are dicts with total and failure_pct.
    """
    if current.get("total") == 0:
        base_totals = [b.get("total") or 0 for b in baselines]
        if any(t > 0 for t in base_totals):
            return "No requests in the current window. The baseline had traffic."
        return "No requests in the current window."
    totals = [b["total"] for b in baselines if b.get("total") is not None]
    fails = [b["failure_pct"] for b in baselines if b.get("failure_pct") is not None]
    cur_total = current.get("total")
    cur_fail = current.get("failure_pct")
    vol = None
    if cur_total is not None and totals and statistics.median(totals) == 0:
        if cur_total > 0:
            return "Request volume is above a baseline of zero."
    if cur_total is not None and totals and statistics.median(totals) > 0:
        ratio = cur_total / statistics.median(totals)
        if ratio >= 1.5:
            vol = "up"
        elif ratio <= (2 / 3):
            vol = "down"
        else:
            vol = "flat"
    fail = None
    if cur_fail is not None and fails:
        delta = cur_fail - statistics.median(fails)
        if delta >= 1:
            fail = "up"
        elif delta <= -1:
            fail = "down"
        else:
            fail = "flat"
    if fail == "up" and vol == "flat":
        return "Failure rate rose while request volume stayed near the baseline."
    if fail == "up" and vol == "up":
        return "Failure rate rose and request volume rose with it."
    if fail == "up" and vol == "down":
        return "Failure rate rose while request volume dropped."
    if fail == "down" and vol == "up":
        return "Failure rate is below the baseline and request volume rose."
    if fail == "down" and vol == "down":
        return "Failure rate and request volume are both below the baseline."
    if fail == "down" and vol == "flat":
        return "Failure rate is below the baseline. Request volume stayed near it."
    if fail == "flat" and vol == "up":
        return "Request volume rose. Failure rate stayed near the baseline."
    if fail == "flat" and vol == "down":
        return "Request volume dropped. Failure rate stayed near the baseline."
    if fail == "flat" and vol == "flat":
        return "Failure rate and request volume are near the baseline."
    if vol == "up":
        return "Request volume rose against the baseline."
    if vol == "down":
        return "Request volume dropped against the baseline."
    if fail == "up":
        return "Failure rate rose against the baseline."
    return None


def empty_baseline_note(series, failed):
    missing = []
    for name, _shift in WINDOWS:
        if failed.get(name):
            continue
        values = series.get(name) or {}
        if not values or all(value is None for value in values.values()):
            missing.append(name)
    if not missing:
        return None
    if "current" in missing:
        rest = [name for name in missing if name != "current"]
        note = "No metric data in the current window."
        if rest:
            note += " Also none for " + " or ".join(rest) + "."
        return note
    if len(missing) == 1:
        return f"No data for {missing[0]}."
    return "No data for " + " or ".join(missing) + "."


def pct_note(label, current, baselines, points=10):
    vals = [v for v in baselines if v is not None]
    if current is None or not vals:
        return None
    delta = current - statistics.median(vals)
    if delta >= points:
        return f"{label} is {delta:.0f} percentage points above the baseline."
    if delta <= -points:
        return f"{label} is {abs(delta):.0f} percentage points below the baseline."
    return f"{label} is near the baseline."


def failure_pct(values, failed_keys):
    total = values.get("total")
    if total is None or total <= 0 or "failed" in failed_keys:
        return None
    failed = values.get("failed") or 0
    return failed / total * 100


def _window_rows(series, failed, columns):
    """columns: (value_key, header, formatter)."""
    rows = []
    for name, _shift in WINDOWS:
        values = series.get(name) or {}
        bad = failed.get(name) or set()
        row = [name]
        for key, _hdr, fmt in columns:
            row.append("" if key in bad else fmt(values.get(key)))
        rows.append(row)
    return rows


def render_service_signals(g, match, window):
    series, failed = load_signals(
        g, "service signals", SERVICE_METRICS, metric_filter(match), window)
    columns = (
        ("total", "requests", fmt_count),
        ("failpct", "failure %", fmt_pct),
        ("rt", "avg response", fmt_ms),
    )
    enriched = {}
    enriched_failed = {}
    baselines = []
    current = {}
    for name, _shift in WINDOWS:
        values = dict(series.get(name) or {})
        bad = set(failed.get(name) or ())
        values["failpct"] = failure_pct(values, bad)
        if "failed" in bad or "total" in bad:
            bad.add("failpct")
        enriched[name] = values
        enriched_failed[name] = bad
        point = {"total": values.get("total"), "failure_pct": values.get("failpct")}
        if name == "current":
            current = point
        else:
            baselines.append(point)
    headers = ["window", "requests", "failure %", "avg response"]
    lines = [
        md_table(headers, _window_rows(enriched, enriched_failed, columns)),
        "",
        "Failure rate is failed requests / requests. Response time is "
        "`dt.service.request.response_time`, converted from microseconds to milliseconds.",
    ]
    note = volume_note(current, baselines)
    if note:
        lines += ["", note]
    gap = empty_baseline_note(series, failed)
    if gap:
        lines += ["", gap]
    missed = sorted({k for bad in failed.values() for k in bad})
    if missed:
        lines += ["", f"Missing metrics: {', '.join(missed)}. The error is in Queries."]
    return "\n".join(lines)


def render_host_signals(g, match, window):
    series, failed = load_signals(
        g, "host signals", HOST_METRICS, metric_filter(match), window)
    columns = tuple(
        (key, hdr, fmt_avail if key == "avail" else fmt_pct)
        for key, _e, hdr in HOST_METRICS)
    headers = ["window", *[hdr for _k, _e, hdr in HOST_METRICS]]
    lines = [
        md_table(headers, _window_rows(series, failed, columns)),
        "",
        "Percentages from `dt.host.cpu.usage`, `dt.host.memory.usage`, "
        "and `dt.host.disk.used.percent`. "
        "`dt.host.availability` is shown as a percentage; a value of 1 or below "
        "is a ratio where 1 means the host was up.",
    ]
    moved = []
    comparable = 0
    for key, label in (("cpu", "CPU"), ("mem", "Memory"), ("disk", "Disk")):
        note = pct_note(
            label,
            (series.get("current") or {}).get(key),
            [(series.get(n) or {}).get(key) for n, _s in WINDOWS if n != "current"],
        )
        if note is None:
            continue
        comparable += 1
        if "near the baseline" not in note:
            moved.append(note)
    if moved:
        lines += ["", *moved]
    elif comparable == 3:
        lines += ["", "CPU, memory, and disk are near the baseline."]
    elif comparable:
        lines += ["", "The host metrics that came back are near the baseline."]
    avail = (series.get("current") or {}).get("avail")
    if avail is not None and avail < 0.99 and "avail" not in (failed.get("current") or ()):
        shown = avail * 100 if avail <= 1 else avail
        lines += ["", f"Availability in the current window is {shown:.1f}%."]
    gap = empty_baseline_note(series, failed)
    if gap:
        lines += ["", gap]
    return "\n".join(lines)


def restarts_dql(name, namespace, window):
    filt = f"k8s.workload.name == {dql_str(name)}"
    if namespace:
        filt += f" and k8s.namespace.name == {dql_str(namespace)}"
    return (
        "timeseries restarts=sum(dt.kubernetes.container.restarts, scalar:true), "
        "by:{k8s.namespace.name, k8s.pod.name}, "
        f"filter:{{{filt}}}, from:-{window}\n"
        "| filter restarts > 0\n"
        "| sort restarts desc\n"
        "| limit 10"
    )


def render_restart_table(rows):
    if not rows:
        return "No container restarts in this window."
    table = [(
        row.get("k8s.pod.name") or "",
        row.get("k8s.namespace.name") or "",
        fmt_count(scalar(row.get("restarts"))),
    ) for row in rows]
    return md_table(["pod", "namespace", "restarts"], table)


def render_workload_signals(g, match, window):
    series, failed = load_signals(
        g, "workload signals", WORKLOAD_METRICS, metric_filter(match), window)
    columns = (
        ("cpu", "cpu usage", fmt_num),
        ("mem", "working set", fmt_bytes),
    )
    lines = [
        md_table(
            ["window", "cpu usage", "working set"],
            _window_rows(series, failed, columns)),
        "",
        "Averages of `dt.kubernetes.container.cpu_usage` and "
        "`dt.kubernetes.container.memory_working_set`.",
    ]
    gap = empty_baseline_note(series, failed)
    if gap:
        lines += ["", gap]
    lines += [
        "",
        "### Container restarts",
        "",
    ]
    rows, err = g.run_soft(
        "workload restarts", restarts_dql(match.name, match.namespace, window))
    if err:
        lines.append(f"> Skipped: {one_line(err)}")
    else:
        lines.append(render_restart_table(rows))
    return "\n".join(lines)


def render_cluster_signals(g, match, window):
    series, failed = load_signals(
        g, "cluster signals", CLUSTER_METRICS, metric_filter(match), window)
    columns = (("ready", "readyz", fmt_num),)
    lines = [
        md_table(["window", "readyz"], _window_rows(series, failed, columns)),
        "",
        "Average of `dt.kubernetes.cluster.readyz`.",
    ]
    gap = empty_baseline_note(series, failed)
    if gap:
        lines += ["", gap]
    return "\n".join(lines)


def render_signals(g, match, window):
    if match.kind == "service":
        return render_service_signals(g, match, window)
    if match.kind == "host":
        return render_host_signals(g, match, window)
    if match.kind == "workload":
        return render_workload_signals(g, match, window)
    if match.kind == "k8s_cluster":
        return render_cluster_signals(g, match, window)
    return (
        "No golden-signal metrics for this entity type. "
        "Problems, logs, and the change window are below."
    )


def pod_restarts_for_name(g, match, window):
    """For a service or process, restarts of the workload with the same name."""
    if match.kind not in ("service", "process_group", "process_group_instance"):
        return None
    rows, err = g.run_soft(
        "workload name", search_dql("workload", match.name, exact=True))
    if err or not rows:
        return None
    found = []
    for row in rows:
        m = match_from_row("workload", row, match.name, "", )
        if m and m.how == "exact":
            found.append(m)
    found = sort_matches(found)
    if len(found) != 1:
        return None
    workload = found[0]
    got, qerr = g.run_soft(
        "pod restarts", restarts_dql(workload.name, workload.namespace, window))
    title = f"Pod restarts for workload `{workload.name}`"
    if workload.namespace:
        title += f" in `{workload.namespace}`"
    if qerr:
        body = f"> Skipped: {one_line(qerr)}"
    else:
        body = render_restart_table(got)
    return f"## {title}\n\n{body}"


def problems_dql(entity_id, problems_from, window):
    eid = dql_str(entity_id)
    return (
        f"fetch dt.davis.problems, from:-{problems_from}\n"
        f"| filter in({eid}, affected_entity_ids)\n"
        f"| filter event.status == \"ACTIVE\" or event.end >= now()-{window}\n"
        "| fields event.start, event.end, display_id, event.name, event.category, event.status\n"
        "| sort event.start desc\n"
        "| limit 20"
    )


def problem_by_id_dql(display_id, problems_from):
    return (
        f"fetch dt.davis.problems, from:-{problems_from}\n"
        f"| filter display_id == {dql_str(display_id)}\n"
        "| fields event.start, event.end, display_id, event.name, "
        "event.category, event.status, affected_entity_ids\n"
        "| sort event.start desc\n"
        "| limit 5"
    )


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def parsed_ts(value):
    """Grail timestamps arrive as ISO strings or epoch numbers."""
    if isinstance(value, (int, float)) or (
            isinstance(value, str) and re.fullmatch(r"\d+", value or "")):
        n = float(value)
        if n > 1e17:
            n /= 1e9
        elif n > 1e14:
            n /= 1e6
        elif n > 1e11:
            n /= 1e3
        return datetime.fromtimestamp(n, tz=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def render_problems(g, match, problems_from, window, window_s, focus):
    rows, err = g.run_soft(
        "problems", problems_dql(match.entity_id, problems_from, window))
    if err:
        return f"> Skipped: {one_line(err)}"
    lines = []
    if focus:
        started = fmt_ts(focus.get("event.start"))
        lines.append(
            f"Opened from `{focus.get('display_id')}` "
            f"({focus.get('event.status')}, {focus.get('event.category')}): "
            f"{focus.get('event.name')}. Started {started}."
        )
        started_at = parsed_ts(focus.get("event.start"))
        if started_at is not None:
            age = (datetime.now(timezone.utc) - started_at).total_seconds()
            if age > window_s:
                lines.append(
                    f"That start is outside the {window} signal window. "
                    "Widen --window to include it."
                )
        lines.append("")
    if not rows:
        lines.append("No active or recently closed Davis problems on this entity.")
        return "\n".join(lines)
    table = []
    for row in rows:
        table.append((
            row.get("display_id") or "",
            row.get("event.status") or "",
            row.get("event.category") or "",
            fmt_ts(row.get("event.start")),
            row.get("event.name") or "",
        ))
    lines.append(md_table(
        ["id", "status", "category", "started", "name"], table))
    if not focus:
        stale = []
        for row in rows:
            if row.get("event.status") != "ACTIVE":
                continue
            started_at = parsed_ts(row.get("event.start"))
            if started_at is None:
                continue
            age = (datetime.now(timezone.utc) - started_at).total_seconds()
            if age > window_s:
                stale.append(str(row.get("display_id") or ""))
        if stale:
            ids = [s for s in stale if s]
        else:
            ids = []
        if ids:
            lines += [
                "",
                "Active problems started before this signal window: "
                + ", ".join(ids)
                + ". Widen --window to include the start.",
            ]
    return "\n".join(lines)


def log_text(rec):
    for key in _LOG_TEXT_FIELDS:
        value = rec.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def is_error_record(rec):
    for key in _LOG_LEVEL_FIELDS:
        value = rec.get(key)
        if isinstance(value, str) and value.upper() in _ERROR_LEVELS:
            return True
    return bool(_ERROR_WORD.search(log_text(rec)))


def log_template(text):
    line = " ".join((text or "").strip().split())
    if not line:
        return "(empty)"
    line = _LEAD_TS.sub("", line)
    found = _ERROR_WORD.search(line)
    if found and found.start() > 40:
        line = line[found.start():]
    line = _UUID.sub("<id>", line)
    line = _HEX.sub("<hex>", line)
    line = _NUM.sub("<n>", line)
    return line[:140]


def logs_dql(filt, window, scan_gb):
    return (
        f"fetch logs, from:-{window}{scan_clause(scan_gb)}\n"
        f"| filter {filt}\n"
        "| limit 200"
    )


def logs_search_dql(name, window, scan_gb):
    return (
        f"fetch logs, from:-{window}{scan_clause(scan_gb)}\n"
        f"| search {dql_str(name)}\n"
        "| limit 200"
    )


def scan_clause(scan_gb):
    if scan_gb is None or scan_gb < 0:
        return ""
    return f", scanLimitGBytes:{int(scan_gb)}"


def render_logs(g, match, window, scan_gb):
    filt = metric_filter(match)
    rows, err = g.run_soft("logs", logs_dql(filt, window, scan_gb))
    how = f"filtered on `{filt}`"
    if err or not rows:
        if len(match.name) < 4:
            why = one_line(err) if err else "the entity filter returned no lines"
            return (
                f"> No log sample. {why}. "
                "The name is too short to fall back to a text search."
            )
        rows, err = g.run_soft(
            "logs search", logs_search_dql(match.name, window, scan_gb))
        how = f"text search for `{match.name}`"
        if err:
            return f"> Skipped: {one_line(err)}"
    errors = [r for r in rows if is_error_record(r)]
    if not errors:
        return (
            f"Sampled {len(rows)} log lines ({how}). "
            "None looked like an error (log level ERROR/FATAL/SEVERE/CRITICAL, "
            "or ERROR, FATAL, Exception, SEVERE, or CRITICAL in the text)."
        )
    counts = {}
    for rec in errors:
        key = log_template(log_text(rec))
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    lines = [
        f"Sampled {len(rows)} log lines ({how}); {len(errors)} looked like errors. "
        "Counts are inside that sample, and the scan cap can cut it short.",
        "",
        md_table(["template", "count"], ranked),
    ]
    return "\n".join(lines)


def events_dql(filt, start, end, scan_gb):
    return (
        f"fetch events, from:{start}, to:{end}{scan_clause(scan_gb)}\n"
        f"| filter {filt}\n"
        "| sort timestamp desc\n"
        "| limit 30"
    )


def events_search_dql(name, start, end, scan_gb):
    return (
        f"fetch events, from:{start}, to:{end}{scan_clause(scan_gb)}\n"
        f"| search {dql_str(name)}\n"
        "| sort timestamp desc\n"
        "| limit 30"
    )


def _event_cells(row):
    preferred = (
        "timestamp", "event.kind", "event.type", "event.name",
        "event.category", "k8s.event.reason",
    )
    bits = []
    for key in preferred:
        if row.get(key) not in (None, ""):
            shown = fmt_ts(row[key]) if key == "timestamp" else row[key]
            bits.append(f"{key}={shown}")
    if bits:
        return "; ".join(bits)[:220]
    extras = []
    for key, value in row.items():
        if key.startswith("dt.system.") or value in (None, ""):
            continue
        extras.append(f"{key}={value}")
        if len(extras) == 4:
            break
    return "; ".join(extras)[:220]


def render_events(g, match, window_s, change_s, scan_gb):
    start = f"now()-{window_s + change_s}s"
    end = f"now()-{window_s}s"
    filt = metric_filter(match)
    rows, err = g.run_soft("events", events_dql(filt, start, end, scan_gb))
    how = f"filtered on `{filt}`"
    if err or not rows:
        if len(match.name) < 4:
            why = one_line(err) if err else "the entity filter returned no events"
            return f"> No events. {why}."
        rows, err = g.run_soft(
            "events search", events_search_dql(match.name, start, end, scan_gb))
        how = f"text search for `{match.name}`"
        if err:
            return f"> Skipped: {one_line(err)}"
    if not rows:
        return "No events in the change window."
    table = [(str(i), _event_cells(row)) for i, row in enumerate(rows, 1)]
    return "\n".join([
        f"{len(rows)} events ({how}).",
        "",
        md_table(["#", "event"], table),
    ])


def edges_dql(entity_id, side, limit):
    eid = dql_str(entity_id)
    if side == "caller":
        which = f"target_id == toSmartscapeId({eid}) or target_id == {eid}"
        other = "source_id"
    else:
        which = f"source_id == toSmartscapeId({eid}) or source_id == {eid}"
        other = "target_id"
    return (
        "smartscapeEdges calls\n"
        '| filter source_type == "SERVICE" and target_type == "SERVICE"\n'
        f"| filter {which}\n"
        f"| fieldsAdd other_id = {other}, other_name = getNodeName({other})\n"
        "| fields other_id, other_name\n"
        f"| limit {int(limit)}"
    )


def neighbor_metrics_dql(entity_ids, window):
    quoted = ", ".join(dql_str(i) for i in entity_ids)
    return (
        "timeseries {"
        "total=sum(dt.service.request.count, scalar:true), "
        "failed=sum(dt.service.request.failure_count, scalar:true, default:0), "
        "rt=avg(dt.service.request.response_time, scalar:true)"
        "}, "
        "by:{dt.entity.service}, "
        f"filter:in(dt.entity.service, {quoted}), "
        f"from:-{window}"
    )


def render_edges(g, match, window, limit):
    callers, cerr = g.run_soft(
        "callers", edges_dql(match.entity_id, "caller", limit))
    callees, eerr = g.run_soft(
        "callees", edges_dql(match.entity_id, "callee", limit))
    if cerr and eerr:
        return (
            f"> Skipped: {one_line(cerr)} "
            "Service call edges are Smartscape `calls`. See docs/smartscape_calls.md."
        )
    callers = callers or []
    callees = callees or []
    ids = []
    for edge in callers + callees:
        eid = str(edge.get("other_id") or "")
        if eid.startswith("SERVICE-") and eid not in ids and eid != match.entity_id:
            ids.append(eid)
    metrics = {}
    if ids:
        rows, merr = g.run_soft(
            "neighbor signals", neighbor_metrics_dql(ids, window))
        if merr:
            log(f"  neighbor metrics skipped: {one_line(merr)}")
        else:
            for row in rows:
                eid = str(row.get("dt.entity.service") or "")
                metrics[eid] = {
                    "total": scalar(row.get("total")),
                    "failed": scalar(row.get("failed")),
                    "rt": scalar(row.get("rt")),
                }
    headers = ["service", "id", "requests", "failure %", "avg response"]
    parts = []
    if cerr:
        parts.append(f"Callers skipped: {one_line(cerr)}")
    else:
        parts.append("### Callers")
        parts.append("")
        parts.append(
            render_neighbor_table(callers, metrics, headers)
            if callers else "No caller edges.")
    parts.append("")
    if eerr:
        parts.append(f"Callees skipped: {one_line(eerr)}")
    else:
        parts.append("### Callees")
        parts.append("")
        parts.append(
            render_neighbor_table(callees, metrics, headers)
            if callees else "No callee edges.")
    parts += [
        "",
        "Callers are `calls` edges with this service as the target. "
        "Callees are `calls` edges with this service as the source. "
        "Request numbers are the current window only.",
    ]
    return "\n".join(parts)


def render_neighbor_table(edges, metrics, headers):
    body = []
    for edge in edges:
        eid = str(edge.get("other_id") or "")
        name = edge.get("other_name") or eid
        stat = metrics.get(eid) or {}
        total = stat.get("total")
        fp = None
        if total:
            fp = ((stat.get("failed") or 0) / total) * 100
        body.append((name, eid, fmt_count(total), fmt_pct(fp), fmt_ms(stat.get("rt"))))
    return md_table(headers, body)


def render_queries(queries):
    blocks = []
    for label, dql, err in queries:
        note = f" ({err})" if err else ""
        blocks.append(f"// {label}{note}\n{dql.strip()}")
    body = "\n\n".join(blocks).replace("```", "'''")
    return "## Queries\n\n```dql\n" + body + "\n```"


def render_matches(matches, chosen):
    rows = []
    for i, m in enumerate(matches, 1):
        used = "yes" if chosen and m.kind == chosen.kind and m.entity_id == chosen.entity_id else ""
        rows.append((i, m.kind, m.how, m.name, m.entity_id, m.detail, used))
    return md_table(
        ["#", "kind", "match", "name", "id", "detail", "used"], rows)


def print_matches(matches):
    for i, m in enumerate(matches, 1):
        detail = f"  {m.detail}" if m.detail else ""
        print(f"{i:>3}  {m.kind:<24} {m.how:<9} {m.name}")
        print(f"     {m.entity_id}{detail}")


def _fatal_resolve(matches, errors, what):
    if matches:
        if errors:
            log(f"{len(errors)} entity type(s) could not be queried; continuing with the rest")
        return
    if errors:
        raise SystemExit(f"Could not query entities: {one_line(errors[0])}")
    raise SystemExit(f"No entities matched {what!r}.")


def load_focus_problem(g, display_id, problems_from):
    rows, err = g.run_soft(
        "problem", problem_by_id_dql(display_id, problems_from))
    if err:
        raise SystemExit(f"Could not read {display_id}: {one_line(err)}")
    if not rows:
        raise SystemExit(f"No Davis problem with display_id {display_id}.")
    return rows[0]


def build_brief(g, match, matches, window, window_s, change, change_s,
                problems_from, scan_gb, neighbors, focus):
    subject = (
        f"Subject: {match.kind} `{match.name}` (`{match.entity_id}`)"
        + (f" · {match.detail}" if match.detail else "")
    )
    lines = [
        f"# Incident brief: {match.name}",
        "",
        f"Generated {dt_fetch._now_stamp()} from {dt_fetch._source_url()}.",
        f"Signals cover the last {window}, compared with the same length of time "
        "yesterday and last week.",
        f"The change window is the {change} before the signal window. "
        f"Problems are read from the last {problems_from}.",
        "",
        subject,
    ]
    if len(matches) > 1:
        lines += [
            "",
            "## Matches",
            "",
            "Re-run with `--pick N` to use a different row.",
            "",
            render_matches(matches, match),
        ]
    lines += ["", "## Problems", "", render_problems(
        g, match, problems_from, window, window_s, focus)]
    lines += ["", "## Signals", "", render_signals(g, match, window)]
    restarts = pod_restarts_for_name(g, match, window)
    if restarts:
        lines += ["", restarts]
    lines += ["", "## Error logs", "", render_logs(g, match, window, scan_gb)]
    lines += ["", "## Change window", "", render_events(
        g, match, window_s, change_s, scan_gb)]
    if match.kind == "service":
        lines += ["", "## Blast radius", "", render_edges(
            g, match, window, neighbors)]
    lines += ["", render_queries(g.queries), ""]
    return "\n".join(lines)


def _subject_from_args(g, args, problems_from):
    if args.entity_id:
        entity_id = args.entity_id.strip().upper()
        matches, errors = resolve_ids(g, [entity_id], args.type)
        _fatal_resolve(matches, errors, entity_id)
        return pick_subject(matches, args.pick), matches, None
    kind, *rest = classify(args.name)
    if kind == "problem":
        focus = load_focus_problem(g, rest[0], problems_from)
        ids = as_list(focus.get("affected_entity_ids"))
        if not ids:
            raise SystemExit(
                f"{rest[0]} has no affected_entity_ids. "
                "Re-run with --entity-id.")
        matches, errors = resolve_ids(g, ids, args.type)
        if not matches:
            shown = ", ".join(ids[:8])
            if errors:
                raise SystemExit(f"Could not query entities: {one_line(errors[0])}")
            raise SystemExit(
                f"No entity matched the affected ids on {rest[0]}: {shown}. "
                "Re-run with --entity-id.")
        if errors:
            log(f"{len(errors)} entity type(s) could not be queried; continuing with the rest")
        return pick_subject(matches, args.pick, prefer_kind=True), matches, focus
    if kind == "id":
        matches, errors = resolve_ids(g, [rest[0]], args.type)
        _fatal_resolve(matches, errors, rest[0])
        return pick_subject(matches, args.pick), matches, None
    name, namespace = rest
    matches, errors = resolve_name(g, name, namespace, args.type)
    _fatal_resolve(matches, errors, args.name)
    return pick_subject(matches, args.pick), matches, None


def cmd_resolve(args):
    dt_fetch._require_config()
    g = Grail()
    kind, *rest = classify(args.name)
    if kind == "problem":
        raise SystemExit("resolve takes an entity name or id. Use brief for a problem id.")
    if kind == "id":
        matches, errors = resolve_ids(g, [rest[0]], args.type)
    else:
        matches, errors = resolve_name(g, rest[0], rest[1], args.type)
    if not matches:
        if errors:
            print(one_line(errors[0]), file=sys.stderr)
        else:
            print(f"No entities matched {args.name!r}.", file=sys.stderr)
        return 1
    print(f"{len(matches)} match(es).\n")
    print_matches(matches)
    return 0


def cmd_brief(args):
    dt_fetch._require_config()
    window_s, window = parse_duration(args.window, "--window")
    change_s, change = parse_duration(args.change_before, "--change-before")
    _problems_s, problems_from = parse_duration(args.problems_from, "--problems-from")
    if args.scan_limit_gb != -1 and args.scan_limit_gb < 1:
        raise SystemExit("--scan-limit-gb must be -1 or a positive number of GB")
    if args.neighbors < 1:
        raise SystemExit("--neighbors must be at least 1")
    if not args.name and not args.entity_id:
        raise SystemExit("give a name, a problem id, or --entity-id")
    g = Grail()
    try:
        match, matches, focus = _subject_from_args(g, args, problems_from)
    except Ambiguous as amb:
        print(
            f"{len(amb.matches)} matches, and none outranks the others. "
            "Re-run with --pick N:\n")
        print_matches(amb.matches)
        return 3
    log(f"subject {match.kind} {match.name} ({match.entity_id})")
    text = build_brief(
        g, match, matches, window, window_s, change, change_s, problems_from,
        args.scan_limit_gb, args.neighbors, focus)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        log(f"wrote {args.out}")
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_name(p, name_required):
        p.add_argument(
            "name", nargs=None if name_required else "?", default="",
            help="entity name, entity id, or (brief only) a Davis display id P-123")
        p.add_argument(
            "--type", choices=list(KIND_ORDER),
            help="only look at this entity type")

    p_resolve = sub.add_parser("resolve", help="list entities that match a name or id")
    add_name(p_resolve, True)

    p_brief = sub.add_parser("brief", help="write an incident brief for one entity")
    add_name(p_brief, False)
    p_brief.add_argument(
        "--pick", type=int,
        help="1-based row from resolve, when several entities match")
    p_brief.add_argument("--entity-id", help="skip name search and use this id")
    p_brief.add_argument("--window", default="1h", help="signal window (default 1h)")
    p_brief.add_argument(
        "--change-before", default="30m",
        help="how long before the signal window to read events (default 30m)")
    p_brief.add_argument(
        "--problems-from", default="7d",
        help="how far back to read Davis problems (default 7d)")
    p_brief.add_argument(
        "--scan-limit-gb", type=int, default=5,
        help="cap on log and event fetches, in GB (default 5; -1 lifts it)")
    p_brief.add_argument(
        "--neighbors", type=int, default=10,
        help="caller and callee edges to include for a service (default 10)")
    p_brief.add_argument("--out", help="write the brief to this file instead of stdout")

    args = ap.parse_args(argv)
    if args.cmd == "resolve":
        return cmd_resolve(args)
    return cmd_brief(args)


if __name__ == "__main__":
    sys.exit(main())
