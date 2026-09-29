"""Docs search, name lookup, the DQL check, the tools, and the agent loop.

The loop is provider-neutral (see llm.py) and reports what it does through
events, so the same agent drives the terminal (util/dql_agent.py) and the
browser chat (web.py). Events: thinking, tool, query, lint, skipped, result,
query_error, visual, visual_error, answer.
"""

import json
import math
import os
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from . import REPO_ROOT
from . import llm, visuals

import dt_fetch  # noqa: E402  (repo root; loads .env as a side effect)

DOCS_DIR = REPO_ROOT / "docs"
DOC_SUFFIXES = {".md", ".txt", ".dql", ".json", ".yaml", ".yml"}
SKILL_FILE = REPO_ROOT / ".github" / "agents" / "dql-expert.md"

SCAN_LIMIT_GB = int(os.getenv("DQL_AGENT_SCAN_LIMIT_GB", "50"))
MAX_TURNS = int(os.getenv("DQL_AGENT_MAX_TURNS", "10"))   # model calls per question
ROWS_TO_MODEL = 50        # records sent back to the model per query
ROWS_TO_UI = 200          # records the browser shows under a query
CELL_CHARS = 300          # longest single value sent back to the model
KEEP_RESULTS = 20         # query results kept for visuals, per conversation


# ---------------------------------------------------------------------------
# Knowledge-base search (BM25 over docs/, no embeddings)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9_][a-z0-9_.]*")


def _tokens(text: str) -> list[str]:
    """Words, plus the parts of dotted names, so `dt.host.cpu.usage` matches
    both itself and `cpu`."""
    out = []
    for tok in _TOKEN.findall(text.lower()):
        tok = tok.strip(".")
        if not tok:
            continue
        out.append(tok)
        if "." in tok:
            out.extend(p for p in tok.split(".") if p)
    return out


def _chunks(path: Path, max_chars: int = 1800) -> list[str]:
    """Split a doc at its headings, then cap each piece at max_chars on line
    boundaries. Each piece keeps the heading it sits under."""
    text = path.read_text(encoding="utf-8", errors="replace")
    sections, heading, buf, in_fence = [], "", [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        is_heading = line.startswith("#") and not in_fence
        if is_heading and buf:
            sections.append((heading, buf))
            buf = []
        if is_heading:
            heading = line.lstrip("#").strip()
        buf.append(line)
    if buf:
        sections.append((heading, buf))

    out = []
    for heading, lines in sections:
        piece, size = [], 0
        for line in lines:
            if piece and size + len(line) > max_chars:
                out.append("\n".join(piece))
                piece, size = ([f"## {heading} (continued)"] if heading else []), 0
            piece.append(line)
            size += len(line) + 1
        if any(p.strip() for p in piece):
            out.append("\n".join(piece))
    return out


class DocIndex:
    def __init__(self, docs_dir: Path = DOCS_DIR):
        self.docs_dir = docs_dir
        self.chunks: list[tuple[str, str]] = []
        for path in sorted(docs_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in DOC_SUFFIXES \
                    and path.name != "README.md":
                rel = path.relative_to(docs_dir).as_posix()
                self.chunks.extend((rel, c) for c in _chunks(path))
        self.tfs = [Counter(_tokens(c)) for _, c in self.chunks]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg_len = (sum(self.lens) / len(self.lens)) if self.lens else 1.0
        df = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(self.chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, top_k: int = 6) -> list[tuple[str, str, float]]:
        k1, b = 1.5, 0.75
        terms = set(_tokens(query))
        scored = []
        for i, tf in enumerate(self.tfs):
            s = 0.0
            for t in terms:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (k1 + 1) / (
                        f + k1 * (1 - b + b * self.lens[i] / self.avg_len))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [(self.chunks[i][0], self.chunks[i][1], round(s, 2))
                for s, i in scored[:top_k]]


class NameIndex:
    """Exact lookup of this tenant's metric keys and field names, from the
    files dt_fetch.py writes. Keyword search ranks prose; this answers
    "does this key exist" with a yes or no."""

    def __init__(self, docs_dir: Path = DOCS_DIR):
        self.entries: list[str] = []
        metrics = docs_dir / "metric_keys.md"
        if metrics.exists():
            for line in metrics.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "`")):
                    self.entries.append(f"metric  {line}")
        schemas = docs_dir / "entity_schemas.md"
        if schemas.exists():
            source, in_fence = "", False
            for line in schemas.read_text(encoding="utf-8").splitlines():
                if line.startswith("## "):
                    m = re.search(r"\(([^)]+)\)\s*$", line)
                    source = m.group(1) if m else line[3:].strip()
                elif line.startswith("```"):
                    in_fence = not in_fence
                elif in_fence and line.strip():
                    self.entries.append(f"{source}  {' '.join(line.split())}")

    def find(self, text: str, limit: int = 60) -> list[str]:
        terms = text.lower().split()
        hits = [e for e in self.entries if all(t in e.lower() for t in terms)]
        return hits[:limit] + ([f"... {len(hits) - limit} more; narrow the search"]
                               if len(hits) > limit else [])


