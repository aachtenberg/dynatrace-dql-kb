"""AWS credentials, SigV4 signing and the Bedrock client, without boto3.

Credentials are looked up in this order, like the AWS SDKs, and refreshed
before they expire:

1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN
2. Web identity: AWS_WEB_IDENTITY_TOKEN_FILE + AWS_ROLE_ARN (EKS IRSA)
3. ~/.aws/credentials, profile AWS_PROFILE or default, when it holds keys
4. The container credentials endpoint: AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
   or _FULL_URI (ECS and Fargate, EKS Pod Identity, AWS CloudShell)
5. `aws configure export-credentials`, when the AWS CLI is installed
   (SSO sign-ins, assumed roles, credential_process)
6. The EC2 instance metadata service (IMDSv2)

A Bedrock API key in AWS_BEARER_TOKEN_BEDROCK replaces SigV4 altogether.
"""

import configparser
import datetime
import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Used when no model id is given: the first active inference profile whose id
# contains this, preferring the one for the region's geography.
DEFAULT_MODEL_MATCH = "claude-sonnet-5"

# Metadata endpoints are link-local or loopback. A corporate HTTPS_PROXY must
# never see them, so they go through an opener with no proxy.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_CONTAINER_HOSTS = {"localhost", "127.0.0.1", "::1", "169.254.170.2",
                    "169.254.170.23", "fd00:ec2::23"}
_REFRESH_MARGIN = 300   # seconds before expiry that credentials are renewed


class BedrockError(RuntimeError):
    pass


