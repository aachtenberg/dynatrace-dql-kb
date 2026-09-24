"""
dt_trace_profiler.py - Rank trace entry points by frequency and flag likely batch jobs.

Uses the same Grail client and configuration as dt_fetch.py (DT_ENVIRONMENT_URL,
DT_API_TOKEN, .env file). Stdlib only.

Stages
  1. Profile  One aggregated query: run count and p50/p95 duration per entry
              point (service + endpoint + span kind).
  2. Cadence  For entry points inside a run-count band, pull root-span start
              times in batches (one scan per batch) and measure how regular the
              gaps between runs are and whether runs start on minute boundaries.
  3. Shape    For the top candidates, look at the three most recent runs, each
              in a narrow time window, and count total spans and DB spans.
  Optional    --metric-counts adds request counts from dt.service.request.count,
              which is not subject to trace capture sampling.

Scoring (0-6): non-server root kind +1, clockwork cadence +2 (or regular +1),
minute-aligned starts +1, long runs +1, high span/DB fan-out +1.

Required token scopes: storage:spans:read, storage:buckets:read
(+ storage:metrics:read for --metric-counts).

Usage:
    ./util/dt_trace_profiler.sh                       # 7-day lookback
    ./util/dt_trace_profiler.sh --days 3 --out /tmp/profile.csv
    ./util/dt_trace_profiler.sh --root-filter 'request.is_root_span == true'
    ./util/dt_trace_profiler.sh --help

The CSV contains real service and endpoint names from your tenant. It is
gitignored by default; do not commit it to a shared repo.
"""

import argparse
import csv
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

# Launched as `python util/dt_trace_profiler.py`, so sys.path[0] is util/.
# Put the repo root on the path to import dt_fetch.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import dt_fetch

# Grouping expressions reused across stages so keys stay consistent.
# OneAgent spans carry dt.entity.service; OTel-ingested spans carry service.name.
SVC = "coalesce(service.name, toString(dt.entity.service))"
SVC_ID = "toString(dt.entity.service)"
EP = "coalesce(endpoint.name, span.name)"
KEY_SEP = "\u241f"  # unit-separator glyph, will not appear in real names


def scan_group(limit_gb: int) -> str:
    """Fetch scan cap as a curly-brace parameter group.

    Grail's default cap is 500 GB, and a fetch that crosses it is stopped.
    The info parameter has to be grouped: {scanLimitGBytes: N}. -1 lifts the cap.
    """
    return ", {scanLimitGBytes: %d}" % int(limit_gb)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def query(dql: str, **kw) -> list[dict]:
    """Run DQL and surface Grail notifications (truncation, scan limits)
    instead of silently analysing partial data."""
    result = dt_fetch.run_dql_result(dql, **kw)
    notes = (result.get("metadata", {}).get("grail", {}) or {}).get("notifications") or []
    stopped = None
    for n in notes:
        msg = n.get("message") or ""
        log(f"  [grail] {n.get('severity', '')}: {msg}")
        low = msg.lower()
        if "scan" in low and any(w in low for w in ("stop", "limit", "exceed")):
            stopped = msg
    if stopped:
        raise RuntimeError(f"Grail stopped the query at the scan limit: {stopped}")
    return result.get("records", []) or []


