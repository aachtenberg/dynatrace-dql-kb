"""
dql_agent.py — Ask questions about your Dynatrace tenant through a model on
Amazon Bedrock. The model searches this repo's DQL docs, writes a query, runs
it against the tenant, reads the error or the records, and answers.

Standard library only: no pip, no Docker, no MCP. Bedrock requests are signed
with SigV4 here, so boto3 is not needed. Grail queries reuse dt_fetch.py.

Usage:
    ./dql_agent.sh                      # interactive
    ./dql_agent.sh "hosts with CPU above 90% in the last hour"
    ./dql_agent.sh --check              # test credentials, model access and tenant
    ./dql_agent.sh --help

Configuration (environment variables, or .env in the repo root):
    BEDROCK_MODEL_ID      required; the model or inference-profile id enabled
                          in your account, e.g. us.anthropic.claude-sonnet-4-5-20250929-v1:0
    BEDROCK_REGION        default AWS_REGION, then AWS_DEFAULT_REGION, then us-east-1
    AWS credentials       see _aws_credentials() for the order they are looked up
    DT_ENVIRONMENT_URL    as for dt_fetch.py; without it the agent writes DQL
    DT_API_TOKEN          but cannot run it
    DQL_AGENT_SCAN_LIMIT_GB   per-query Grail scan cap, default 50
"""

import argparse
import configparser
import datetime
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import dt_fetch  # loads .env as a side effect

REPO_ROOT = Path(__file__).resolve().parent
DOCS_DIR = REPO_ROOT / "docs"
DOC_SUFFIXES = {".md", ".txt", ".dql", ".json", ".yaml", ".yml"}

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")
BEDROCK_REGION = (
    os.getenv("BEDROCK_REGION")
    or os.getenv("AWS_REGION")
    or os.getenv("AWS_DEFAULT_REGION")
    or "us-east-1"
)
SCAN_LIMIT_GB = int(os.getenv("DQL_AGENT_SCAN_LIMIT_GB", "50"))
MAX_TURNS = 10            # model calls per question
ROWS_TO_MODEL = 50        # records sent back to the model per query
CELL_CHARS = 300          # longest single value sent back to the model


# ---------------------------------------------------------------------------
# AWS credentials and SigV4
# ---------------------------------------------------------------------------

class AwsCredentials:
    def __init__(self, access_key, secret_key, token=None, source=""):
        self.access_key = access_key
        self.secret_key = secret_key
        self.token = token
        self.source = source