# ---------------------------------------------------------------------------
# Tools (neutral format; llm.py converts per provider)
# ---------------------------------------------------------------------------

def _tool(name, description, properties, required):
    return {"name": name, "description": description,
            "schema": {"type": "object", "properties": properties, "required": required}}


TOOL_SEARCH = _tool(
    "search_docs",
    "Search the DQL reference in docs/: syntax, working examples, common mistakes, "
    "and this tenant's metric keys and field names. Keyword search, so use the words "
    "likely to appear in the doc (command names, metric-key fragments such as "
    "'cpu.usage', field names).",
    {"query": {"type": "string", "description": "Keywords to look for."},
     "top_k": {"type": "integer", "description": "Results, default 6."}},
    ["query"])

TOOL_FIND = _tool(
    "find_names",
    "Look up this tenant's real metric keys and field names. Every word must appear "
    "in the entry (substring, case-insensitive). Examples: 'host memory', "
    "'dt.kubernetes cpu', 'logs loglevel', 'dt.entity.service name'. Each line is "
    "'metric <key>' or '<data source> <field> <type>'.",
    {"text": {"type": "string", "description": "Words to match."}},
    ["text"])

TOOL_RUN = _tool(
    "run_dql",
    "Run one DQL query against the user's Dynatrace tenant (read-only) and return a "
    "result_id, the field names, up to 50 records and the scanned bytes, or the error "
    "Grail reported. Include a timeframe (from:-1h, from:-24h) and a limit. The user "
    "may decline to run it.",
    {"query": {"type": "string", "description": "The DQL query."}},
    ["query"])

TOOL_TIMESERIES = _tool(
    "show_timeseries",
    "Draw a line chart in the chat from a timeseries (or makeTimeseries) result you "
    "already have. The numbers come from that result's records.",
    {"result_id": {"type": "string", "description": "From run_dql, e.g. r2."},
     "value_field": {"type": "string", "description": "The array field, e.g. usage."},
     "series_field": {"type": "string",
                      "description": "Field naming each line, e.g. entity.name or "
                                     "dt.entity.host. Omit for a single series."},
     "title": {"type": "string", "description": "Short title, sentence case."},
     "unit": {"type": "string", "description": "Unit of the values, e.g. %, ms, GB."}},
    ["result_id", "value_field", "title"])

TOOL_BAR = _tool(
    "show_bar",
    "Draw a horizontal bar chart of one number per row (top N, largest first) from a "
    "result you already have, e.g. errors per host or CPU per namespace with "
    "scalar:true.",
    {"result_id": {"type": "string"},
     "label_field": {"type": "string", "description": "Field naming each bar."},
     "value_field": {"type": "string", "description": "Numeric field."},
     "title": {"type": "string"},
     "unit": {"type": "string"},
     "limit": {"type": "integer", "description": "Bars to show, default 20, at most 30."}},
    ["result_id", "label_field", "value_field", "title"])

TOOL_GRAPH = _tool(
    "show_graph",
    "Draw a node graph from a result whose rows each link a source to one or more "
    "targets: smartscapeEdges rows (source_id -> target_id), who calls whom, or a "
    "problem and its affected_entity_ids. Node types and colours come from the ids.",
    {"result_id": {"type": "string"},
     "source_field": {"type": "string", "description": "e.g. source_id"},
     "target_field": {"type": "string",
                      "description": "e.g. target_id; may be an array field"},
     "source_label_field": {"type": "string", "description": "Optional name field."},
     "target_label_field": {"type": "string", "description": "Optional name field."},
     "edge_label_field": {"type": "string", "description": "Optional, e.g. type."},
     "highlight": {"type": "array", "items": {"type": "string"},
                   "description": "Node ids or names to emphasise."},
     "title": {"type": "string"}},
    ["result_id", "source_field", "target_field", "title"])

