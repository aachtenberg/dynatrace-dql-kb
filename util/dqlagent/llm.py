"""Chat-model adapters. The agent speaks one neutral format; each adapter
converts it to its provider's API and back, so the same agent runs on Amazon
Bedrock, an OpenAI-compatible server (vLLM, LiteLLM, Azure OpenAI, OpenAI),
Ollama, or the Anthropic API.

Neutral format
    message  {"role": "user" | "assistant", "content": [block, ...]}
    block    {"type": "text", "text": str}
             {"type": "tool_call", "id": str, "name": str, "input": dict}
                 (the Responses API adds "item_id", sent back with the call)
             {"type": "tool_result", "id": str, "name": str, "text": str, "is_error": bool}
             {"type": "raw", "provider": str, "data": ...}
                 provider-only content (reasoning or thinking blocks) that must
                 be sent back unchanged on the next call
    tool     {"name": str, "description": str, "schema": JSON schema}
    reply    {"content": [block, ...], "stop": "end" | "tool_use" | "max_tokens" | "refusal"}

Which provider is used comes from LLM_PROVIDER, with the same variable names
dql_rag.py reads, so one .env configures both:

    unset / bedrock     BEDROCK_MODEL_ID, BEDROCK_REGION, AWS credentials
    ollama              OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_NUM_CTX
    vllm                VLLM_BASE_URL, VLLM_MODEL, PRIVATE_API_KEY
    openai_compatible   PRIVATE_BASE_URL, PRIVATE_MODEL, PRIVATE_API_KEY
    openai              OPENAI_API_KEY, OPENAI_MODEL
    azure_openai        AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,
                        AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_VERSION
                        (openai and azure_openai use the Responses API;
                        OPENAI_API=chat switches to chat completions, and
                        OPENAI_API=responses makes vllm and openai_compatible
                        use it too)
    anthropic           ANTHROPIC_API_KEY, ANTHROPIC_MODEL (needs the
                        `anthropic` package; everything else is stdlib)
"""

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import aws


class ModelError(RuntimeError):
    pass


class Interrupted(Exception):
    """A model call cut off because the user pressed Stop."""


# Settings the browser may change. Anything else stays in the server's env.
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._:/@+-]{1,200}$")
REGION_RE = re.compile(r"^[a-z]{2}(-gov|-iso[a-z]?)?-[a-z]+-\d{1,2}$")
BEDROCK_REGIONS = ["us-east-1", "us-east-2", "us-west-2", "ca-central-1", "sa-east-1",
                   "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-central-2",
                   "eu-north-1", "eu-south-1", "ap-south-1", "ap-southeast-1",
                   "ap-southeast-2", "ap-northeast-1", "ap-northeast-2",
                   "us-gov-west-1"]


def _allowed_models() -> list[str]:
    """DQL_CHAT_ALLOWED_MODELS limits which ids a user may pick (comma list;
    a trailing * matches a prefix). Unset: any id."""
    raw = os.getenv("DQL_CHAT_ALLOWED_MODELS", "")
    return [m.strip() for m in raw.split(",") if m.strip()]


def model_allowed(model_id: str) -> bool:
    allowed = _allowed_models()
    if not allowed:
        return True
    return any(model_id == a or (a.endswith("*") and model_id.startswith(a[:-1]))
               for a in allowed)


def _http_json(url: str, body: dict | None, headers: dict, what: str,
               timeout: int = 300, method: str | None = None) -> dict:
    """POST (or GET) JSON with retries on 429/5xx. Errors become ModelError with
    the provider's own message."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"accept": "application/json", **headers}
    if data is not None:
        hdrs["content-type"] = "application/json"
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, headers=hdrs,
                                     method=method or ("POST" if data is not None else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 + 3 * attempt)
                continue
            raise _http_error(what, e) from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, ConnectionRefusedError) and attempt < 2:
                time.sleep(1.5)     # a gateway that briefly refuses, as Azure's can
                continue
            host = urllib.parse.urlsplit(url).netloc
            raise ModelError(f"Cannot reach {what} at {host}: {e.reason}.") from None
        except (http.client.HTTPException, OSError) as e:
            # Dropped connections and read timeouts are not URLError.
            if attempt < 2 and not isinstance(e, TimeoutError):
                time.sleep(1.5)
                continue
            raise ModelError(f"The connection to {what} failed: "
                             f"{e.__class__.__name__} {e}".rstrip()) from None
        except ValueError:
            raise ModelError(f"{what} returned something that is not JSON.") from None
    raise ModelError(f"{what} kept failing; try again in a minute.")


def _http_error(what: str, e: urllib.error.HTTPError) -> ModelError:
    """The provider's own message from an HTTP error body."""
    detail = e.read().decode("utf-8", errors="ignore")
    try:
        err = json.loads(detail)
        err = err.get("error", err) if isinstance(err, dict) else err
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err)
        detail = str(err)
    except ValueError:
        pass
    hint = " Check the API key." if e.code in (401, 403) else ""
    return ModelError(f"{what} HTTP {e.code}: {detail[:800]}{hint}")


