"""The browser chat: a small standard-library HTTP server around the agent.

It runs on your machine (the default) or in a container behind an
authenticating load balancer. Setup and deployment: util/dql_chat.md.

    GET  /                  the chat page (files in static/)
    GET  /healthz           200 "ok", for load balancers
    GET  /api/config        provider, settings (with current values), tenant
    GET  /api/models        options for the model picker, from the provider
    POST /api/settings      change this chat's settings
    POST /api/chat          ask; the reply is a text/event-stream of agent events
    POST /api/approve       answer a "run this query?" prompt
    POST /api/cancel        stop the answer in progress
    POST /api/reset         start a new conversation

Access (DQL_CHAT_AUTH):
    token   default. A random token in the URL printed at start; every API call
            must carry it. Host and Origin are checked, so another website
            open in the same browser cannot drive the chat.
    proxy   behind a load balancer that signs users in (ALB with OIDC or
            Cognito). The user id comes from DQL_CHAT_USER_HEADER, default
            x-amzn-oidc-identity; requests without it are refused.
    none    no check at all. Only for a network nobody else can reach.
"""

import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import aws, core, llm

import dt_fetch  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_BODY = 64 * 1024

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Cancelled(Exception):
    pass


class Config:
    def __init__(self, host=None, port=None, auth=None):
        self.host = host or os.getenv("DQL_CHAT_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("DQL_CHAT_PORT", "8750"))
        self.auth = (auth or os.getenv("DQL_CHAT_AUTH", "token")).strip().lower()
        if self.auth not in ("token", "proxy", "none"):
            raise SystemExit(f"DQL_CHAT_AUTH must be token, proxy or none, not {self.auth!r}.")
        self.token = os.getenv("DQL_CHAT_TOKEN") or secrets.token_urlsafe(24)
        self.user_header = os.getenv("DQL_CHAT_USER_HEADER", "x-amzn-oidc-identity").lower()
        self.auto_run = _env_flag("DQL_CHAT_AUTO_RUN")
        self.allow_settings = _env_flag("DQL_CHAT_ALLOW_SETTINGS", "1")
        self.max_sessions = int(os.getenv("DQL_CHAT_MAX_SESSIONS", "50"))
        self.idle_seconds = int(os.getenv("DQL_CHAT_IDLE_MINUTES", "240")) * 60
        self.approval_timeout = int(os.getenv("DQL_CHAT_APPROVAL_TIMEOUT", "600"))
        self.audit = os.getenv("DQL_CHAT_AUDIT", "queries").strip().lower()
        self.loopback = self.host in ("127.0.0.1", "localhost", "::1")


def audit(cfg: Config, **fields):
    """One JSON line per event on stdout: CloudWatch or a log file keeps it."""
    if cfg.audit == "off":
        return
    fields = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    print(json.dumps(fields, default=str), flush=True)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def common_fields(model: llm.ChatModel | None) -> list[dict]:
    default_tokens = int(os.getenv("DQL_AGENT_MAX_TOKENS") or 0) or (
        model.default_max_tokens if model else 4096)
    return [
        {"key": "max_turns", "label": "Turns per question", "type": "number",
         "default": core.MAX_TURNS, "min": 1, "max": 30,
         "help": "Model calls allowed for one question. Each search, check or query is one."},
        {"key": "max_tokens", "label": "Max output tokens per turn", "type": "number",
         "default": default_tokens, "min": 256, "max": 64000,
         "help": "Caps each model reply, thinking included. Too low cuts answers off."},
    ]


class Session:
    def __init__(self, server: "ChatServer", sid: str, user: str):
        self.server, self.id, self.user = server, sid, user
        self.lock = threading.Lock()            # one question at a time
        self.model_settings: dict = {}          # provider-specific, validated
        self.max_turns = core.MAX_TURNS
        self.max_tokens: int | None = None
        self.model: llm.ChatModel | None = None
        self.agent: core.Agent | None = None
        self.pending: dict[str, dict] = {}
        self.cancelled = threading.Event()
        self.writer = None
        self.last_used = time.time()

    # The model is built lazily; building a Bedrock one may look up the default.
    def get_model(self) -> llm.ChatModel:
        if self.model is None:
            settings = dict(self.model_settings)
            key = (llm.provider_name(), settings.get("region") or "")
            if not settings.get("model") and key in self.server.default_models:
                settings["model"] = self.server.default_models[key]
            self.model = llm.make_model(settings=settings)
            if not self.model_settings.get("model"):
                self.server.default_models[key] = self.model.settings.get("model", "")
        return self.model

    def get_agent(self) -> core.Agent:
        if self.agent is None:
            self.agent = core.Agent(self.get_model(), self.server.index, self.server.can_run,
                                    visuals_on=True, on_event=self.forward,
                                    approver=self.approver, max_turns=self.max_turns,
                                    max_tokens=self.max_tokens)
        return self.agent

    def fields(self) -> list[dict]:
        cls = llm.model_class()
        model = self.model
        out = []
        for f in common_fields(model):
            value = self.max_turns if f["key"] == "max_turns" else (self.max_tokens or f["default"])
            out.append({**f, "value": value})
        for f in cls.settings_fields():
            value = self.model_settings.get(f["key"])
            if value in (None, "") and model is not None:
                value = model.settings.get(f["key"])
            out.append({**f, "value": value if value not in (None, "") else f.get("default")})
        return out

    def apply_settings(self, values: dict):
        """Validate and apply. Changing the model or region starts a new chat."""
        common = {f["key"]: f for f in common_fields(self.model)}
        new_turns, new_tokens = self.max_turns, self.max_tokens
        provider_values = {}
        for key, value in values.items():
            if key in common:
                f = common[key]
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise llm.ModelError(f"{f['label']} must be a whole number.") from None
                if not f["min"] <= value <= f["max"]:
                    raise llm.ModelError(f"{f['label']} must be between {f['min']} and {f['max']}.")
                if key == "max_turns":
                    new_turns = value
                else:
                    new_tokens = value
            else:
                provider_values[key] = value
        clean = llm.model_class().validate(provider_values)
        changed = {k: v for k, v in clean.items() if v != self.model_settings.get(k)
                   and not (self.model is not None and v == self.model.settings.get(k))}
        if changed:
            candidate = {**self.model_settings, **clean}
            if "region" in changed and "model" not in changed:
                candidate.pop("model", None)    # a model id rarely spans regions
            model = llm.make_model(settings=candidate)     # raises if unusable
            self.model_settings = {k: v for k, v in candidate.items() if v not in (None, "")}
            self.model, self.agent = model, None
        self.max_turns, self.max_tokens = new_turns, new_tokens
        if self.agent is not None:
            self.agent.max_turns, self.agent.max_tokens = new_turns, new_tokens
        return bool(changed)

    # -- streaming and approval --------------------------------------------
    def forward(self, kind: str, data: dict):
        if self.cancelled.is_set():
            raise Cancelled()
        if kind == "result":
            audit(self.server.cfg, event="query", user=self.user, session=self.id,
                  query=data.get("query"), records=data.get("record_count"),
                  scanned=data.get("scanned"))
        elif kind == "query_error":
            audit(self.server.cfg, event="query_error", user=self.user, session=self.id,
                  query=data.get("query"), error=data.get("summary"))
        if self.writer is None or not self.writer.send(kind, data):
            self.cancelled.set()
            raise Cancelled()

    def approver(self, query: str) -> tuple[bool, str]:
        aid = secrets.token_hex(8)
        slot = {"event": threading.Event(), "run": False, "said": ""}
        self.pending[aid] = slot
        try:
            self.forward("approval", {"id": aid, "query": query})
            answered = slot["event"].wait(self.server.cfg.approval_timeout)
        finally:
            self.pending.pop(aid, None)
        if self.cancelled.is_set():
            raise Cancelled()
        if not answered:
            return False, ""
        return slot["run"], slot["said"]

    def release_approvals(self):
        for slot in list(self.pending.values()):
            slot["event"].set()


class SSEWriter:
    """Writes server-sent events; returns False once the browser has gone."""

    def __init__(self, wfile):
        self.wfile, self.lock, self.open = wfile, threading.Lock(), True

    def _write(self, payload: bytes) -> bool:
        with self.lock:
            if not self.open:
                return False
            try:
                self.wfile.write(payload)
                self.wfile.flush()
                return True
            except OSError:
                self.open = False
                return False

    def send(self, kind: str, data: dict) -> bool:
        body = json.dumps(data, default=str, ensure_ascii=False)
        return self._write(f"event: {kind}\ndata: {body}\n\n".encode("utf-8"))

    def ping(self) -> bool:
        return self._write(b": ping\n\n")


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class ChatServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.index = core.DocIndex()
        self.can_run = bool(dt_fetch.DT_ENVIRONMENT_URL and dt_fetch.DT_API_TOKEN)
        self.sessions: dict[str, Session] = {}
        self.sessions_lock = threading.Lock()
        self.default_models: dict = {}
        self.option_cache: dict = {}
        super().__init__((cfg.host, cfg.port), Handler)

    def session(self, sid: str, user: str) -> Session:
        key = f"{user}\x00{sid}"
        with self.sessions_lock:
            now = time.time()
            for k, s in list(self.sessions.items()):
                if now - s.last_used > self.cfg.idle_seconds and not s.lock.locked():
                    del self.sessions[k]
            sess = self.sessions.get(key)
            if sess is None:
                if len(self.sessions) >= self.cfg.max_sessions:
                    idle = sorted((s for s in self.sessions.values() if not s.lock.locked()),
                                  key=lambda s: s.last_used)
                    if not idle:
                        raise llm.ModelError("Too many chats are busy; try again shortly.")
                    del self.sessions[f"{idle[0].user}\x00{idle[0].id}"]
                sess = self.sessions[key] = Session(self, sid, user)
            sess.last_used = now
            return sess


class Handler(BaseHTTPRequestHandler):
    server: ChatServer
    server_version = "dql-chat"
    sys_version = ""

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):
        path = urllib.parse.urlsplit(self.path).path     # never log the token
        sys.stderr.write(f"{self.address_string()} {self.command} {path} {args[1] if len(args) > 1 else ''}\n")

    def _headers(self, status: int, ctype: str, length: int | None = None, cache=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()

    def _write(self, data: bytes):
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status: int, obj):
        body = json.dumps(obj, default=str).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self._write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Request too large.")
        raw = self.rfile.read(n) if n else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    def _user(self) -> str | None:
        """Who is asking, or None when the request must be refused."""
        cfg = self.server.cfg
        if cfg.auth == "proxy":
            user = (self.headers.get(cfg.user_header) or "").strip()
            return user[:200] or None
        if cfg.auth == "token":
            got = self.headers.get("X-DQL-Token") or ""
            return "local" if hmac.compare_digest(got, cfg.token) else None
        return "anonymous"

    def _host_ok(self) -> bool:
        """Defence against DNS rebinding and cross-site requests."""
        cfg = self.server.cfg
        host = (self.headers.get("Host") or "").lower()
        if cfg.auth == "token" and cfg.loopback:
            allowed = {f"127.0.0.1:{cfg.port}", f"localhost:{cfg.port}", f"[::1]:{cfg.port}"}
            if host not in allowed:
                return False
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc.lower() != host:
            return False
        return True

    def _session(self, sid: str, user: str) -> Session:
        if not SESSION_ID.match(sid or ""):
            raise ValueError("Missing or malformed session id.")
        return self.server.session(sid, user)

    # -- routing -----------------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            body = b"ok"
            self._headers(200, "text/plain; charset=utf-8", len(body))
            self._write(body)
            return
        if not self._host_ok():
            return self._json(403, {"error": "Host or Origin not allowed."})
        if path.startswith("/api/"):
            user = self._user()
            if user is None:
                return self._json(401, {"error": "Not signed in (missing or wrong token)."})
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            try:
                if path == "/api/config":
                    return self._json(200, self._config(self._session(query.get("session", ""), user)))
                if path == "/api/models":
                    return self._json(200, self._models(self._session(query.get("session", ""), user),
                                                        query.get("region", "")))
            except (ValueError, llm.ModelError) as e:
                return self._json(400, {"error": str(e)})
            return self._json(404, {"error": "Not found."})
        if self.server.cfg.auth == "proxy" and self._user() is None:
            return self._json(401, {"error": "Not signed in."})
        self._static(path)

    def do_HEAD(self):
        if urllib.parse.urlsplit(self.path).path.startswith("/api/"):
            return self._json(405, {"error": "Use GET or POST."})
        self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self._host_ok():
            return self._json(403, {"error": "Host or Origin not allowed."})
        # A custom header forces a CORS preflight, which this server never
        # answers, so a page on another site cannot post here.
        if self.headers.get("X-DQL-Client") != "1":
            return self._json(403, {"error": "Missing X-DQL-Client header."})
        user = self._user()
        if user is None:
            return self._json(401, {"error": "Not signed in (missing or wrong token)."})
        try:
            body = self._body()
            sess = self._session(str(body.get("session", "")), user)
            if path == "/api/chat":
                return self._chat(sess, body)
            if path == "/api/approve":
                slot = sess.pending.get(str(body.get("id", "")))
                if not slot:
                    return self._json(404, {"error": "That prompt is no longer waiting."})
                slot["run"] = bool(body.get("run"))
                slot["said"] = str(body.get("said") or "")[:2000]
                slot["event"].set()
                return self._json(200, {"ok": True})
            if path == "/api/cancel":
                sess.cancelled.set()
                sess.release_approvals()
                return self._json(200, {"ok": True})
            if path == "/api/reset":
                if sess.lock.locked():
                    return self._json(409, {"error": "Still answering; stop it first."})
                if sess.agent:
                    sess.agent.reset()
                return self._json(200, {"ok": True})
            if path == "/api/settings":
                if not self.server.cfg.allow_settings:
                    return self._json(403, {"error": "Settings are fixed on this server."})
                if sess.lock.locked():
                    return self._json(409, {"error": "Still answering; stop it first."})
                values = body.get("values") or {}
                if not isinstance(values, dict):
                    raise ValueError("values must be an object.")
                reset = sess.apply_settings(values)
                return self._json(200, {**self._config(sess), "reset": reset})
        except (ValueError, llm.ModelError) as e:
            return self._json(400, {"error": str(e)})
        return self._json(404, {"error": "Not found."})

    # -- endpoints ---------------------------------------------------------
    def _config(self, sess: Session) -> dict:
        error, name = None, ""
        try:
            name = sess.get_model().name
        except llm.ModelError as e:
            error = str(e)
        cls = llm.model_class()
        tenant = dt_fetch.DT_ENVIRONMENT_URL if self.server.can_run else ""
        return {"provider": llm.provider_name(),
                "provider_label": getattr(cls, "label", "") or llm.provider_name(),
                "model_name": name, "error": error,
                "tenant": urllib.parse.urlsplit(tenant).netloc if tenant else "",
                "can_run": self.server.can_run,
                "allow_settings": self.server.cfg.allow_settings,
                "auto_run": self.server.cfg.auto_run,
                "user": "" if self.server.cfg.auth == "token" else sess.user,
                "fields": sess.fields()}

    def _models(self, sess: Session, region: str) -> dict:
        provider = llm.provider_name()
        if provider == "bedrock":
            region = region or sess.model_settings.get("region") or \
                (sess.model.settings.get("region") if sess.model else "") or aws.default_region()
            if not llm.REGION_RE.match(region):
                raise ValueError(f"Not a region: {region!r}.")
            key = (provider, region)
        else:
            key = (provider, "")
        cached = self.server.option_cache.get(key)
        if cached and time.time() - cached[0] < 600:
            return {"options": cached[1]}
        if provider == "bedrock":
            try:
                client = aws.Bedrock("", region, need_model=False)
            except aws.BedrockError as e:
                raise llm.ModelError(str(e)) from None
            options = llm.bedrock_options(client)
        else:
            options = sess.get_model().model_options()
        self.server.option_cache[key] = (time.time(), options)
        return {"options": options}

    def _chat(self, sess: Session, body: dict):
        message = str(body.get("message") or "").strip()
        if not message:
            return self._json(400, {"error": "Empty message."})
        if len(message) > 8000:
            return self._json(400, {"error": "Message too long (8000 characters at most)."})
        if not sess.lock.acquire(blocking=False):
            return self._json(409, {"error": "Still answering the previous question."})
        stop = threading.Event()
        try:
            try:
                agent = sess.get_agent()
            except llm.ModelError as e:
                return self._json(400, {"error": str(e)})
            self._headers(200, "text/event-stream; charset=utf-8")
            writer = sess.writer = SSEWriter(self.wfile)
            sess.cancelled.clear()

            def heartbeat():
                # Keeps proxies and load balancers from closing a quiet stream
                # while the model thinks or a query runs.
                while not stop.wait(15):
                    if not writer.ping():
                        sess.cancelled.set()
                        sess.release_approvals()
                        return
            threading.Thread(target=heartbeat, daemon=True).start()

            agent.approve = "always" if body.get("auto") else "ask"
            if self.server.cfg.audit == "full":
                audit(self.server.cfg, event="question", user=sess.user, session=sess.id,
                      text=message)
            try:
                agent.ask(message)
                writer.send("done", {})
            except Cancelled:
                writer.send("cancelled", {})
            except llm.ModelError as e:
                writer.send("error", {"text": str(e)})
            except Exception as e:      # keep the stream well-formed; log the rest
                traceback.print_exc()
                writer.send("error", {"text": f"Internal error: {e.__class__.__name__}: {e}"})
        finally:
            stop.set()
            sess.writer = None
            sess.cancelled.clear()
            sess.lock.release()

    def _static(self, path: str):
        rel = "index.html" if path in ("/", "") else urllib.parse.unquote(path.lstrip("/"))
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents or not target.is_file():
            return self._json(404, {"error": "Not found."})
        ctype = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".html": "text/html; charset=utf-8", ".md": "text/markdown; charset=utf-8",
                 ".svg": "image/svg+xml"}.get(target.suffix) or \
            (mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        data = target.read_bytes()
        self._headers(200, ctype, len(data), cache=target.suffix != ".html")
        self._write(data)


def serve(host=None, port=None, auth=None, open_browser=True) -> int:
    cfg = Config(host, port, auth)
    server = ChatServer(cfg)
    where = f"http://{'127.0.0.1' if cfg.host in ('0.0.0.0', '::') else cfg.host}:{cfg.port}/"
    url = where + (f"?t={cfg.token}" if cfg.auth == "token" else "")
    print(f"DQL chat on {where}  (LLM_PROVIDER={llm.provider_name()}, "
          f"tenant {'connected' if server.can_run else 'not configured: queries are written, not run'})",
          file=sys.stderr)
    if cfg.auth == "token":
        print(f"Open: {url}", file=sys.stderr)
    elif cfg.auth == "none":
        print("WARNING: DQL_CHAT_AUTH=none; anyone who can reach this port can use the "
              "tenant token and the model.", file=sys.stderr)
    if not cfg.loopback and cfg.auth == "token":
        print("Note: listening beyond this machine; the token in the URL is the only lock.",
              file=sys.stderr)
    print("Ctrl-C to stop.", file=sys.stderr, flush=True)
    if open_browser and cfg.auth == "token":
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:   # noqa: BLE001 — a missing browser is not an error
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
