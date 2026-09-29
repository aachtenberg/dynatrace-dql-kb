"""
dql_agent.py — Ask questions about your Dynatrace tenant in the terminal. A
model (Amazon Bedrock by default) searches this repo's DQL docs, writes a
query, runs it against the tenant, reads the error or the records, and answers.

Standard library only: no pip, no Docker, no MCP. The same agent drives the
browser chat (util/dql_chat.py); the code lives in util/dqlagent/.

Usage:
    ./util/dql_agent.sh                 # interactive
    ./util/dql_agent.sh "hosts with CPU above 90% in the last hour"
    ./util/dql_agent.sh --check         # test the model, tool use and the tenant
    ./util/dql_agent.sh --models claude # Bedrock: list model ids you can use
    ./util/dql_agent.sh --help

Setup, recipes and troubleshooting: util/dql_agent.md

Configuration (environment variables, or .env in the repo root):
    LLM_PROVIDER          unset or bedrock (default), ollama, vllm,
                          openai_compatible, openai, azure_openai, anthropic;
                          see util/dqlagent/llm.py for each one's variables
    BEDROCK_MODEL_ID      optional; the model or inference-profile id to use.
                          Unset: the Claude Sonnet 5 inference profile for
                          BEDROCK_REGION, looked up with ListInferenceProfiles
    BEDROCK_REGION        default AWS_REGION, then AWS_DEFAULT_REGION, then us-east-1
    AWS credentials       see util/dqlagent/aws.py for the order they are looked up
    DT_ENVIRONMENT_URL    as for dt_fetch.py; without it the agent writes DQL
    DT_API_TOKEN          but cannot run it
    DQL_AGENT_SCAN_LIMIT_GB   per-query Grail scan cap, default 50
    DQL_AGENT_MAX_TURNS       model calls per question, default 10
    DQL_AGENT_MAX_TOKENS      output tokens per model call (default per model)
"""

import argparse
import os
import sys

import dqlagent  # noqa: F401  (puts the repo root on sys.path)
from dqlagent import aws, llm
from dqlagent.aws import (AwsCredentials, Bedrock, BedrockError,  # noqa: F401
                          _aws_credentials, sigv4_headers, DEFAULT_MODEL_MATCH)
from dqlagent.core import (DOCS_DIR, Agent, DocIndex, NameIndex,  # noqa: F401
                           _error_summary, _say, lint_dql, run_dql_tool)
from dqlagent.llm import ModelError, make_model  # noqa: F401

import dt_fetch  # noqa: E402

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")
BEDROCK_REGION = aws.default_region()

HELP = """Commands:
  /new      start a new conversation
  /last     print the last query the model ran or proposed
  /auto     run queries without asking (toggle)
  /help     this list
  /exit     quit (Ctrl-D also works)"""

PING_TOOL = {"name": "ping", "description": "Confirms that tool calls work. Takes no input.",
             "schema": {"type": "object", "properties": {}, "required": []}}


def _tenant_configured() -> bool:
    return bool(dt_fetch.DT_ENVIRONMENT_URL and dt_fetch.DT_API_TOKEN)


def _max_tokens() -> int | None:
    raw = os.getenv("DQL_AGENT_MAX_TOKENS", "")
    return int(raw) if raw.isdigit() else None


def list_models(match: str = "") -> int:
    """Print the inference profiles and text models Bedrock offers in this
    region. Listed does not mean enabled for this account: --check proves that."""
    if llm.provider_name() != "bedrock":
        try:
            model = make_model()
            opts = model.model_options()
        except ModelError as e:
            _say(f"ERROR: {e}")
            return 2
        print(f"{model.label}: models the server offers")
        for o in opts:
            if match.lower() in o["label"].lower():
                print(f"   {o['label']}")
        return 0
    try:
        bedrock = Bedrock(BEDROCK_MODEL_ID, BEDROCK_REGION, need_model=False)
    except BedrockError as e:
        _say(f"ERROR: {e}")
        return 2
    match = match.lower()
    print(f"Bedrock in {BEDROCK_REGION}, credentials from {bedrock.auth_source}")
    print("* = BEDROCK_MODEL_ID. Pick an id from the first column. With "
          f"BEDROCK_MODEL_ID unset, the {DEFAULT_MODEL_MATCH} profile for the "
          "region is used.\n")
    ok = False

    try:
        profiles = bedrock.list_inference_profiles()
        ok = True
        rows = sorted(
            (p.get("inferenceProfileId", ""), p.get("inferenceProfileName", ""),
             p.get("status", ""))
            for p in profiles)
        rows = [r for r in rows if match in (r[0] + " " + r[1]).lower()]
        print(f"Inference profiles ({len(rows)}), the usual choice:")
        width = max((len(r[0]) for r in rows), default=0)
        for pid, name, status in rows:
            mark = "*" if pid == BEDROCK_MODEL_ID else " "
            extra = "" if status in ("", "ACTIVE") else f"  [{status}]"
            print(f" {mark} {pid:<{width}}  {name}{extra}")
    except BedrockError as e:
        print(f"Inference profiles: could not list.\n{e}")

    print()
    try:
        models = bedrock.list_foundation_models()
        ok = True
        rows = []
        for m in models:
            mid = m.get("modelId", "")
            label = f"{m.get('providerName', '')} {m.get('modelName', '')}".strip()
            if match not in (mid + " " + label).lower():
                continue
            types = m.get("inferenceTypesSupported") or []
            how = ("on-demand" if "ON_DEMAND" in types
                   else "profile only" if "INFERENCE_PROFILE" in types
                   else "provisioned only")
            life = (m.get("modelLifecycle") or {}).get("status", "")
            rows.append((mid, how, label + ("" if life in ("", "ACTIVE") else f"  [{life}]")))
        rows.sort()
        print(f"Foundation models with text output ({len(rows)}):")
        width = max((len(r[0]) for r in rows), default=0)
        for mid, how, label in rows:
            mark = "*" if mid == BEDROCK_MODEL_ID else " "
            print(f" {mark} {mid:<{width}}  {how:<16}  {label}")
        print("\n'profile only' models are called through the matching us./eu./apac. "
              "profile above.")
    except BedrockError as e:
        print(f"Foundation models: could not list.\n{e}")

    print("\nThe model must support tool use. Confirm one works with:\n"
          "  BEDROCK_MODEL_ID=<id> ./util/dql_agent.sh --check")
    return 0 if ok else 1