def _http_stream(url: str, body: dict, what: str, cancel, timeout: int = 300):
    """POST JSON and yield the reply's JSON lines as they arrive. When `cancel`
    (a threading.Event) is set, stop reading and close the connection, which
    makes a server such as Ollama stop generating; raises Interrupted."""
    if cancel.is_set():
        raise Interrupted()
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"accept": "application/x-ndjson",
                                          "content-type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise _http_error(what, e) from None
    except urllib.error.URLError as e:
        raise ModelError(f"Cannot reach {what} at {urllib.parse.urlsplit(url).netloc}: {e.reason}.") from None
    except (http.client.HTTPException, OSError) as e:
        raise ModelError(f"The connection to {what} failed: {e.__class__.__name__} {e}".rstrip()) from None
    with resp:
        try:
            for line in resp:
                if cancel.is_set():
                    raise Interrupted()
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    raise ModelError(f"{what} returned something that is not JSON.") from None
        except (http.client.HTTPException, OSError) as e:
            raise ModelError(f"The connection to {what} failed: {e.__class__.__name__} {e}".rstrip()) from None
    if cancel.is_set():
        raise Interrupted()


def _text(blocks) -> str:
    return "\n".join(b["text"] for b in blocks if b.get("type") == "text" and b.get("text"))


class ChatModel:
    """Base class. Subclasses set `provider` and `label`, implement chat(),
    and describe their settings with settings_fields()."""

    provider = ""
    label = ""
    default_max_tokens = 4096
    supports_cancel = False     # chat() takes cancel= (a threading.Event) and stops early

    def __init__(self, settings: dict | None = None):
        self.settings = {f["key"]: f.get("default") for f in self.settings_fields()}
        self.settings.update({k: v for k, v in (settings or {}).items() if v not in (None, "")})

    # -- settings ----------------------------------------------------------
    @classmethod
    def settings_fields(cls) -> list[dict]:
        """Provider-specific settings the UI shows: key, label, type
        ('text' | 'select' | 'number'), default, options, min/max, help."""
        return []

    @classmethod
    def validate(cls, values: dict) -> dict:
        """Check browser-supplied settings; raise ModelError on anything off."""
        fields = {f["key"]: f for f in cls.settings_fields()}
        clean = {}
        for key, value in values.items():
            f = fields.get(key)
            if not f:
                raise ModelError(f"Unknown setting {key!r}.")
            if f["type"] == "number":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ModelError(f"{f['label']} must be a whole number.") from None
                if not f.get("min", value) <= value <= f.get("max", value):
                    raise ModelError(f"{f['label']} must be between {f['min']} and {f['max']}.")
            else:
                value = str(value).strip()
                pattern = f.get("pattern")
                if value and pattern and not re.match(pattern, value):
                    raise ModelError(f"{f['label']} is not valid: {value!r}.")
                if key == "model" and value and not model_allowed(value):
                    raise ModelError(f"{value} is not in DQL_CHAT_ALLOWED_MODELS.")
            clean[key] = value
        return clean

    # -- calls -------------------------------------------------------------
    @property
    def name(self) -> str:
        return f"{self.provider} · {self.settings.get('model', '')}"

    def describe(self) -> list[str]:
        return [self.name]

    def model_options(self) -> list[dict]:
        """[{value, label}] for the model picker. May raise ModelError."""
        return []

    def chat(self, system: str, messages: list, tools: list,
             max_tokens: int | None = None) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Amazon Bedrock (Converse)
