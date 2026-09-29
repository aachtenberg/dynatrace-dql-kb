# util

Tools that talk to your Dynatrace tenant but are not part of the knowledge base. They use only the Python standard library, read the same `.env` as `dt_fetch.py`, and run from the repo root.

| Tool | What it does | Guide |
|------|--------------|-------|
| `./util/dql_agent.sh` | A model (Bedrock by default) that writes DQL, runs it on your tenant, and answers from the records, in the terminal | [dql_agent.md](dql_agent.md) |
| `./util/dql_chat.sh` | The same agent as a browser chat that draws charts and graphs from its queries and keeps past chats to reopen; also a container for AWS | [dql_chat.md](dql_chat.md) |
| `./util/dt_trace_profiler.sh` | Ranks trace entry points and flags the ones that look like batch jobs | [dt_trace_profiler.md](dt_trace_profiler.md) |
| `./util/dt_incident.sh` | Resolves a name to an entity and writes an incident brief | [dt_incident.md](dt_incident.md) |

`find_python.sh` is shared by the wrappers: it picks the first Python 3.10+ that actually starts. The agent's code is the `dqlagent/` package; both front ends are thin layers over it.