def _aws_credentials() -> AwsCredentials | None:
    """Look up credentials the way the AWS CLI does, minus what needs boto3.

    1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN
    2. ~/.aws/credentials, profile AWS_PROFILE or default, when it holds keys
    3. `aws configure export-credentials`, when the AWS CLI is installed. This
       covers SSO, assumed roles and credential_process.
    """
    key = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    if key and secret:
        return AwsCredentials(key, secret, os.getenv("AWS_SESSION_TOKEN"),
                              "environment variables")

    profile = os.getenv("AWS_PROFILE", "default")
    cred_file = Path(os.getenv("AWS_SHARED_CREDENTIALS_FILE",
                               Path.home() / ".aws" / "credentials"))
    if cred_file.exists():
        parser = configparser.ConfigParser()
        parser.read(cred_file, encoding="utf-8")
        if parser.has_section(profile):
            sect = parser[profile]
            if sect.get("aws_access_key_id") and sect.get("aws_secret_access_key"):
                return AwsCredentials(sect["aws_access_key_id"],
                                      sect["aws_secret_access_key"],
                                      sect.get("aws_session_token"),
                                      f"{cred_file} [{profile}]")

    aws = shutil.which("aws")
    if aws:
        cmd = [aws, "configure", "export-credentials", "--format", "process"]
        if os.getenv("AWS_PROFILE"):
            cmd += ["--profile", profile]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=60, check=True).stdout
            data = json.loads(out)
            return AwsCredentials(data["AccessKeyId"], data["SecretAccessKey"],
                                  data.get("SessionToken"),
                                  f"aws configure export-credentials [{profile}]")
        except (subprocess.SubprocessError, ValueError, KeyError):
            pass
    return None


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sigv4_headers(method: str, url: str, body: bytes, creds: AwsCredentials,
                  region: str, service: str,
                  now: datetime.datetime | None = None) -> dict:
    """Headers for an AWS Signature Version 4 request.

    `url` must already be percent-encoded. For every service except S3 the
    canonical path encodes it once more, so a model id's ':' is sent as %3A
    and signed as %253A.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    parts = urllib.parse.urlsplit(url)
    canonical_uri = urllib.parse.quote(parts.path or "/", safe="/-_.~")
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}"
        for k, v in sorted(query)
    )
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {"host": parts.netloc, "x-amz-date": amz_date}
    if creds.token:
        headers["x-amz-security-token"] = creds.token
    signed = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical_request = "\n".join([method, canonical_uri, canonical_query,
                                   canonical_headers, signed, payload_hash])
    scope = f"{date}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    k = _sign(("AWS4" + creds.secret_key).encode("utf-8"), date)
    k = _sign(k, region)
    k = _sign(k, service)
    k = _sign(k, "aws4_request")
    signature = hmac.new(k, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={creds.access_key}/{scope}, "
        f"SignedHeaders={signed}, Signature={signature}"
    )
    del headers["host"]  # urllib sends it
    return headers


# ---------------------------------------------------------------------------
# Bedrock Converse
# ---------------------------------------------------------------------------

class BedrockError(RuntimeError):
    pass


class Bedrock:
    def __init__(self, model_id: str, region: str):
        if not model_id:
            raise BedrockError(
                "BEDROCK_MODEL_ID is not set. Use the model or inference-profile "
                "id enabled in your account, e.g. "
                "us.anthropic.claude-sonnet-4-5-20250929-v1:0."
            )
        self.model_id = model_id
        self.region = region
        self.endpoint = os.getenv(
            "BEDROCK_ENDPOINT_URL", f"https://bedrock-runtime.{region}.amazonaws.com"
        ).rstrip("/")
        # A Bedrock API key, if the account issues them, replaces SigV4.
        self.api_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")
        self.creds = None if self.api_key else _aws_credentials()
        if not self.api_key and not self.creds:
            raise BedrockError(
                "No AWS credentials found. Set AWS_ACCESS_KEY_ID and "
                "AWS_SECRET_ACCESS_KEY (and AWS_SESSION_TOKEN), put keys in "
                "~/.aws/credentials, sign in with `aws sso login` if the AWS "
                "CLI is installed, or set AWS_BEARER_TOKEN_BEDROCK."
            )

    @property
    def auth_source(self) -> str:
        return "AWS_BEARER_TOKEN_BEDROCK" if self.api_key else self.creds.source

    def converse(self, messages, system=None, tools=None, max_tokens=4096):
        body = {
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
        }
        if system:
            body["system"] = [{"text": system}]
        if tools:
            body["toolConfig"] = {"tools": tools}
        data = json.dumps(body).encode("utf-8")
        url = (f"{self.endpoint}/model/"
               f"{urllib.parse.quote(self.model_id, safe='')}/converse")
        headers = {"content-type": "application/json", "accept": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        else:
            headers.update(sigv4_headers("POST", url, data, self.creds,
                                         self.region, "bedrock"))
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")
            try:
                detail = json.loads(detail).get("message", detail)
            except ValueError:
                pass
            raise BedrockError(f"Bedrock HTTP {e.code}: {detail}\n"
                               f"{_bedrock_hint(e.code, detail)}") from None
        except urllib.error.URLError as e:
            raise BedrockError(
                f"Cannot reach {self.endpoint}: {e.reason}. Behind a proxy, set "
                "HTTPS_PROXY. If TLS inspection breaks certificate checks, set "
                "SSL_CERT_FILE to your company CA bundle."
            ) from None


def _bedrock_hint(code: int, detail: str) -> str:
    low = detail.lower()
    if code == 403 and "security token" in low:
        return "The credentials are expired or wrong. Refresh them and try again."
    if code == 403:
        return ("The identity needs bedrock:InvokeModel on this model (and on the "
                "inference profile, if the id starts with us. or eu.).")
    if "access to the model" in low or "model access" in low:
        return "Ask your AWS admin to enable this model under Bedrock > Model access."
    if "on-demand throughput" in low or "inference profile" in low:
        return ("This model must be called through an inference profile. Try the "
                "id with a us. or eu. prefix.")
    if code == 404 or "identifier is invalid" in low:
        return f"Check BEDROCK_MODEL_ID and that the model exists in {BEDROCK_REGION}."
    if code == 429:
        return "Throttled. Wait a minute and ask again."
    return ""


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
# Tools
# ---------------------------------------------------------------------------

TOOL_SEARCH = {
    "toolSpec": {
        "name": "search_docs",
        "description": (
            "Search the DQL reference in docs/: syntax, working examples, common "
            "mistakes, and this tenant's metric keys and field names. Keyword "
            "search, so use the words likely to appear in the doc (command "
            "names, metric-key fragments such as 'cpu.usage', field names)."
        ),
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords to look for."},
                "top_k": {"type": "integer", "description": "Results, default 6."},
            },
            "required": ["query"],
        }},
    }
}

TOOL_FIND = {
    "toolSpec": {
        "name": "find_names",
        "description": (
            "Look up this tenant's real metric keys and field names. Every word "
            "must appear in the entry (substring, case-insensitive). Examples: "
            "'host memory', 'dt.kubernetes cpu', 'logs loglevel', "
            "'dt.entity.service name'. Each line is 'metric <key>' or "
            "'<data source> <field> <type>'."
        ),
        "inputSchema": {"json": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Words to match."}},
            "required": ["text"],
        }},
    }
}

TOOL_RUN = {
    "toolSpec": {
        "name": "run_dql",
        "description": (
            "Run one DQL query against the user's Dynatrace tenant (read-only) "
            "and return the field names, up to 50 records and the scanned bytes, "
            "or the error Grail reported. Include a timeframe (from:-1h, "
            "from:-24h) and a limit. The user may decline to run it."
        ),
        "inputSchema": {"json": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The DQL query."}},
            "required": ["query"],
        }},
    }
}

SYSTEM_PROMPT = """You answer questions about a Dynatrace environment by writing \
and running DQL (Dynatrace Query Language).