def default_region() -> str:
    return (os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION") or "us-east-1")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

class AwsCredentials:
    def __init__(self, access_key, secret_key, token=None, source="", expires=None):
        self.access_key = access_key
        self.secret_key = secret_key
        self.token = token
        self.source = source
        self.expires = expires          # epoch seconds, None if static

    def fresh(self) -> bool:
        return self.expires is None or self.expires - time.time() > _REFRESH_MARGIN


def _epoch(value) -> float | None:
    """ISO 8601 ('2026-09-28T12:00:00Z', '...+00:00', fractions) to epoch seconds."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", text)
    if m:   # fromisoformat takes at most 6 fraction digits
        text = m.group(1) + (m.group(2) or "")[:7] + m.group(3)
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _from_env():
    key, secret = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")
    if key and secret:
        return AwsCredentials(key, secret, os.getenv("AWS_SESSION_TOKEN"),
                              "environment variables")
    return None


def _from_web_identity():
    token_file, role = os.getenv("AWS_WEB_IDENTITY_TOKEN_FILE"), os.getenv("AWS_ROLE_ARN")
    if not (token_file and role):
        return None
    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    endpoint = (os.getenv("AWS_ENDPOINT_URL_STS") or os.getenv("AWS_ENDPOINT_URL")
                or (f"https://sts.{region}.amazonaws.com" if region
                    else "https://sts.amazonaws.com"))
    body = urllib.parse.urlencode({
        "Action": "AssumeRoleWithWebIdentity", "Version": "2011-06-15",
        "RoleArn": role, "WebIdentityToken": token,
        "RoleSessionName": os.getenv("AWS_ROLE_SESSION_NAME") or f"dql-agent-{int(time.time())}",
    }).encode("utf-8")
    req = urllib.request.Request(endpoint.rstrip("/") + "/", data=body, method="POST",
                                 headers={"content-type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())
    except (urllib.error.URLError, ET.ParseError, OSError):
        return None
    found = {el.tag.split("}")[-1]: (el.text or "") for el in root.iter()}
    if not found.get("AccessKeyId"):
        return None
    return AwsCredentials(found["AccessKeyId"], found.get("SecretAccessKey", ""),
                          found.get("SessionToken"), f"web identity ({role})",
                          _epoch(found.get("Expiration")))


def _from_shared_file():
    profile = os.getenv("AWS_PROFILE", "default")
    cred_file = Path(os.getenv("AWS_SHARED_CREDENTIALS_FILE",
                               Path.home() / ".aws" / "credentials"))
    if not cred_file.exists():
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(cred_file, encoding="utf-8")
    except configparser.Error:
        return None
    if not parser.has_section(profile):
        return None
    sect = parser[profile]
    if sect.get("aws_access_key_id") and sect.get("aws_secret_access_key"):
        return AwsCredentials(sect["aws_access_key_id"], sect["aws_secret_access_key"],
                              sect.get("aws_session_token"), f"{cred_file} [{profile}]")
    return None


def _from_container():
    rel = os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    full = os.getenv("AWS_CONTAINER_CREDENTIALS_FULL_URI")
    if rel:
        url = "http://169.254.170.2" + rel
    elif full:
        url = full
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" and (parts.hostname or "") not in _CONTAINER_HOSTS:
            return None     # the SDKs refuse plain http to any other host
    else:
        return None
    headers = {}
    token_file = os.getenv("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE")
    if token_file:
        try:
            headers["Authorization"] = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return None
    elif os.getenv("AWS_CONTAINER_AUTHORIZATION_TOKEN"):
        headers["Authorization"] = os.environ["AWS_CONTAINER_AUTHORIZATION_TOKEN"]
    try:
        with _DIRECT.open(urllib.request.Request(url, headers=headers), timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None
    if not data.get("AccessKeyId"):
        return None
    return AwsCredentials(data["AccessKeyId"], data["SecretAccessKey"], data.get("Token"),
                          "container credentials endpoint", _epoch(data.get("Expiration")))


def _from_cli():
    aws = shutil.which("aws")
    if not aws:
        return None
    profile = os.getenv("AWS_PROFILE")
    cmd = [aws, "configure", "export-credentials", "--format", "process"]
    if profile:
        cmd += ["--profile", profile]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                             check=True).stdout
        data = json.loads(out)
        return AwsCredentials(data["AccessKeyId"], data["SecretAccessKey"],
                              data.get("SessionToken"),
                              f"aws configure export-credentials [{profile or 'default'}]",
                              _epoch(data.get("Expiration")))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        return None


def _from_imds():
    if os.getenv("AWS_EC2_METADATA_DISABLED", "").lower() == "true":
        return None
    base = os.getenv("AWS_EC2_METADATA_SERVICE_ENDPOINT", "http://169.254.169.254").rstrip("/")
    try:
        req = urllib.request.Request(base + "/latest/api/token", method="PUT",
                                     headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"})
        with _DIRECT.open(req, timeout=1) as resp:
            token = resp.read().decode("utf-8")
        hdr = {"X-aws-ec2-metadata-token": token}
        path = base + "/latest/meta-data/iam/security-credentials/"
        with _DIRECT.open(urllib.request.Request(path, headers=hdr), timeout=2) as resp:
            role = resp.read().decode("utf-8").split("\n")[0].strip()
        if not role:
            return None
        with _DIRECT.open(urllib.request.Request(path + role, headers=hdr), timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None
    if not data.get("AccessKeyId"):
        return None
    return AwsCredentials(data["AccessKeyId"], data["SecretAccessKey"], data.get("Token"),
                          f"EC2 instance metadata ({role})", _epoch(data.get("Expiration")))


_PROVIDERS = (_from_env, _from_web_identity, _from_shared_file, _from_container,
              _from_cli, _from_imds)


class CredentialChain:
    """The first source that answers wins. Its credentials are cached and
    looked up again shortly before they expire, so a long-running server keeps
    working past the lifetime of one set of temporary credentials."""

    def __init__(self, providers=_PROVIDERS):
        self._providers = providers
        self._creds: AwsCredentials | None = None
        self._lock = threading.Lock()

    def get(self) -> AwsCredentials:
        with self._lock:
            if self._creds is None or not self._creds.fresh():
                for provider in self._providers:
                    creds = provider()
                    if creds:
                        self._creds = creds
                        break
                else:
                    if self._creds is None or (self._creds.expires or 0) < time.time():
                        raise BedrockError(
                            "No AWS credentials found. Set AWS_ACCESS_KEY_ID and "
                            "AWS_SECRET_ACCESS_KEY (and AWS_SESSION_TOKEN), put keys in "
                            "~/.aws/credentials, sign in with `aws sso login` if the "
                            "AWS CLI is installed, or set AWS_BEARER_TOKEN_BEDROCK. In "
                            "AWS, give the task, pod or instance a role.")
            return self._creds

    @property
    def source(self) -> str:
        return self.get().source


_SHARED_CHAIN = CredentialChain()


def shared_chain() -> CredentialChain:
    return _SHARED_CHAIN


def _aws_credentials() -> AwsCredentials | None:
    """First credentials found, or None. Kept for callers of the old helper."""
    try:
        return CredentialChain().get()
    except BedrockError:
        return None


# ---------------------------------------------------------------------------
# SigV4
# ---------------------------------------------------------------------------

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
# Bedrock
# ---------------------------------------------------------------------------

def _bedrock_hint(code: int, detail: str, action: str = "bedrock:InvokeModel",
                  region: str = "") -> str:
    low = detail.lower()
    if code == 403 and "security token" in low:
        return "The credentials are expired or wrong. Refresh them and try again."
    if "not available for this account" in low or "access to the model" in low \
            or "model access" in low:
        return ("The model is not enabled for this AWS account; IAM is not the "
                "problem. Ask your AWS team to enable it, or pick one the account "
                "can use: ./util/dql_agent.sh --models, then set BEDROCK_MODEL_ID.")
    if code == 403 and action != "bedrock:InvokeModel":
        return (f"The identity is not allowed {action}. Ask your AWS team for the "
                "model id instead; listing is optional.")
    if code == 403:
        return ("The identity needs bedrock:InvokeModel on this model (and on the "
                "inference profile, if the id starts with us. or eu.).")
    if "on-demand throughput" in low or "inference profile" in low:
        return ("This model must be called through an inference profile. Try the "
                "id with a us. or eu. prefix.")
    if code == 404 or "identifier is invalid" in low:
        return f"Check BEDROCK_MODEL_ID and that the model exists in {region or default_region()}."
    if code == 429:
        return "Throttled. Wait a minute and ask again."
    return ""


class Bedrock:
    """Bedrock Runtime (Converse) and the two read-only calls on the Bedrock
    control plane that list models and inference profiles."""

    def __init__(self, model_id: str = "", region: str = "", need_model: bool = True,
                 chain: CredentialChain | None = None):
        self.model_id = model_id
        self.region = region or default_region()
        self.endpoint = os.getenv(
            "BEDROCK_ENDPOINT_URL", f"https://bedrock-runtime.{self.region}.amazonaws.com"
        ).rstrip("/")
        self.control_endpoint = os.getenv(
            "BEDROCK_CONTROL_ENDPOINT_URL", f"https://bedrock.{self.region}.amazonaws.com"
        ).rstrip("/")
        # A Bedrock API key, if the account issues them, replaces SigV4.
        self.api_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")
        self.chain = chain or shared_chain()
        if not self.api_key:
            self.chain.get()            # fail now, with the setup hint, not mid-chat
        if need_model and not self.model_id:
            self.model_id = self._default_model()

    @property
    def creds(self) -> AwsCredentials | None:
        return None if self.api_key else self.chain.get()

    @property
    def auth_source(self) -> str:
        return "AWS_BEARER_TOKEN_BEDROCK" if self.api_key else self.chain.source

    def _request(self, method: str, url: str, body: dict | None = None,
                 action: str = "bedrock:InvokeModel") -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else b""
        for attempt in range(3):
            headers = {"accept": "application/json"}
            if body is not None:
                headers["content-type"] = "application/json"
            if self.api_key:
                headers["authorization"] = f"Bearer {self.api_key}"
            else:
                headers.update(sigv4_headers(method, url, data, self.chain.get(),
                                             self.region, "bedrock"))
            req = urllib.request.Request(url, data=data if body is not None else None,
                                         method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="ignore")
                try:
                    detail = json.loads(detail).get("message", detail)
                except (ValueError, AttributeError):
                    pass
                if e.code in (429, 503) and attempt < 2:
                    time.sleep(2 + 4 * attempt)
                    continue
                hint = _bedrock_hint(e.code, str(detail), action, self.region)
                if "security token" in str(detail).lower():
                    hint += f" They came from {self.auth_source}."
                raise BedrockError(f"Bedrock HTTP {e.code}: {detail}\n{hint}") from None
            except urllib.error.URLError as e:
                host = urllib.parse.urlsplit(url).netloc
                raise BedrockError(
                    f"Cannot reach {host}: {e.reason}. Behind a proxy, set "
                    "HTTPS_PROXY. If TLS inspection breaks certificate checks, set "
                    "SSL_CERT_FILE to your company CA bundle."
                ) from None
            except (http.client.HTTPException, OSError) as e:
                # Dropped connections and read timeouts are not URLError.
                if attempt < 2 and not isinstance(e, TimeoutError):
                    time.sleep(2)
                    continue
                host = urllib.parse.urlsplit(url).netloc
                raise BedrockError(f"The connection to {host} failed: "
                                   f"{e.__class__.__name__} {e}".rstrip()) from None
        raise BedrockError("Bedrock kept failing; try again in a minute.")

    def _default_model(self) -> str:
        """The DEFAULT_MODEL_MATCH inference profile for this region's
        geography (us-east-1 -> us., eu-west-1 -> eu.), else a global. one,
        else any match."""
        try:
            profiles = self.list_inference_profiles()
        except BedrockError as e:
            if "security token" in str(e).lower():
                raise                   # bad credentials, not a missing model id
            raise BedrockError(
                "BEDROCK_MODEL_ID is not set, and the default model could not be "
                "looked up. Set BEDROCK_MODEL_ID to the model or inference-profile "
                f"id your AWS team enabled.\n{e}") from None
        ids = sorted(p.get("inferenceProfileId", "") for p in profiles
                     if DEFAULT_MODEL_MATCH in p.get("inferenceProfileId", "")
                     and p.get("status", "ACTIVE") == "ACTIVE")
        geo = {"us": "us.", "eu": "eu.", "ap": "apac.", "ca": "ca.",
               "sa": "sa.", "me": "me."}.get(self.region.split("-")[0], "")
        for prefix in (geo, "global.", ""):
            picks = [i for i in ids if prefix and i.startswith(prefix)] if prefix else ids
            if picks:
                return picks[0]
        raise BedrockError(
            f"BEDROCK_MODEL_ID is not set and no {DEFAULT_MODEL_MATCH} inference "
            f"profile is offered in {self.region}. Run ./util/dql_agent.sh --models "
            "and set BEDROCK_MODEL_ID to one of the ids.")

    def converse(self, messages, system=None, tools=None, max_tokens=4096):
        """Raw Converse call. `messages` and `tools` are in Converse's own format."""
        if not self.model_id:
            raise BedrockError("BEDROCK_MODEL_ID is not set.")
        body = {"messages": messages, "inferenceConfig": {"maxTokens": max_tokens}}
        if system:
            body["system"] = [{"text": system}]
        if tools:
            body["toolConfig"] = {"tools": tools}
        url = (f"{self.endpoint}/model/"
               f"{urllib.parse.quote(self.model_id, safe='')}/converse")
        return self._request("POST", url, body)

    def list_foundation_models(self) -> list[dict]:
        """ListFoundationModels, text-output models only."""
        url = f"{self.control_endpoint}/foundation-models?byOutputModality=TEXT"
        return self._request("GET", url, action="bedrock:ListFoundationModels"
                             ).get("modelSummaries", []) or []

    def list_inference_profiles(self) -> list[dict]:
        """ListInferenceProfiles, system-defined (cross-region) profiles."""
        out, token = [], None
        while True:
            query = {"maxResults": "1000", "typeEquals": "SYSTEM_DEFINED"}
            if token:
                query["nextToken"] = token
            url = (f"{self.control_endpoint}/inference-profiles?"
                   + urllib.parse.urlencode(query, quote_via=urllib.parse.quote))
            resp = self._request("GET", url, action="bedrock:ListInferenceProfiles")
            out.extend(resp.get("inferenceProfileSummaries", []) or [])
            token = resp.get("nextToken")
            if not token:
                return out