VISUAL_TOOLS = [TOOL_TIMESERIES, TOOL_BAR, TOOL_GRAPH]

CHAT_RULES = """You are a chat assistant for engineers who operate Dynatrace. \
They ask plain questions ("any open problems?", "which hosts are hot?", \
"errors in payments?"). You answer by writing DQL, running it on their tenant, \
and reading the records. DQL is easy to get wrong and you will be tempted to \
guess. Don't: the reference below, search_docs and find_names are the truth.

How to work:
1. Map the question to a data source. search_docs first; \
docs/dql_common_questions.md maps common questions (problems, CPU, errors, \
Kubernetes) to a query that runs. Start from that query and adapt it.
2. Check every metric key and field name with find_names. Never invent one.
3. {run_step}

How to reply:
- This is a chat. Be short. No preamble. In this order:
  1. Summary: one or two sentences that answer the question from the \
records (the number, the verdict, the top item).
  2. Worth a look: things in the records the reader would want to know \
even though they did not ask: an outlier, errors, a spike, one host or \
service carrying most of the load, a value near a limit, data that looks \
missing, a result that was cut off. At most three bullets, each naming the \
entity and the number. Put them in a blockquote that starts with \
"**Worth a look**". Leave the section out when nothing stands out; never \
pad it or speculate beyond the records.
  3. Details: a compact table for lists (at most 15 rows, say if there are \
more), only when it adds to the summary.
  4. The query that produced it in a ```dql block.
- If the question is vague, choose the sensible reading, run it, and say in \
one line what you assumed.
- Only show a query that ran, or one the user chose not to run.
- If you cannot make a query work after three tries, show the last error in \
one line and ask one question. Do not fall back to general advice about the \
Dynatrace UI or REST API.
- Never say a data source or field does not exist unless search_docs, \
find_names or `describe` showed it. `fetch dt.system.data_objects` lists every \
data source.
- Always bound the time range (from:-1h) and rows (| limit). Never add \
scanLimitGBytes.
"""

VISUAL_RULES = """
Visuals (the chat can draw):
- When a picture makes the answer clearer, call show_timeseries (a trend over \
time), show_bar (compare one number across hosts, services, namespaces) or \
show_graph (who calls whom, what a problem affects), with the result_id of a \
query you ran. They draw from that result's records; you never supply numbers.
- For a trend, run timeseries without scalar:true so the values are arrays. \
For a bar chart, use scalar:true or summarize so there is one number per row. \
For a call graph, smartscapeEdges rows give source_id and target_id; add \
getNodeName() fields for readable names.
- One visual per point. None for a single number. After a visual, still state \
the key numbers in text; the reader may not look at the chart.
- In show_graph, pass the entities you call out under "Worth a look" as \
highlight, so the graph marks them.
"""

RUN_STEP_ON = ("Run it with run_dql. When you need to see a source's real "
               "fields, run `describe <source>` or `fetch <source>, from:-15m "
               "| limit 3` first. If the query is rejected, read the error, fix "
               "that exact problem and run it again. If the result is empty, "
               "say whether the filter or the data is the likely reason.")
RUN_STEP_OFF = ("There is no tenant connection, so the query cannot be run. "
                "Check it against the docs line by line instead, and say that it "
                "has not been run.")


def _load_skill() -> str:
    """The @dql-expert agent's rules, shared with Copilot: .github/agents/dql-expert.md."""
    try:
        return SKILL_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_system_prompt(can_run: bool, visuals_on: bool = False) -> str:
    rules = CHAT_RULES.replace("{run_step}", RUN_STEP_ON if can_run else RUN_STEP_OFF)
    if visuals_on and can_run:
        rules += VISUAL_RULES
    skill = _load_skill()
    if skill:
        rules += "\n\n# DQL reference (from .github/agents/dql-expert.md)\n\n" + skill
    return rules