Work this way:
1. Before writing a query, call search_docs for the syntax or a similar \
example, and find_names for every metric key and field name you plan to use. \
Never guess one.
2. {run_step}
3. Answer in a few sentences, then give the final query in a ```dql block.

DQL rules that are easy to get wrong:
- Metrics use `timeseries`, never `fetch`. `fetch` is for logs, events, spans, \
bizevents and dt.entity.* tables.
- Grouping needs braces: `by:{{dt.entity.host}}`.
- No SQL: no SELECT, WHERE, GROUP BY or JOIN keywords. Commands are piped with `|`.
- `lookup` prefixes the fields it adds with `lookup.` unless you pass `prefix:""`.
- Always bound the time range (from:-1h) and the rows (| limit 100).
- Never add scanLimitGBytes to a query.
"""

RUN_STEP_ON = ("If the docs do not show the fields of the data you need, run "
               "`describe logs` (or spans, events, bizevents, dt.entity.host, ...) "
               "or `fetch logs, from:-15m | limit 3` first to see real names and "
               "values. Then call run_dql with the query. If Grail returns an error, read it, "
               "search_docs if needed, fix the query and run it again. If the "
               "result is empty, say whether the query or the data is the likely "
               "reason. Base the answer on the records, not on assumptions.")
RUN_STEP_OFF = ("There is no tenant connection, so do not try to run the query. "
                "Check it carefully against the docs instead, and if a metric "
                "key or field name is not in them, say so.")


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


def run_dql_tool(query: str) -> tuple[dict, bool]:
    """Returns (result for the model, ok)."""
    try:
        result = dt_fetch.run_dql_result(query, max_records=1000,
                                         scan_limit_gbytes=SCAN_LIMIT_GB)
    except RuntimeError as e:
        return {"error": str(e)[:3000]}, False
    records = result.get("records", []) or []
    grail = (result.get("metadata") or {}).get("grail") or {}
    fields = []
    for rec in records[:ROWS_TO_MODEL]:
        for key in rec:
            if key not in fields:
                fields.append(key)
    out = {
        "record_count": len(records),
        "fields": fields,
        "records": [{k: _clip(v) for k, v in rec.items()}
                    for rec in records[:ROWS_TO_MODEL]],
        "scanned": _fmt_bytes(grail.get("scannedBytes")),
    }
    if len(records) > ROWS_TO_MODEL:
        out["note"] = f"Only the first {ROWS_TO_MODEL} of {len(records)} records are shown."
    notes = [n.get("message") for n in grail.get("notifications", []) or []
             if isinstance(n, dict) and n.get("message")]
    if notes:
        out["grail_notifications"] = notes[:5]
    return out, True


def _error_summary(error: str) -> str:
    """Grail's own message when the error body is JSON, else the first line."""
    for line in error.splitlines()[1:]:
        try:
            body = json.loads(line)
        except ValueError:
            continue
        msg = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
        if msg:
            return msg[:300]
    return error.splitlines()[0][:300] if error else "unknown error"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _say(msg: str):
    print(msg, file=sys.stderr, flush=True)


class Agent:
    def __init__(self, bedrock: Bedrock, index: DocIndex, can_run: bool,
                 approve: str = "ask"):
        self.bedrock = bedrock
        self.index = index
        self.names = NameIndex(index.docs_dir)
        self.can_run = can_run
        self.approve = approve        # "ask", "always", "never"
        self.messages: list[dict] = []
        self.last_query: str | None = None
        self.system = SYSTEM_PROMPT.format(
            run_step=RUN_STEP_ON if can_run else RUN_STEP_OFF)
        self.tools = [TOOL_SEARCH, TOOL_FIND] + ([TOOL_RUN] if can_run else [])

    def reset(self):
        self.messages = []

    def _approved(self, query: str) -> bool:
        if self.approve == "always":
            return True
        if self.approve == "never" or not sys.stdin.isatty():
            return False
        try:
            ans = input("  Run this query? [Y/n] ").strip().lower()
        except EOFError:
            return False
        return ans in ("", "y", "yes")

    def _call_tool(self, name: str, args: dict) -> tuple[list, str]:
        if name == "search_docs":
            q = str(args.get("query", ""))
            top_k = max(1, min(int(args.get("top_k") or 6), 12))
            _say(f"  · search_docs: {q}")
            hits = self.index.search(q, top_k)
            if not hits:
                return [{"text": "No matching docs."}], "success"
            text = "\n\n".join(f"--- {src} (score {score}) ---\n{chunk}"
                               for src, chunk, score in hits)
            return [{"text": text}], "success"

        if name == "find_names":
            q = str(args.get("text", ""))
            _say(f"  · find_names: {q}")
            hits = self.names.find(q)
            if not hits:
                return [{"text": (
                    "No match in docs/metric_keys.md or docs/entity_schemas.md. "
                    "Try fewer or shorter words. If it is still missing, the key "
                    "or field is not in this tenant's generated docs.")}], "success"
            return [{"text": "\n".join(hits)}], "success"

        if name == "run_dql" and self.can_run:
            q = str(args.get("query", "")).strip()
            self.last_query = q
            _say("  · run_dql:\n" + "\n".join("      " + ln for ln in q.splitlines()))
            if not self._approved(q):
                _say("    skipped")
                return [{"text": "The user did not run this query. Give them the "
                                 "query and say what it should return."}], "error"
            result, ok = run_dql_tool(q)
            if ok:
                _say(f"    {result['record_count']} records, "
                     f"{result['scanned']} scanned")
            else:
                _say("    error: " + _error_summary(result["error"]))
            return [{"text": json.dumps(result, default=str)}], \
                "success" if ok else "error"

        return [{"text": f"Unknown tool {name}."}], "error"

    def ask(self, question: str) -> str:
        """One question, answered after as many tool calls as it needs. On an
        error or Ctrl-C the conversation is rolled back to before the question,
        so a tool call is never left without its result."""
        start = len(self.messages)
        try:
            return self._ask(question)
        except BaseException:
            del self.messages[start:]
            raise

    def _ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": [{"text": question}]})
        for _ in range(MAX_TURNS):
            resp = self.bedrock.converse(self.messages, self.system, self.tools)
            msg = resp.get("output", {}).get("message") or {}
            content = msg.get("content") or []
            self.messages.append({"role": "assistant", "content": content})
            uses = [c["toolUse"] for c in content if "toolUse" in c]
            if resp.get("stopReason") != "tool_use" or not uses:
                text = "\n".join(c["text"] for c in content if c.get("text"))
                if resp.get("stopReason") == "max_tokens":
                    text += "\n\n[answer cut off at the token limit]"
                return text.strip()
            results = []
            for use in uses:
                out, status = self._call_tool(use.get("name", ""), use.get("input") or {})
                results.append({"toolResult": {"toolUseId": use["toolUseId"],
                                               "content": out, "status": status}})
            self.messages.append({"role": "user", "content": results})
        # Out of turns: ask for an answer with what it has.
        self.messages.append({"role": "user", "content": [{"text": (
            "Stop calling tools. Answer with what you have, including the best "
            "query so far.")}]})
        resp = self.bedrock.converse(self.messages, self.system, self.tools)
        content = (resp.get("output", {}).get("message") or {}).get("content") or []
        self.messages.append({"role": "assistant", "content": content})
        return "\n".join(c["text"] for c in content if c.get("text")).strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HELP = """Commands:
  /new      start a new conversation
  /last     print the last query the model ran or proposed
  /auto     run queries without asking (toggle)
  /help     this list
  /exit     quit (Ctrl-D also works)"""


def _tenant_configured() -> bool:
    return bool(dt_fetch.DT_ENVIRONMENT_URL and dt_fetch.DT_API_TOKEN)


def check() -> int:
    ok = True
    index = DocIndex()
    names = NameIndex()
    print(f"docs:    {len(index.chunks)} sections, {len(names.entries)} metric keys "
          f"and fields, from {DOCS_DIR}")
    if "Auto-generated" not in (DOCS_DIR / "metric_keys.md").read_text(encoding="utf-8")[:500]:
        print("         metric_keys.md looks like the placeholder; run ./dt_fetch.sh all")

    try:
        bedrock = Bedrock(BEDROCK_MODEL_ID, BEDROCK_REGION)
        print(f"aws:     {bedrock.auth_source}")
        print(f"model:   {BEDROCK_MODEL_ID} in {BEDROCK_REGION}")
        resp = bedrock.converse(
            [{"role": "user", "content": [{"text": "Reply with the word OK."}]}],
            max_tokens=10)
        text = "".join(c.get("text", "") for c in
                       resp.get("output", {}).get("message", {}).get("content", []))
        print(f"         Converse answered: {text.strip()[:40]!r}")
    except BedrockError as e:
        ok = False
        print(f"bedrock: FAILED\n{e}")

    if _tenant_configured():
        print(f"tenant:  {dt_fetch.DT_ENVIRONMENT_URL}")
        result, good = run_dql_tool("fetch dt.entity.host | limit 1")
        if good:
            print(f"         query ran, {result['record_count']} record(s)")
        else:
            ok = False
            print("         FAILED\n" + result["error"])
    else:
        print("tenant:  not configured (DT_ENVIRONMENT_URL / DT_API_TOKEN); "
              "the agent will write queries but not run them")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ask a Bedrock model about your Dynatrace tenant. "
                    "It writes DQL, runs it, and answers from the result.")
    ap.add_argument("question", nargs="*", help="ask once and exit")
    ap.add_argument("--check", action="store_true",
                    help="test AWS credentials, model access and the tenant")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="run queries without asking")
    ap.add_argument("--no-run", action="store_true",
                    help="write queries but never run them")
    args = ap.parse_args()

    if args.check:
        return check()

    try:
        bedrock = Bedrock(BEDROCK_MODEL_ID, BEDROCK_REGION)
    except BedrockError as e:
        _say(f"ERROR: {e}")
        return 2
    can_run = _tenant_configured() and not args.no_run
    approve = "always" if args.yes else "ask"
    agent = Agent(bedrock, DocIndex(), can_run, approve)

    if args.question:
        if can_run and not args.yes and not sys.stdin.isatty():
            _say("stdin is not a terminal, so queries cannot be approved; "
                 "pass --yes to run them.")
        try:
            print(agent.ask(" ".join(args.question)))
        except BedrockError as e:
            _say(f"ERROR: {e}")
            return 1
        return 0

    _say(f"DQL agent · {BEDROCK_MODEL_ID} · "
         + (f"tenant {dt_fetch.DT_ENVIRONMENT_URL}" if can_run
            else "no tenant: queries are written, not run"))
    _say("Ask a question, or /help.")
    while True:
        try:
            line = input("\ndql> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/help":
            print(HELP)
            continue
        if line == "/new":
            agent.reset()
            print("New conversation.")
            continue
        if line == "/last":
            print(agent.last_query or "No query yet.")
            continue
        if line == "/auto":
            agent.approve = "ask" if agent.approve == "always" else "always"
            print("Queries run without asking." if agent.approve == "always"
                  else "You will be asked before each query.")
            continue
        try:
            print("\n" + agent.ask(line))
        except BedrockError as e:
            _say(f"ERROR: {e}")
        except KeyboardInterrupt:
            _say("\nInterrupted.")


if __name__ == "__main__":
    sys.exit(main())