def _check_model(provider: str, main: str) -> bool:
    """Ask one provider for a reply and a tool call. Prints what happened."""
    try:
        model = make_model(provider)
        role = "default" if provider == main else "also set up"
        print(f"llm:     {model.label} ({role}, LLM_PROVIDER={provider})")
        for line in model.describe():
            print(line)
        if provider == "bedrock":
            how = "BEDROCK_MODEL_ID" if BEDROCK_MODEL_ID else "default, looked up"
            print(f"         ({how})")
        reply = model.chat("", [{"role": "user", "content": [
            {"type": "text", "text": "Reply with the word OK."}]}], [])
        print(f"         answered: {llm._text(reply['content']).strip()[:40]!r}")
        reply = model.chat("You are testing tool calls.", [{"role": "user", "content": [
            {"type": "text", "text": "Call the ping tool now."}]}], [PING_TOOL])
        if any(b.get("type") == "tool_call" and b.get("name") == "ping" for b in reply["content"]):
            print("         tool use: OK")
            return True
        print("         tool use: FAILED. The model answered without calling the "
              "tool; the agent needs a model that supports tool use.")
    except ModelError as e:
        print(f"llm:     {provider} FAILED\n{e}")
    return False


def check() -> int:
    ok = True
    index = DocIndex()
    names = NameIndex()
    print(f"docs:    {len(index.chunks)} sections, {len(names.entries)} metric keys "
          f"and fields, from {DOCS_DIR}")
    if "Auto-generated" not in (DOCS_DIR / "metric_keys.md").read_text(encoding="utf-8")[:500]:
        print("         metric_keys.md looks like the placeholder; run ./dt_fetch.sh all")

    # Every provider set up in .env, so a failing default does not hide one that
    # works. The exit code follows the default, the one the agent uses.
    main, *others = llm.configured_providers()
    works = [p for p in [main, *others] if _check_model(p, main)]
    if main not in works:
        ok = False
        if works:
            print(f"         {works[0]} works. To use it, add LLM_PROVIDER={works[0]} to .env.")

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
        description="Ask a model about your Dynatrace tenant. "
                    "It writes DQL, runs it, and answers from the result.")
    ap.add_argument("question", nargs="*", help="ask once and exit")
    ap.add_argument("--check", action="store_true",
                    help="test the tenant and each model set up in .env "
                         "(fails only if the default model or the tenant does)")
    ap.add_argument("--models", nargs="?", const="", metavar="FILTER",
                    help="list the models you can use, optionally only those matching FILTER")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="run queries without asking")
    ap.add_argument("--no-run", action="store_true",
                    help="write queries but never run them")
    args = ap.parse_args()

    if args.check:
        return check()
    if args.models is not None:
        return list_models(args.models)

    try:
        model = make_model()
    except ModelError as e:
        _say(f"ERROR: {e}")
        return 2
    can_run = _tenant_configured() and not args.no_run
    approve = "always" if args.yes else "ask"
    agent = Agent(model, DocIndex(), can_run, approve, max_tokens=_max_tokens())

    if args.question:
        if can_run and not args.yes and not sys.stdin.isatty():
            _say("stdin is not a terminal, so queries cannot be approved; "
                 "pass --yes to run them.")
        try:
            print(agent.ask(" ".join(args.question)))
        except ModelError as e:
            _say(f"ERROR: {e}")
            return 1
        return 0

    _say(f"DQL agent · {model.name} · "
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
        except ModelError as e:
            _say(f"ERROR: {e}")
        except KeyboardInterrupt:
            _say("\nInterrupted.")


if __name__ == "__main__":
    sys.exit(main())