# Mistakes models make over and over. Caught here, before Grail is asked, so
# the model gets a precise correction instead of a parse error.
_SQL = re.compile(r"(^|\|)\s*(select|where|group\s+by|order\s+by|having|join\s+\w+\s+on)\b",
                  re.IGNORECASE | re.MULTILINE)
_FETCH_NO_COMMA = re.compile(
    r"\bfetch\s+[\w.]+\s+(from|to|bucket|timeframe|samplingRatio|scanLimitGBytes)\s*:")
_FETCH_SOURCE = re.compile(r"\bfetch\s+([\w.]+)")
_BY_NO_BRACES = re.compile(r"\bby\s*:\s*(?!\{)")
_METRIC_PREFIXES = ("dt.host.", "dt.service.", "dt.containers.", "dt.kubernetes.",
                    "dt.process.", "dt.cloud.", "dt.synthetic.", "dt.frontend.")
_SQL_FIX = {"select": "fields", "where": "filter", "group by": "summarize ..., by:{...}",
            "order by": "sort", "having": "filter after summarize",
            "join": "join [subquery], on:{field}"}


def lint_dql(query: str, metric_keys: set[str]) -> list[str]:
    problems = []
    for m in _SQL.finditer(query):
        word = " ".join(m.group(2).lower().split()[:2])
        word = "join" if word.startswith("join") else word
        problems.append(f"`{m.group(2)}` is SQL; DQL uses `{_SQL_FIX.get(word, '?')}`.")
    if _FETCH_NO_COMMA.search(query):
        problems.append("Parameters after `fetch <source>` need a comma: "
                        "`fetch logs, from:-1h`.")
    for m in _FETCH_SOURCE.finditer(query):
        src = m.group(1)
        if src in metric_keys or (src.startswith(_METRIC_PREFIXES)):
            problems.append(f"`{src}` is a metric. Use `timeseries avg({src}), ...`, "
                            "not `fetch`.")
    if _BY_NO_BRACES.search(query):
        problems.append("`by:` needs braces: `by:{field}`.")
    if "scanlimitgbytes" in query.lower():
        problems.append("Remove scanLimitGBytes; the agent sets the scan limit.")
    return problems


def _fmt_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def _clip(value):
    if isinstance(value, str):
        return value if len(value) <= CELL_CHARS else value[:CELL_CHARS] + "…"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, default=str)
        return value if len(text) <= CELL_CHARS else text[:CELL_CHARS] + "…"
    return value


def _query_grail(query: str) -> tuple[dict | None, str]:
    """(Grail result, error text)."""
    try:
        return dt_fetch.run_dql_result(query, max_records=1000,
                                       scan_limit_gbytes=SCAN_LIMIT_GB), ""
    except RuntimeError as e:
        return None, str(e)[:3000]


def _summarize(result: dict, rows: int = ROWS_TO_MODEL) -> dict:
    records = result.get("records", []) or []
    grail = (result.get("metadata") or {}).get("grail") or {}
    fields = []
    for rec in records[:rows]:
        for key in rec:
            if key not in fields:
                fields.append(key)
    out = {
        "record_count": len(records),
        "fields": fields,
        "records": [{k: _clip(v) for k, v in rec.items()} for rec in records[:rows]],
        "scanned": _fmt_bytes(grail.get("scannedBytes")),
    }
    if len(records) > rows:
        out["note"] = f"Only the first {rows} of {len(records)} records are shown."
    else:
        out["complete"] = True      # every record Grail returned is here; nothing was cut
    notes = [n.get("message") for n in grail.get("notifications", []) or []
             if isinstance(n, dict) and n.get("message")]
    if notes:
        out["grail_notifications"] = notes[:5]
    return out


# The chat's opening hint: a fixed, read-only query (docs/dql_common_questions.md),
# run by the server, never written by the model.
OPEN_PROBLEMS_DQL = """fetch dt.davis.problems, from:-7d
| filter event.status == "ACTIVE"
| fields event.start, display_id, event.name, event.category, affected_entity_ids
| sort event.start desc
| limit 50"""