# ---------------------------------------------------------------------------

class BedrockModel(ChatModel):
    provider = "bedrock"
    label = "Amazon Bedrock"

    def __init__(self, settings: dict | None = None, client: "aws.Bedrock | None" = None):
        super().__init__(settings)
        if client is not None:          # an existing aws.Bedrock (old Agent callers)
            self.client = client
            self.settings.update(model=client.model_id, region=client.region)
        else:
            self.client = aws.Bedrock(self.settings.get("model") or "",
                                      self.settings.get("region") or aws.default_region())
            self.settings["model"] = self.client.model_id
        self.default_max_tokens = 16000 if "anthropic." in self.client.model_id else 4096

    @classmethod
    def settings_fields(cls):
        return [
            {"key": "region", "label": "AWS region", "type": "select",
             "default": aws.default_region(), "options": BEDROCK_REGIONS,
             "free": True, "pattern": REGION_RE.pattern,
             "help": "Where Bedrock is called. The model list follows it."},
            {"key": "model", "label": "Model or inference profile", "type": "select",
             "default": os.getenv("BEDROCK_MODEL_ID", ""), "options": [], "free": True,
             "pattern": MODEL_ID_RE.pattern, "dynamic": True,
             "help": "Empty: the Claude Sonnet 5 profile for the region."},
        ]

    @property
    def name(self):
        return f"bedrock · {self.client.model_id} · {self.client.region}"

    def describe(self):
        return [f"model:   {self.client.model_id} in {self.client.region}",
                f"aws:     {self.client.auth_source}"]

    def model_options(self):
        return bedrock_options(self.client)


    def _status_ok(self) -> bool:
        # Converse accepts toolResult.status only for Anthropic and Amazon Nova models.
        return any(k in self.client.model_id for k in ("anthropic.", "amazon.nova"))

    def _to_converse(self, messages):
        out = []
        for m in messages:
            blocks = []
            for b in m["content"]:
                t = b.get("type")
                if t == "text" and b.get("text"):
                    blocks.append({"text": b["text"]})
                elif t == "tool_call":
                    blocks.append({"toolUse": {"toolUseId": b["id"], "name": b["name"],
                                               "input": b.get("input") or {}}})
                elif t == "tool_result":
                    r = {"toolUseId": b["id"], "content": [{"text": b.get("text") or "(empty)"}]}
                    if self._status_ok():
                        r["status"] = "error" if b.get("is_error") else "success"
                    blocks.append({"toolResult": r})
                elif t == "raw" and b.get("provider") == "bedrock":
                    blocks.append(b["data"])
            if blocks:
                out.append({"role": m["role"], "content": blocks})
        return out

    def chat(self, system, messages, tools, max_tokens=None):
        converse_tools = [{"toolSpec": {"name": t["name"], "description": t["description"],
                                        "inputSchema": {"json": t["schema"]}}} for t in tools]
        try:
            resp = self.client.converse(self._to_converse(messages), system, converse_tools,
                                        max_tokens or self.default_max_tokens)
        except aws.BedrockError as e:
            raise ModelError(str(e)) from None
        content = []
        for c in (resp.get("output", {}).get("message") or {}).get("content") or []:
            if "text" in c:
                content.append({"type": "text", "text": c["text"]})
            elif "toolUse" in c:
                u = c["toolUse"]
                content.append({"type": "tool_call", "id": u.get("toolUseId", ""),
                                "name": u.get("name", ""), "input": u.get("input") or {}})
            else:
                content.append({"type": "raw", "provider": "bedrock", "data": c})
        stop = {"tool_use": "tool_use", "max_tokens": "max_tokens",
                "guardrail_intervened": "refusal", "content_filtered": "refusal"
                }.get(resp.get("stopReason", ""), "end")
        return {"content": content, "stop": stop}