def dql_str(s) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def iso_ns(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")


def fmt_period(s) -> str:
    if s is None:
        return ""
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n * 0.98:  # jitter puts an hourly job at 3599s, still "1.0h"
            return f"{s / n:.1f}{unit}"
    return f"{s:.0f}s"


def num(v, cast=float, default=0):
    # Grail may return longs as JSON strings; normalise.
    try:
        return cast(float(v)) if v is not None else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Stage 1: profile
# ---------------------------------------------------------------------------

def stage_profile(days: int, root_filter: str, scan_limit_gb: int) -> list[dict]:
    dql = f"""
fetch spans, from: now() - {days}d{scan_group(scan_limit_gb)}
| filter {root_filter}
| fieldsAdd svc = {SVC}, svc_id = {SVC_ID}, ep = {EP}, kind = span.kind,
            dur_ms = toLong(duration) / 1000000.0
| summarize {{runs = count(),
             p50_ms = percentile(dur_ms, 50),
             p95_ms = percentile(dur_ms, 95)}},
            by: {{svc, svc_id, ep, kind}}
| sort runs desc
"""
    rows = query(dql, scan_limit_gbytes=scan_limit_gb, timeout_s=900)
    for r in rows:
        r["runs"] = num(r.get("runs"), int)
        r["p50_ms"] = num(r.get("p50_ms"))
        r["p95_ms"] = num(r.get("p95_ms"))
        r["kind"] = (r.get("kind") or "").lower()
    return rows


def stage_metric_counts(days: int) -> dict:
    # The endpoint dimension on dt.service.request.count has changed across
    # Dynatrace versions. If this errors, check `describe`/metric metadata and
    # adjust; the caller treats failure as non-fatal.
    dql = f"""
timeseries total = sum(dt.service.request.count), from: now() - {days}d,
           by: {{dt.entity.service, endpoint.name}}
| fieldsAdd requests = arraySum(total)
| fields svc_id = toString(dt.entity.service), ep = endpoint.name, requests
"""
    return {(r.get("svc_id"), r.get("ep")): num(r.get("requests"), int)
            for r in query(dql)}


# ---------------------------------------------------------------------------
# Stage 2: cadence
# ---------------------------------------------------------------------------

def stage_start_times(days, root_filter, eps, batch_size, max_records, scan_limit_gb) -> dict:
    """Root start times for many entry points, one scan per batch."""
    out: dict = {}
    for i in range(0, len(eps), batch_size):
        batch = eps[i:i + batch_size]
        keys = ", ".join(dql_str(f"{svc}{KEY_SEP}{ep}") for svc, ep in batch)
        dql = f"""
fetch spans, from: now() - {days}d{scan_group(scan_limit_gb)}
| filter {root_filter}
| fieldsAdd key = concat({SVC}, "{KEY_SEP}", {EP})
| filter in(key, {{{keys}}})
| fields key, ts = toLong(start_time), tid = toString(trace.id)
"""
        log(f"  batch {i // batch_size + 1}: {len(batch)} entry points")
        for r in query(dql, max_records=max_records, timeout_s=900,
                       scan_limit_gbytes=scan_limit_gb):
            svc, _, ep = (r.get("key") or "").partition(KEY_SEP)
            out.setdefault((svc, ep), []).append((num(r.get("ts"), int), r.get("tid")))
    return out


def cadence(samples, burst_s: float = 5.0, align_tol_s: float = 10.0) -> dict:
    """Regularity stats from (ts_ns, trace_id) samples.

    Starts within burst_s of each other collapse into one run, so a job that
    fans out into parallel root spans counts once.

    rcv = MAD / median of the gaps between runs. Robust to missed runs and
    weekend gaps. Near 0 means clockwork; Poisson-like traffic sits near 0.6-0.7.
    """
    runs = []
    for ts, tid in sorted(samples):
        t = ts / 1e9
        if not runs or t - runs[-1][0] > burst_s:
            runs.append((t, ts, tid))
    res = {"runs_collapsed": len(runs), "period_s": None, "rcv": None,
           "align_frac": None, "recent": [(r[1], r[2]) for r in runs[-3:]]}
    if len(runs) < 4:
        return res
    gaps = [b[0] - a[0] for a, b in zip(runs, runs[1:])]
    med = statistics.median(gaps)
    mad = statistics.median(abs(g - med) for g in gaps)
    res["period_s"] = med
    res["rcv"] = mad / med if med > 0 else None
    res["align_frac"] = sum(1 for r in runs if (r[0] % 60) <= align_tol_s) / len(runs)
    return res


# ---------------------------------------------------------------------------
# Stage 3: shape
# ---------------------------------------------------------------------------

def stage_shape(recent, p95_ms: float, scan_limit_gb: int):
    """Median span and DB-span counts over a few recent runs, each queried in
    a window sized from the entry point's p95 so the scan stays small."""
    spans, dbs = [], []
    pad_ns = int(max(p95_ms * 1.5, 60_000) * 1e6) + 120 * 10**9
    for ts, tid in recent:
        dql = f"""
fetch spans{scan_group(scan_limit_gb)}
| filter toString(trace.id) == {dql_str(tid)}
| summarize {{spans = count(), db_spans = countIf(isNotNull(db.system))}}
"""
        rows = query(
            dql,
            start=iso_ns(ts - 60 * 10**9),
            end=iso_ns(ts + pad_ns),
            scan_limit_gbytes=scan_limit_gb,
        )
        if rows:
            spans.append(num(rows[0].get("spans"), int))
            dbs.append(num(rows[0].get("db_spans"), int))
    if not spans:
        return None, None
    return statistics.median(spans), statistics.median(dbs)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score(row: dict):
    s, why = 0, []
    if row.get("kind") and row["kind"] != "server":
        s += 1
        why.append(f"root kind={row['kind']}")
    rcv = row.get("rcv")
    if rcv is not None:
        if rcv < 0.15:
            s += 2
            why.append(f"clockwork cadence (rcv={rcv:.2f})")
        elif rcv < 0.35:
            s += 1
            why.append(f"regular cadence (rcv={rcv:.2f})")
    af = row.get("align_frac")
    if af is not None and af >= 0.7:
        s += 1
        why.append(f"starts on minute boundary {af:.0%}")
    if row.get("p50_ms", 0) >= 30_000:
        s += 1
        why.append(f"long runs (p50 {row['p50_ms'] / 1000:.0f}s)")
    sp, db = row.get("spans_med"), row.get("db_spans_med")
    if (sp and sp >= 200) or (db and db >= 100):
        s += 1
        why.append(f"high fan-out ({sp:.0f} spans, {db:.0f} db)")
    return s, "; ".join(why)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7,
                    help="lookback in days; keep within span retention (default 7)")
    ap.add_argument("--root-filter", default="isNull(span.parent_id)",
                    help="DQL predicate selecting entry spans. Default is true "
                         "trace roots. Use 'request.is_root_span == true' for "
                         "per-service entry points when upstream systems "
                         "propagate trace context into your services.")
    ap.add_argument("--min-runs", type=int, default=4)
    ap.add_argument("--max-runs", type=int, default=20_000,
                    help="skip cadence analysis above this many root spans in "
                         "the window (not batch-like, and expensive)")
    ap.add_argument("--batch-size", type=int, default=150,
                    help="entry points per stage-2 scan; lower it if Grail "
                         "reports truncation")
    ap.add_argument("--max-records", type=int, default=500_000)
    ap.add_argument("--shape-top", type=int, default=25,
                    help="top cadence candidates that get stage 3")
    ap.add_argument("--metric-counts", action="store_true",
                    help="add unsampled counts from dt.service.request.count")
    ap.add_argument("--scan-limit-gb", type=int, default=-1,
                    help="Grail fetch scan cap in GB, sent as "
                         "{scanLimitGBytes: N}. Default -1 lifts the 500 GB "
                         "stop so a no-arg 7-day run is not cancelled. A "
                         "positive value stops the query at that many GB.")
    ap.add_argument("--out", default="dt_trace_profile.csv")
    a = ap.parse_args()

    dt_fetch._require_config()

    cap = "no cap" if a.scan_limit_gb < 0 else f"{a.scan_limit_gb} GB"
    log(f"scan limit {scan_group(a.scan_limit_gb).lstrip(', ')} ({cap}); "
        "Grail otherwise stops a fetch at 500 GB")
    log(f"stage 1: profiling entry points over {a.days}d")
    rows = stage_profile(a.days, a.root_filter, a.scan_limit_gb)
    log(f"  {len(rows)} entry points")

    if a.metric_counts:
        log("stage 1b: unsampled request counts")
        try:
            mc = stage_metric_counts(a.days)
            for r in rows:
                r["metric_requests"] = mc.get((r.get("svc_id"), r.get("ep")))
        except RuntimeError as e:
            log(f"  skipped: {str(e).splitlines()[0]}")

    # Kind is part of the stage-1 key; cadence is keyed on (svc, ep) only.
    band = sorted({(r["svc"], r["ep"]) for r in rows
                   if a.min_runs <= r["runs"] <= a.max_runs})
    log(f"stage 2: cadence for {len(band)} entry points")
    starts = stage_start_times(a.days, a.root_filter, band,
                               a.batch_size, a.max_records, a.scan_limit_gb)
    for r in rows:
        smp = starts.get((r["svc"], r["ep"]))
        if smp:
            r.update(cadence(smp))
        r["score"], r["why"] = score(r)

    cands = sorted((r for r in rows if r.get("recent")),
                   key=lambda r: r["score"], reverse=True)[:a.shape_top]
    log(f"stage 3: shape for {len(cands)} candidates")
    for r in cands:
        r["spans_med"], r["db_spans_med"] = stage_shape(
            r["recent"], r["p95_ms"], a.scan_limit_gb)
        r["score"], r["why"] = score(r)

    rows.sort(key=lambda r: (-r["score"], -r["runs"]))
    cols = ["score", "svc", "ep", "kind", "runs", "metric_requests",
            "runs_collapsed", "period", "rcv", "align_frac", "p50_ms",
            "p95_ms", "spans_med", "db_spans_med", "why"]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r["period"] = fmt_period(r.get("period_s"))
            for k, nd in (("rcv", 3), ("align_frac", 3), ("p50_ms", 1), ("p95_ms", 1)):
                if r.get(k) is not None:
                    r[k] = round(r[k], nd)
            w.writerow(r)

    log(f"\nwrote {a.out}\n\nTop batch candidates (score >= 3):")
    for r in [r for r in rows if r["score"] >= 3][:20]:
        print(f"  [{r['score']}] {r['svc']} :: {r['ep']}  every "
              f"{r['period'] or '?'}  ({r['why']})")


if __name__ == "__main__":
    main()