def open_problems(top: int = 5) -> dict:
    """Open Davis problems for the chat's welcome card: how many, by category,
    and the newest few. {"error": ...} when Grail refuses."""
    result, error = _query_grail(OPEN_PROBLEMS_DQL)
    if result is None:
        return {"error": _error_summary(error)}
    seen, items = set(), []
    for r in result.get("records") or []:
        pid = r.get("display_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        start = visuals._ts_ms(r.get("event.start"))
        affected = r.get("affected_entity_ids")
        items.append({"id": pid, "name": r.get("event.name") or "",
                      "category": r.get("event.category") or "",
                      "start": start / 1000 if start else None,
                      "affected": len(affected) if isinstance(affected, list) else 0})
    items.sort(key=lambda p: p["start"] or 0, reverse=True)
    grail = (result.get("metadata") or {}).get("grail") or {}
    return {"open": len(items), "by_category": dict(Counter(p["category"] for p in items)),
            "items": items[:top], "scanned": _fmt_bytes(grail.get("scannedBytes")),
            "query": OPEN_PROBLEMS_DQL}


def run_dql_tool(query: str) -> tuple[dict, bool]:
    """Returns (result for the model, ok). Kept for callers of the old helper."""
    result, error = _query_grail(query)
    if result is None:
        return {"error": error}, False
    return _summarize(result), True


def _error_summary(error: str) -> str:
    """Grail's message plus its detail and position when the error body is
    JSON (PARSE_ERROR alone says nothing), else the first line."""
    for line in error.splitlines()[1:]:
        try:
            body = json.loads(line)
        except ValueError:
            continue
        err = body.get("error") if isinstance(body, dict) else None
        if not isinstance(err, dict):
            continue
        details = err.get("details") or {}
        parts = [err.get("message") or ""]
        if details.get("errorMessage") and details["errorMessage"] != parts[0]:
            parts.append(details["errorMessage"])
        pos = (details.get("syntaxErrorPosition") or {}).get("start") or {}
        if pos.get("line") is not None:
            parts.append(f"(line {pos.get('line')}, column {pos.get('column')})")
        text = ": ".join(p for p in parts[:2] if p)
        if len(parts) > 2:
            text += " " + parts[2]
        if text:
            return text[:500]
    return error.splitlines()[0][:300] if error else "unknown error"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _say(msg: str):
    print(msg, file=sys.stderr, flush=True)


def terminal_events(kind: str, data: dict):
    """How the terminal shows the agent's steps (stderr, so answers pipe cleanly)."""
    if kind == "tool":
        _say(f"  · {data['name']}: {data['detail']}")
    elif kind == "query":
        _say("  · run_dql:\n" + "\n".join("      " + ln for ln in data["query"].splitlines()))
    elif kind == "lint":
        _say("    not run: " + " ".join(data["issues"]))
    elif kind == "skipped":
        _say("    skipped")
    elif kind == "result":
        _say(f"    {data['record_count']} records, {data['scanned']} scanned")
    elif kind == "query_error":
        _say("    error: " + data["summary"])


def terminal_approver(query: str) -> tuple[bool, str]:
    """(run it, what the user said instead). Anything other than y/n is taken
    as an instruction for the model."""
    if not sys.stdin.isatty():
        return False, ""
    try:
        ans = input("  Run it? [Y/n, or say what to change] ").strip()
    except EOFError:
        return False, ""
    if ans.lower() in ("", "y", "yes"):
        return True, ""
    if ans.lower() in ("n", "no"):
        return False, ""
    return False, ans


class Agent:
    """One conversation. `model` is an llm.ChatModel (an aws.Bedrock client
    also works, for callers written before the adapters existed).

    approve:   "ask" (call `approver`), "always", or "never"
    visuals:   offer show_timeseries / show_bar / show_graph (needs a UI that draws)
    on_event:  callable(kind, data); defaults to terminal output
    """

    def __init__(self, model, index: DocIndex | None = None, can_run: bool = True,
                 approve: str = "ask", visuals_on: bool = False, on_event=None,
                 approver=None, max_turns: int | None = None,
                 max_tokens: int | None = None):
        if not isinstance(model, llm.ChatModel) and hasattr(model, "converse"):
            model = llm.BedrockModel(client=model)
        self.model = model
        self.index = index or DocIndex()
        self.names = NameIndex(self.index.docs_dir)
        self.can_run = can_run
        self.approve = approve
        self.visuals_on = visuals_on and can_run
        self.on_event = on_event or terminal_events
        self.approver = approver or terminal_approver
        self.max_turns = max_turns or MAX_TURNS
        self.max_tokens = max_tokens
        self.cancel = None      # a threading.Event: set, and a model that can stops mid-reply
        self.messages: list[dict] = []
        self.results: OrderedDict[str, dict] = OrderedDict()
        self._result_seq = 0
        self.last_query: str | None = None
        self.system = build_system_prompt(can_run, self.visuals_on)
        self.metric_keys = {e.split()[-1] for e in self.names.entries
                            if e.startswith("metric ")}
        self.tools = [TOOL_SEARCH, TOOL_FIND] + ([TOOL_RUN] if can_run else []) \
            + (VISUAL_TOOLS if self.visuals_on else [])

    def emit(self, kind: str, **data):
        self.on_event(kind, data)

    def reset(self):
        self.messages = []
        self.results.clear()

    def state(self) -> dict:
        """What a conversation needs to carry on later: the model's messages and
        the query results visuals draw from. Plain JSON."""
        return {"messages": self.messages, "results": list(self.results.items()),
                "result_seq": self._result_seq}

    def snapshot(self) -> dict:
        """state() as it is now, unaffected by a question asked afterwards
        (earlier messages are never changed in place, only appended to)."""
        return {"messages": list(self.messages), "results": list(self.results.items()),
                "result_seq": self._result_seq}

    def load_state(self, state: dict):
        self.messages = list(state.get("messages") or [])
        self.results = OrderedDict((rid, r) for rid, r in state.get("results") or [])
        self._result_seq = int(state.get("result_seq") or len(self.results))

    # -- tools -------------------------------------------------------------
    def _run_query(self, q: str) -> tuple[str, bool]:
        self.last_query = q
        self.emit("query", query=q)
        issues = lint_dql(q, self.metric_keys)
        if issues:
            self.emit("lint", issues=issues)
            return "Not run; fix these and call run_dql again:\n- " + "\n- ".join(issues), False
        if self.approve == "always":
            run, said = True, ""
        elif self.approve == "never":
            run, said = False, ""
        else:
            run, said = self.approver(q)
        if not run:
            self.emit("skipped", said=said)
            if said:
                return f"Not run. The user said: {said}\nChange the query accordingly.", False
            return ("Not run; the user declined. Stop calling tools and ask, in one "
                    "short sentence, what to change."), False
        result, error = _query_grail(q)
        if result is None:
            summary = _error_summary(error)
            self.emit("query_error", query=q, summary=summary)
            return json.dumps({"error": summary, "raw": error[:2000]}), False
        self._result_seq += 1
        rid = f"r{self._result_seq}"
        self.results[rid] = {"query": q, "records": result.get("records", []) or []}
        while len(self.results) > KEEP_RESULTS:
            self.results.popitem(last=False)
        for_model = {"result_id": rid, **_summarize(result)}
        preview = _summarize(result, ROWS_TO_UI)
        self.emit("result", result_id=rid, query=q, record_count=for_model["record_count"],
                  scanned=for_model["scanned"], fields=preview["fields"],
                  rows=preview["records"], notes=for_model.get("grail_notifications", []))
        return json.dumps(for_model, default=str), True

    def _visual(self, name: str, args: dict) -> tuple[str, bool]:
        rid = str(args.get("result_id", ""))
        stored = self.results.get(rid)
        if not stored:
            return (f"No result {rid!r}. Use a result_id that run_dql returned in this "
                    f"conversation: {', '.join(self.results) or 'none yet'}."), False
        records = stored["records"]
        try:
            if name == "show_timeseries":
                spec = visuals.timeseries(records, str(args.get("value_field", "")),
                                          args.get("series_field") or None,
                                          str(args.get("title", "")), str(args.get("unit", "")))
                note = (f"Shown: {len(spec['series'])} series, "
                        f"{max(len(s['points']) for s in spec['series'])} points each.")
            elif name == "show_bar":
                spec = visuals.bar(records, str(args.get("label_field", "")),
                                   str(args.get("value_field", "")), str(args.get("title", "")),
                                   str(args.get("unit", "")), args.get("limit") or 20)
                note = f"Shown: {len(spec['bars'])} bars, largest {spec['bars'][0]['value']:g}."
            else:
                highlight = args.get("highlight")
                spec = visuals.graph(records, str(args.get("source_field", "")),
                                     str(args.get("target_field", "")),
                                     args.get("source_label_field") or None,
                                     args.get("target_label_field") or None,
                                     args.get("edge_label_field") or None,
                                     str(args.get("title", "")),
                                     highlight if isinstance(highlight, list) else None)
                note = f"Shown: {len(spec['nodes'])} nodes, {len(spec['edges'])} edges."
        except visuals.VisualError as e:
            self.emit("visual_error", tool=name, message=str(e))
            return f"Not drawn: {e}", False
        if spec.get("dropped"):
            note += f" {spec['dropped']} more not shown."
        spec["source"] = {"result_id": rid, "query": stored["query"]}
        self.emit("visual", spec=spec)
        return note, True

    def _call_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if "_invalid_arguments" in args:
            return ("The tool arguments were not valid JSON (possibly cut off). "
                    "Call the tool again with complete arguments."), False
        if name == "search_docs":
            q = str(args.get("query", ""))
            try:
                top_k = max(1, min(int(args.get("top_k") or 6), 12))
            except (TypeError, ValueError):
                top_k = 6
            self.emit("tool", name=name, detail=q)
            hits = self.index.search(q, top_k)
            if not hits:
                return "No matching docs.", True
            return "\n\n".join(f"--- {src} (score {score}) ---\n{chunk}"
                               for src, chunk, score in hits), True
        if name == "find_names":
            q = str(args.get("text", ""))
            self.emit("tool", name=name, detail=q)
            hits = self.names.find(q)
            if not hits:
                return ("No match in docs/metric_keys.md or docs/entity_schemas.md. "
                        "Try fewer or shorter words. If it is still missing, the key "
                        "or field is not in this tenant's generated docs."), True
            return "\n".join(hits), True
        if name == "run_dql" and self.can_run:
            return self._run_query(str(args.get("query", "")).strip())
        if name in ("show_timeseries", "show_bar", "show_graph") and self.visuals_on:
            return self._visual(name, args)
        return f"Unknown tool {name}.", False

    # -- loop --------------------------------------------------------------
    def ask(self, question: str) -> str:
        """One question, answered after as many tool calls as it needs. On an
        error or interruption the conversation is rolled back to before the
        question, so a tool call is never left without its result."""
        start = len(self.messages)
        try:
            answer = self._ask(question)
        except BaseException:
            del self.messages[start:]
            raise
        self.emit("answer", text=answer)
        return answer

    def _call_model(self):
        self.emit("thinking")
        extra = {"cancel": self.cancel} if self.cancel is not None and \
            getattr(self.model, "supports_cancel", False) else {}
        reply = self.model.chat(self.system, self.messages, self.tools, self.max_tokens, **extra)
        self.messages.append({"role": "assistant", "content": reply["content"]})
        return reply

    def _ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": [{"type": "text", "text": question}]})
        for _ in range(self.max_turns):
            reply = self._call_model()
            calls = [b for b in reply["content"] if b.get("type") == "tool_call"]
            if not calls:
                text = llm._text(reply["content"])
                if reply["stop"] == "max_tokens":
                    text += "\n\n[answer cut off at the output-token limit]"
                elif reply["stop"] == "refusal" and not text:
                    text = "The model declined to answer this."
                return text.strip()
            results = []
            for call in calls:
                text, ok = self._call_tool(call.get("name", ""), call.get("input") or {})
                results.append({"type": "tool_result", "id": call["id"],
                                 "name": call.get("name", ""), "text": text,
                                 "is_error": not ok})
            self.messages.append({"role": "user", "content": results})
        # Out of turns: ask for an answer with what it has. The note joins the
        # last tool results, because roles must alternate (Converse rejects two
        # user messages in a row).
        self.messages[-1]["content"].append({"type": "text", "text": (
            "Stop calling tools. Answer with what you have, including the best "
            "query so far.")})
        reply = self._call_model()
        answer = llm._text(reply["content"]).strip() or \
            f"No answer within {self.max_turns} turns. Raise the turn limit or narrow the question."
        # Keep only the text: a tool call left without a result would make every
        # provider reject the next question.
        self.messages[-1]["content"] = [{"type": "text", "text": answer}]
        return answer