def bedrock_options(client: "aws.Bedrock") -> list[dict]:
    """Inference profiles, then on-demand foundation models, for the picker."""
    opts, errors = [], []
    try:
        for p in sorted(client.list_inference_profiles(),
                        key=lambda p: p.get("inferenceProfileId", "")):
            pid = p.get("inferenceProfileId", "")
            if p.get("status", "ACTIVE") == "ACTIVE" and model_allowed(pid):
                opts.append({"value": pid, "label": f"{pid} — {p.get('inferenceProfileName', '')}"})
    except aws.BedrockError as e:
        errors.append(str(e).splitlines()[0])
    try:
        for m in sorted(client.list_foundation_models(), key=lambda m: m.get("modelId", "")):
            mid = m.get("modelId", "")
            if "ON_DEMAND" in (m.get("inferenceTypesSupported") or []) and model_allowed(mid):
                opts.append({"value": mid, "label": f"{mid} — {m.get('providerName', '')} "
                                                    f"{m.get('modelName', '')}".rstrip()})
    except aws.BedrockError as e:
        errors.append(str(e).splitlines()[0])
    if not opts and errors:
        raise ModelError("; ".join(errors))
    return opts


# ---------------------------------------------------------------------------
# OpenAI-compatible: chat completions or the Responses API
# (vLLM, LiteLLM, Azure OpenAI, OpenAI, ...)
# ---------------------------------------------------------------------------

def _v1(url: str) -> str:
    base = url.rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


