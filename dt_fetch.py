"""
dt_fetch.py — Populate the environment-specific docs from a live Dynatrace tenant.

Runs the DQL discovery queries against the Dynatrace Grail query API and writes
the results into:
  - docs/metric_keys.md     (all metric keys)
  - docs/entity_schemas.md  (field names for entities, logs, events, spans, bizevents)

Configuration (environment variables, or a .env file in the repo root):
  DT_ENVIRONMENT_URL   e.g. https://abc12345.apps.dynatrace.com   (no trailing slash)
  DT_API_TOKEN         a Dynatrace API token (dt0c01...) with Grail read scopes:
                         storage:metrics:read, storage:entities:read,
                         storage:logs:read, storage:events:read,
                         storage:bizevents:read, storage:spans:read,
                         storage:buckets:read

Usage:
    python dt_fetch.py metrics     # populate docs/metric_keys.md
    python dt_fetch.py schemas     # populate docs/entity_schemas.md
    python dt_fetch.py all         # both
    python dt_fetch.py test        # verify the token/URL work, run one tiny query
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DOCS_DIR = REPO_ROOT / "docs"


# ---------------------------------------------------------------------------
# Configuration / .env loading
# ---------------------------------------------------------------------------

def _load_dotenv():
    """Load KEY=VALUE pairs from a .env file in the repo root (if present).
    Does not overwrite variables already set in the real environment."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

DT_ENVIRONMENT_URL = os.getenv("DT_ENVIRONMENT_URL", "").rstrip("/")
DT_API_TOKEN = os.getenv("DT_API_TOKEN", "")

# Grail DQL execution endpoint (async: execute -> poll)
QUERY_EXECUTE_PATH = "/platform/storage/query/v1/query:execute"
QUERY_POLL_PATH = "/platform/storage/query/v1/query:poll"

POLL_INTERVAL_SECONDS = 1.5
POLL_TIMEOUT_SECONDS = 120


