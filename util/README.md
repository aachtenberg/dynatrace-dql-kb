# util

Tools that talk to your Dynatrace tenant but are not part of the knowledge base. Both use only the Python standard library, read the same `.env` as `dt_fetch.py`, and run from the repo root.

| Tool | What it does | Guide |
|------|--------------|-------|
| `./util/dql_agent.sh` | A Bedrock model that writes DQL, runs it on your tenant, and answers from the records | [dql_agent.md](dql_agent.md) |
| `./util/dt_trace_profiler.sh` | Ranks trace entry points and flags the ones that look like batch jobs | [dt_trace_profiler.md](dt_trace_profiler.md) |

`find_python.sh` is shared by the wrappers: it picks the first Python 3.10+ that actually starts.