class OpenAICompatModel(ChatModel):
    provider = "openai_compatible"
    label = "OpenAI-compatible server"

    PRESETS = {
        "openai_compatible": lambda: dict(base=_v1(os.getenv("PRIVATE_BASE_URL", "")),
                                          key=os.getenv("PRIVATE_API_KEY", ""),
                                          model=os.getenv("PRIVATE_MODEL", "")),
        "vllm": lambda: dict(base=_v1(os.getenv("VLLM_BASE_URL", "http://localhost:8000")),
                             key=os.getenv("PRIVATE_API_KEY", ""),
                             model=os.getenv("VLLM_MODEL") or os.getenv("PRIVATE_MODEL", "")),
        "openai": lambda: dict(base="https://api.openai.com/v1",
                               key=os.getenv("OPENAI_API_KEY", ""),
                               model=os.getenv("OPENAI_MODEL", "gpt-4o")),
        "azure_openai": lambda: dict(base=os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
                                     key=os.getenv("AZURE_OPENAI_API_KEY", ""),
                                     model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")),
    }

    def __init__(self, settings=None, preset: str = "openai_compatible"):
        self.preset = preset
        self.conf = self.PRESETS[preset]()
        self.provider = preset
        self.label = {"vllm": "vLLM", "openai": "OpenAI", "azure_openai": "Azure OpenAI"
                      }.get(preset, "OpenAI-compatible server")
        super().__init__({"model": self.conf["model"], **(settings or {})})
        if not self.conf["base"] or (preset == "openai_compatible" and not self.settings.get("model")):
            raise ModelError("PRIVATE_BASE_URL and PRIVATE_MODEL are required for "
                             "LLM_PROVIDER=openai_compatible.")
        if preset in ("openai", "azure_openai") and not self.conf["key"]:
            raise ModelError(f"No API key for {self.label}.")
        self.api = (os.getenv("OPENAI_API") or "").strip().lower() or (
            "responses" if preset in ("openai", "azure_openai") else "chat")
        if self.api not in ("chat", "responses"):
            raise ModelError(f"OPENAI_API must be chat or responses, not {self.api!r}.")
        if self.api == "responses":
            self.default_max_tokens = 16000     # reasoning tokens count against it

    @classmethod
    def settings_fields(cls):
        return [{"key": "model", "label": "Model", "type": "select", "default": "",
                 "options": [], "free": True, "pattern": MODEL_ID_RE.pattern, "dynamic": True,
                 "help": "The model name the server serves (for Azure, the deployment)."}]

    def describe(self):
        return [f"model:   {self.settings['model']} at {self.conf['base']}",
                f"api:     {'Responses' if self.api == 'responses' else 'chat completions'}"]

    def _url(self, path: str) -> str:
        if self.preset == "azure_openai" and path == "/responses":
            return f"{self.conf['base']}/openai/v1/responses"      # v1: no api-version
        if self.preset == "azure_openai":
            version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
            dep = urllib.parse.quote(self.settings["model"], safe="")
            return f"{self.conf['base']}/openai/deployments/{dep}{path}?api-version={version}"
        return self.conf["base"] + path

    def _headers(self):
        if not self.conf["key"]:
            return {}
        if self.preset == "azure_openai":
            return {"api-key": self.conf["key"]}
        return {"authorization": f"Bearer {self.conf['key']}"}

    def model_options(self):
        if self.preset == "azure_openai":
            # Azure lists base models, not deployments; offer the one in .env.
            dep = self.conf["model"]
            return [{"value": dep, "label": dep, "detail": "deployment"}] if dep else []
        data = _http_json(self._url("/models"), None, self._headers(), self.label, timeout=20)
        ids = sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))
        return [{"value": i, "label": i} for i in ids if model_allowed(i)]

    def chat(self, system, messages, tools, max_tokens=None):
        if self.api == "responses":
            return self._responses(system, messages, tools, max_tokens)
        msgs = [{"role": "system", "content": system}] if system else []
        for m in messages:
            if m["role"] == "assistant":
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                         for b in m["content"] if b.get("type") == "tool_call"]
                msg = {"role": "assistant", "content": _text(m["content"]) or None}
                if calls:
                    msg["tool_calls"] = calls
                msgs.append(msg)
            else:
                for b in m["content"]:
                    if b.get("type") == "tool_result":
                        text = b.get("text") or ""
                        msgs.append({"role": "tool", "tool_call_id": b["id"],
                                     "content": ("ERROR: " + text) if b.get("is_error") else text})
                text = _text(m["content"])
                if text:
                    msgs.append({"role": "user", "content": text})
        body = {"model": self.settings["model"], "messages": msgs}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["schema"]}}
                for t in tools]
        token_key = "max_completion_tokens" if self.preset in ("openai", "azure_openai") else "max_tokens"
        body[token_key] = max_tokens or self.default_max_tokens
        data = _http_json(self._url("/chat/completions"), body, self._headers(), self.label)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = []
        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})
        for i, call in enumerate(msg.get("tool_calls") or []):
            fn = call.get("function") or {}
            args = fn.get("arguments") or "{}"
            try:
                parsed = json.loads(args) if isinstance(args, str) else dict(args)
            except ValueError:
                parsed = {"_invalid_arguments": str(args)[:500]}
            content.append({"type": "tool_call", "id": call.get("id") or f"call_{i}",
                            "name": fn.get("name", ""), "input": parsed})
        stop = {"tool_calls": "tool_use", "length": "max_tokens",
                "content_filter": "refusal"}.get(choice.get("finish_reason", ""), "end")
        return {"content": content, "stop": stop}

    def _responses(self, system, messages, tools, max_tokens):
        """POST /responses. Like Converse, the conversation is a list of typed
        items, and reasoning items go back unchanged. store=false keeps nothing
        on the provider's side; reasoning comes back encrypted instead."""
        items = []
        for m in messages:
            blocks = m["content"]
            calls = any(b.get("type") == "tool_call" for b in blocks)
            for b in blocks:
                t = b.get("type")
                if t == "text" and b.get("text"):
                    items.append({"role": m["role"], "content": b["text"]})
                elif t == "tool_call":
                    item = {"type": "function_call", "call_id": b["id"], "name": b["name"],
                            "arguments": json.dumps(b.get("input") or {})}
                    if b.get("item_id"):
                        item["id"] = b["item_id"]
                    items.append(item)
                elif t == "tool_result":
                    text = b.get("text") or "(empty)"
                    items.append({"type": "function_call_output", "call_id": b["id"],
                                  "output": ("ERROR: " + text) if b.get("is_error") else text})
                elif t == "raw" and b.get("provider") == self.provider and calls:
                    # Reasoning only matters until the tool calls it led to are answered.
                    items.append(b["data"])
        body = {"model": self.settings["model"], "input": items, "store": False,
                "max_output_tokens": max_tokens or self.default_max_tokens}
        if system:
            body["instructions"] = system
        if tools:
            body["tools"] = [{"type": "function", "name": t["name"], "description": t["description"],
                              "parameters": t["schema"]} for t in tools]
        if self.preset in ("openai", "azure_openai"):
            body["include"] = ["reasoning.encrypted_content"]
        data = _http_json(self._url("/responses"), body, self._headers(), self.label)
        content, refused = [], False
        for item in data.get("output") or []:
            t = item.get("type")
            if t == "message":
                for c in item.get("content") or []:
                    if c.get("type") == "output_text" and c.get("text"):
                        content.append({"type": "text", "text": c["text"]})
                    elif c.get("type") == "refusal":
                        refused = True
                        content.append({"type": "text", "text": c.get("refusal") or "(refused)"})
            elif t == "function_call":
                args = item.get("arguments") or "{}"
                try:
                    parsed = json.loads(args)
                except ValueError:
                    parsed = {"_invalid_arguments": str(args)[:500]}
                content.append({"type": "tool_call", "id": item.get("call_id") or item.get("id", ""),
                                "item_id": item.get("id", ""), "name": item.get("name", ""),
                                "input": parsed if isinstance(parsed, dict) else {"value": parsed}})
            elif t == "reasoning":
                content.append({"type": "raw", "provider": self.provider, "data": item})
        reason = (data.get("incomplete_details") or {}).get("reason", "")
        if refused or reason == "content_filter":
            stop = "refusal"
        elif reason == "max_output_tokens":
            stop = "max_tokens"
        elif any(b["type"] == "tool_call" for b in content):
            stop = "tool_use"
        else:
            stop = "end"
        return {"content": content, "stop": stop}