def _now_stamp() -> str:
    """UTC timestamp for stamping generated docs, e.g. '2026-06-27 14:05 UTC'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _require_config():
    missing = []
    if not DT_ENVIRONMENT_URL:
        missing.append("DT_ENVIRONMENT_URL")
    if not DT_API_TOKEN:
        missing.append("DT_API_TOKEN")
    if missing:
        print(f"ERROR: missing required config: {', '.join(missing)}")
        print("Set them in your environment or in a .env file (see .env.example).")
        sys.exit(2)


# ---------------------------------------------------------------------------
# Dynatrace Grail query API
# ---------------------------------------------------------------------------

def _auth_header() -> str:
    """Classic API tokens (dt0c01...) use 'Api-Token'; platform tokens
    (dt0s16...) and OAuth bearer tokens use 'Bearer'."""
    if DT_API_TOKEN.startswith("dt0c01"):
        return f"Api-Token {DT_API_TOKEN}"
    return f"Bearer {DT_API_TOKEN}"


def _http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _auth_header())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} {e.reason} for {url}\n{detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach {url}: {e.reason}") from None


def run_dql(query: str) -> list[dict]:
    """Execute a DQL query via the Grail API and return result records.
    Handles the async execute -> poll flow."""
    execute_url = DT_ENVIRONMENT_URL + QUERY_EXECUTE_PATH
    # maxResultRecords: API defaults to 1000; raise it so large result sets
    # (e.g. all metric keys) come back complete rather than silently truncated.
    payload = {
        "query": query,
        "requestTimeoutMilliseconds": 30000,
        "maxResultRecords": 100000,
    }
    resp = _http_json("POST", execute_url, payload)

    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        state = resp.get("state")
        if state == "SUCCEEDED":
            return resp.get("result", {}).get("records", []) or []
        if state in ("FAILED", "CANCELLED", "ERROR"):
            raise RuntimeError(f"Query {state}: {json.dumps(resp)[:500]}")
        if state not in ("RUNNING", "NOT_STARTED"):
            # Some responses return the result inline with no explicit state
            if "result" in resp:
                return resp["result"].get("records", []) or []
            raise RuntimeError(f"Unexpected response: {json.dumps(resp)[:500]}")

        token = resp.get("requestToken")
        if not token:
            raise RuntimeError(f"RUNNING but no requestToken: {json.dumps(resp)[:500]}")
        if time.monotonic() > deadline:
            raise RuntimeError(f"Query timed out after {POLL_TIMEOUT_SECONDS}s")
        time.sleep(POLL_INTERVAL_SECONDS)
        poll_url = (
            DT_ENVIRONMENT_URL + QUERY_POLL_PATH
            + "?request-token=" + urllib.parse.quote(token)
        )
        resp = _http_json("GET", poll_url)


# ---------------------------------------------------------------------------
# Doc population
# ---------------------------------------------------------------------------

# DQL caps result records at 1000 by default; raise it so we get every key.
METRICS_QUERY = "metrics | sort metric.key asc | limit 50000"


def populate_metric_keys():
    print(f"Fetching metric keys ({METRICS_QUERY}) ...")
    records = run_dql(METRICS_QUERY)
    # Dedup while preserving sort order — the metrics table can return a key
    # more than once (e.g. multiple dimension definitions).
    seen = set()
    keys = []
    for r in records:
        k = r.get("metric.key")
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    print(f"  got {len(records)} rows, {len(keys)} unique metric keys")

    lines = [
        "# Metric Keys Reference",
        f"# Auto-generated by dt_fetch.py from {DT_ENVIRONMENT_URL}",
        f"# Queried: {_now_stamp()}",
        f"# Query: {METRICS_QUERY}  ({len(keys)} unique keys)",
        "",
        "```",
        *keys,
        "```",
        "",
    ]
    out = DOCS_DIR / "metric_keys.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {out}")


# (section title, source) — `describe <source>` returns the full field schema
# (field name + data type) WITHOUT needing any data in the source, so it works
# even on empty tenants where `fetch ... | limit 1` returns nothing.
SCHEMA_SOURCES = [
    ("Host Entity (dt.entity.host)", "dt.entity.host"),
    ("Service Entity (dt.entity.service)", "dt.entity.service"),
    ("Process Group (dt.entity.process_group)", "dt.entity.process_group"),
    ("Process Group Instance (dt.entity.process_group_instance)",
     "dt.entity.process_group_instance"),
    ("Cloud Application / K8s Workload (dt.entity.cloud_application)",
     "dt.entity.cloud_application"),
    ("Kubernetes Cluster (dt.entity.kubernetes_cluster)", "dt.entity.kubernetes_cluster"),
    ("Logs", "logs"),
    ("Events", "events"),
    ("Spans", "spans"),
    ("Business Events", "bizevents"),
]


def populate_entity_schemas():
    print("Fetching entity / data-source schemas (via describe) ...")
    blocks = [
        "# Entity and Data Source Schemas",
        f"# Auto-generated by dt_fetch.py from {DT_ENVIRONMENT_URL}",
        f"# Queried: {_now_stamp()}",
        "# Each section lists every field and its data type(s), from `describe <source>`.",
        "",
    ]
    for title, source in SCHEMA_SOURCES:
        query = f"describe {source}"
        print(f"  {title}: {query}")
        try:
            records = run_dql(query)
        except RuntimeError as e:
            blocks += [f"## {title}", f"Query: `{query}`", "", f"_Error: {e}_", ""]
            print(f"    skipped ({str(e).splitlines()[0]})")
            continue
        # describe returns rows of {field, data_types:[...]}
        rows = sorted(
            ((r.get("field", ""), "|".join(r.get("data_types") or [])) for r in records),
            key=lambda x: x[0],
        )
        blocks.append(f"## {title}")
        blocks.append(f"Query: `{query}`  ({len(rows)} fields)")
        blocks.append("")
        if rows:
            width = max(len(f) for f, _ in rows)
            blocks.append("```")
            blocks += [f"{f:<{width}}  {t}" for f, t in rows]
            blocks.append("```")
        else:
            blocks.append("_No fields returned._")
        blocks.append("")

    print("  fetching list of all entity types ...")
    try:
        ents = run_dql(
            'fetch dt.system.data_objects | filter startsWith(name, "dt.entity.") '
            "| fields name | sort name asc"
        )
        names = [r.get("name") for r in ents if r.get("name")]
        blocks += ["## All Available Entity Types",
                   f"({len(names)} types)", "", "```", *names, "```", ""]
    except RuntimeError as e:
        blocks += ["## All Available Entity Types", f"_Error: {e}_", ""]

    out = DOCS_DIR / "entity_schemas.md"
    out.write_text("\n".join(blocks), encoding="utf-8")
    print(f"  wrote {out}")


def test_connection():
    print(f"Testing connection to {DT_ENVIRONMENT_URL} ...")
    records = run_dql("metrics | limit 1")
    print("Success. Sample record:")
    print(json.dumps(records[0] if records else {}, indent=2)[:500])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    _require_config()
    cmd = sys.argv[1].lower()
    if cmd == "metrics":
        populate_metric_keys()
    elif cmd == "schemas":
        populate_entity_schemas()
    elif cmd == "all":
        populate_metric_keys()
        populate_entity_schemas()
    elif cmd == "test":
        test_connection()
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: metrics, schemas, all, test")
        sys.exit(1)


if __name__ == "__main__":
    main()