# ---------------------------------------------------------------------------
# Ollama (native /api/chat, so num_ctx is honored)
# ---------------------------------------------------------------------------

def ollama_base() -> str:
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def ollama_up(timeout: float = 1.5) -> bool:
    """Whether an Ollama server answers at OLLAMA_BASE_URL (for the chat's
    provider list; a quick GET, no model is loaded)."""
    try:
        with urllib.request.urlopen(ollama_base() + "/api/version", timeout=timeout) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


class OllamaModel(ChatModel):
    provider = "ollama"
    label = "Ollama"
    supports_cancel = True      # streams, so Stop frees the GPU at once

    def __init__(self, settings=None):
        self.base = ollama_base()
        super().__init__(settings)

    @classmethod
    def settings_fields(cls):
        return [
            {"key": "model", "label": "Model", "type": "select",
             "default": os.getenv("OLLAMA_MODEL", "qwen3:8b"), "options": [], "free": True,
             "pattern": MODEL_ID_RE.pattern, "dynamic": True,
             "help": "Installed models on the Ollama server."},
            {"key": "num_ctx", "label": "Context window (num_ctx)", "type": "number",
             "default": int(os.getenv("OLLAMA_NUM_CTX", "16384")), "min": 4096, "max": 262144,
             "help": "The agent's prompt is ~6k tokens before any results; below 16k it gets cut."},
        ]

    def describe(self):
        return [f"model:   {self.settings['model']} at {self.base} (num_ctx {self.settings['num_ctx']})"]

    def model_options(self):
        """Installed chat models. The agent needs tool calls, so a model whose
        capabilities lack "tools" is listed as disabled; embedding-only models
        are left out. Older servers without capabilities list everything."""
        data = _http_json(self.base + "/api/tags", None, {}, "Ollama", timeout=20)
        opts, cant = [], []
        for m in sorted(data.get("models", []), key=lambda m: m.get("name", "")):
            name = m.get("name", "")
            if not name or not model_allowed(name):
                continue
            try:
                info = _http_json(self.base + "/api/show", {"model": name}, {}, "Ollama", timeout=10)
            except ModelError:
                info = {}
            caps = info.get("capabilities")
            if caps is not None and "completion" not in caps:
                continue                                    # embedding models
            size = (m.get("details") or {}).get("parameter_size", "")
            ctx = next((v for k, v in (info.get("model_info") or {}).items()
                        if k.endswith(".context_length")), None)
            detail = " · ".join(x for x in (size, f"{ctx // 1024}k context" if ctx else "") if x)
            opt = {"value": name, "label": name, "detail": detail}
            if caps is not None and "tools" not in caps:
                opt.update(disabled=True, why="cannot call tools")
                cant.append(opt)
            else:
                opts.append(opt)
        return opts + cant

    def chat(self, system, messages, tools, max_tokens=None, cancel=None):
        msgs = [{"role": "system", "content": system}] if system else []
        for m in messages:
            if m["role"] == "assistant":
                msg = {"role": "assistant", "content": _text(m["content"])}
                calls = [{"function": {"name": b["name"], "arguments": b.get("input") or {}}}
                         for b in m["content"] if b.get("type") == "tool_call"]
                if calls:
                    msg["tool_calls"] = calls
                msgs.append(msg)
            else:
                for b in m["content"]:
                    if b.get("type") == "tool_result":
                        msgs.append({"role": "tool", "tool_name": b.get("name", ""),
                                     "content": ("ERROR: " if b.get("is_error") else "")
                                     + (b.get("text") or "")})
                text = _text(m["content"])
                if text:
                    msgs.append({"role": "user", "content": text})
        body = {"model": self.settings["model"], "messages": msgs, "stream": False,
                "think": False,
                "options": {"num_ctx": int(self.settings["num_ctx"]),
                            "num_predict": max_tokens or self.default_max_tokens}}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["schema"]}}
                for t in tools]
        if cancel is None:
            data = _http_json(self.base + "/api/chat", body, {}, "Ollama")
        else:
            # Streamed: the text and tool calls arrive in pieces; a stop
            # closes the connection and Ollama stops generating.
            text, calls, data = [], [], {}
            for chunk in _http_stream(self.base + "/api/chat", dict(body, stream=True), "Ollama", cancel):
                if chunk.get("error"):
                    raise ModelError(f"Ollama: {chunk['error']}")
                piece = chunk.get("message") or {}
                text.append(piece.get("content") or "")
                calls.extend(piece.get("tool_calls") or [])
                if chunk.get("done"):
                    data = chunk
                    break
            data = {"message": {"content": "".join(text), "tool_calls": calls},
                    "done_reason": data.get("done_reason")}
        msg = data.get("message") or {}
        content = []
        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})
        for i, call in enumerate(msg.get("tool_calls") or []):
            fn = call.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"_invalid_arguments": args[:500]}
            content.append({"type": "tool_call", "id": call.get("id") or f"call_{i}",
                            "name": fn.get("name", ""), "input": args})
        stop = "max_tokens" if data.get("done_reason") == "length" else (
            "tool_use" if any(b["type"] == "tool_call" for b in content) else "end")
        return {"content": content, "stop": stop}


# ---------------------------------------------------------------------------
# Anthropic API (official SDK; optional)
# ---------------------------------------------------------------------------

class AnthropicModel(ChatModel):
    provider = "anthropic"
    label = "Anthropic API"
    default_max_tokens = 16000

    def __init__(self, settings=None):
        super().__init__(settings)
        try:
            import anthropic
        except ImportError:
            raise ModelError("LLM_PROVIDER=anthropic needs the anthropic package "
                             "(pip install anthropic). On a desktop without pip, use "
                             "Bedrock instead.") from None
        self._sdk = anthropic
        self.client = anthropic.Anthropic()

    @classmethod
    def settings_fields(cls):
        return [{"key": "model", "label": "Model", "type": "select",
                 "default": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"), "options": [],
                 "free": True, "pattern": MODEL_ID_RE.pattern, "dynamic": True, "help": ""}]

    def model_options(self):
        try:
            ids = [m.id for m in self.client.models.list()]
        except self._sdk.APIError as e:
            raise ModelError(f"Anthropic API: {e}") from None
        return [{"value": i, "label": i} for i in ids if model_allowed(i)]

    @staticmethod
    def _block_dict(block) -> dict:
        for attr in ("to_dict", "model_dump"):
            fn = getattr(block, attr, None)
            if fn:
                return fn()
        return dict(block)

    def chat(self, system, messages, tools, max_tokens=None):
        msgs = []
        for m in messages:
            blocks = []
            for b in m["content"]:
                t = b.get("type")
                if t == "text" and b.get("text"):
                    blocks.append({"type": "text", "text": b["text"]})
                elif t == "tool_call":
                    blocks.append({"type": "tool_use", "id": b["id"], "name": b["name"],
                                   "input": b.get("input") or {}})
                elif t == "tool_result":
                    blocks.append({"type": "tool_result", "tool_use_id": b["id"],
                                   "content": b.get("text") or "", "is_error": bool(b.get("is_error"))})
                elif t == "raw" and b.get("provider") == "anthropic":
                    blocks.append(b["data"])    # thinking blocks go back unchanged
            if blocks:
                msgs.append({"role": m["role"], "content": blocks})
        kwargs = dict(model=self.settings["model"], max_tokens=max_tokens or self.default_max_tokens,
                      system=system, messages=msgs,
                      tools=[{"name": t["name"], "description": t["description"],
                              "input_schema": t["schema"]} for t in tools],
                      cache_control={"type": "ephemeral"})
        try:
            try:
                resp = self.client.messages.create(**kwargs)
            except TypeError:   # an SDK too old for top-level cache_control
                kwargs.pop("cache_control")
                resp = self.client.messages.create(**kwargs)
        except self._sdk.RateLimitError as e:
            raise ModelError(f"Anthropic API rate limit: {e}") from None
        except self._sdk.APIStatusError as e:
            raise ModelError(f"Anthropic API HTTP {e.status_code}: {e.message}") from None
        except self._sdk.APIConnectionError as e:
            raise ModelError(f"Cannot reach the Anthropic API: {e}") from None
        content = []
        for block in resp.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({"type": "tool_call", "id": block.id, "name": block.name,
                                "input": dict(block.input or {})})
            else:
                content.append({"type": "raw", "provider": "anthropic",
                                "data": self._block_dict(block)})
        stop = {"tool_use": "tool_use", "max_tokens": "max_tokens",
                "refusal": "refusal"}.get(resp.stop_reason or "", "end")
        return {"content": content, "stop": stop}


# ---------------------------------------------------------------------------

PROVIDERS = {
    "bedrock": BedrockModel,
    "ollama": OllamaModel,
    "anthropic": AnthropicModel,
    "openai_compatible": OpenAICompatModel,
    "vllm": OpenAICompatModel,
    "openai": OpenAICompatModel,
    "azure_openai": OpenAICompatModel,
}


def provider_name() -> str:
    return (os.getenv("LLM_PROVIDER") or "bedrock").strip().lower()


def configured_providers() -> list[str]:
    """LLM_PROVIDER first, then every other provider whose settings are in the
    environment. Bedrock counts only when it is LLM_PROVIDER (credentials can
    come from anywhere), and Ollama only when it answers."""
    env = os.getenv
    found = [p for p, ready in [
        ("azure_openai", env("AZURE_OPENAI_ENDPOINT") and env("AZURE_OPENAI_API_KEY")),
        ("openai", env("OPENAI_API_KEY")),
        ("anthropic", env("ANTHROPIC_API_KEY")),
        ("vllm", env("VLLM_BASE_URL")),
        ("openai_compatible", env("PRIVATE_BASE_URL") and env("PRIVATE_MODEL")),
    ] if ready]
    main = provider_name()
    others = [p for p in found if p != main]
    if main != "ollama" and ollama_up():
        others.append("ollama")
    return [main] + others


# (label, short label) for pickers.
PROVIDER_LABELS = {
    "bedrock": ("Amazon Bedrock", "Bedrock"),
    "ollama": ("Ollama", "Ollama"),
    "anthropic": ("Anthropic API", "Anthropic"),
    "openai_compatible": ("OpenAI-compatible server", "Gateway"),
    "vllm": ("vLLM", "vLLM"),
    "openai": ("OpenAI", "OpenAI"),
    "azure_openai": ("Azure OpenAI", "Azure"),
}


def provider_label(provider: str) -> tuple[str, str]:
    if provider in PROVIDER_LABELS:
        label, short = PROVIDER_LABELS[provider]
        if provider == "ollama":
            host = urllib.parse.urlsplit(ollama_base()).hostname or ""
            label = "Ollama (this machine)" if host in ("localhost", "127.0.0.1", "::1") else f"Ollama ({host})"
        return label, short
    label = getattr(PROVIDERS.get(provider), "label", "") or provider
    return label, label


def model_class(provider: str | None = None):
    provider = provider or provider_name()
    if provider not in PROVIDERS:
        raise ModelError(f"Unknown LLM_PROVIDER {provider!r}. Use one of: "
                         + ", ".join(sorted(PROVIDERS)) + ".")
    return PROVIDERS[provider]


def make_model(provider: str | None = None, settings: dict | None = None) -> ChatModel:
    """The configured adapter. `settings` holds browser or CLI overrides that
    were already validated with model_class(provider).validate()."""
    provider = provider or provider_name()
    cls = model_class(provider)
    try:
        if cls is OpenAICompatModel:
            return cls(settings, preset=provider)
        return cls(settings)
    except aws.BedrockError as e:
        raise ModelError(str(e)) from None
