# dql_agent runbook

`util/dql_agent.sh` puts a Bedrock model in a loop with your DQL docs and your Dynatrace tenant. It writes a query, runs it, reads Grail's error or the records, and answers. This page covers setting it up, checking it works, day-to-day use, recipes, and what to do when it fails.

Run every command from the repo root. This file sits outside `docs/` on purpose: `docs/` is the DQL reference the agent searches.

## 1. What you need

| Item | Who provides it | Check |
|------|-----------------|-------|
| Python 3.10 or newer | Already on the machine | `python --version` (Git Bash) or `python3 --version` |
| This repo | `git clone`, or a zip copied across | `ls util/dql_agent.sh` |
| A Dynatrace platform URL and token | You, in the tenant's Account Management | `./dt_fetch.sh test` |
| An AWS identity allowed to call Bedrock | Your AWS or platform team | `./util/dql_agent.sh --check` |
| A Bedrock model enabled in that account | Your AWS or platform team | `./util/dql_agent.sh --check` |

Nothing gets installed. The only outbound connections are to your tenant and to `bedrock-runtime.<region>.amazonaws.com`.

## 2. One-time setup

### 2.1 Dynatrace token

Create a platform token (`dt0s16…`) in the same environment as the URL, with these read scopes:

```
storage:metrics:read   storage:entities:read   storage:logs:read
storage:events:read    storage:bizevents:read  storage:spans:read
storage:buckets:read
```

The agent can only read what the token can read. If you leave out `storage:logs:read`, log questions come back as permission errors.

### 2.2 AWS access (for the AWS or platform team)

The default model is **Claude Sonnet 5**, called through its cross-region inference profile (an id starting with `us.`, `eu.`, `apac.` or `global.`). The identity needs `bedrock:InvokeModel` (Converse is authorised by that action) on the profile **and** on the foundation model in every region the profile routes to. The two list actions let the agent find the profile id itself and power `--models`; without them, set `BEDROCK_MODEL_ID` by hand.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:*:*:inference-profile/*anthropic.claude-sonnet-5*",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:ListInferenceProfiles", "bedrock:ListFoundationModels"],
      "Resource": "*"
    }
  ]
}
```

Change the model pattern if you use another model. If the account still uses Bedrock's **Model access** page, the model must also be enabled there. Anthropic models ask for a one-off use-case form.

### 2.3 `.env`

```bash
cp .env.example .env
```

Set these in `.env`:

```bash
DT_ENVIRONMENT_URL=https://<env-id>.apps.dynatrace.com
DT_API_TOKEN=dt0s16.XXXXXXXX
BEDROCK_REGION=us-east-1
# BEDROCK_MODEL_ID=     # optional; see below
# HTTPS_PROXY=http://proxy.company.com:8080
# SSL_CERT_FILE=/path/to/company-ca.pem
```

With `BEDROCK_MODEL_ID` unset, the agent asks Bedrock for the Claude Sonnet 5 inference profile that matches the region's geography (`us.` for `us-east-1`, `eu.` for `eu-west-1`), falling back to `global.`. To choose the model yourself:

```bash
./util/dql_agent.sh --models           # every inference profile and text model in the region
./util/dql_agent.sh --models sonnet    # only ids or names containing "sonnet"
```

Put an id from the first column in `BEDROCK_MODEL_ID`. "profile only" models are called through their `us.`/`eu.`/… profile, not the bare id. A model can be listed and still not be enabled for your account; `--check` is the proof.

### 2.4 AWS credentials

The agent takes the first of these it finds:

| Order | Source | Typical use |
|-------|--------|-------------|
| 1 | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | Keys pasted from the AWS access portal ("Command line access") |
| 2 | `~/.aws/credentials`, profile `AWS_PROFILE` or `default` | Long-lived keys, or keys written by a company login tool |
| 3 | `aws configure export-credentials` | AWS CLI with SSO or an assumed role; also AWS CloudShell |
| 4 | `AWS_BEARER_TOKEN_BEDROCK` | A Bedrock API key, if your account issues them |

Keys pasted from the portal expire, usually after 1–12 hours. Paste fresh ones when `--check` reports expired credentials.

### 2.5 Fill in your tenant's names

```bash
./dt_fetch.sh all
```

This writes `docs/metric_keys.md` and `docs/entity_schemas.md`. The agent's `find_names` tool checks every metric key and field against these two files, so skipping this step makes it refuse or guess on your tenant's names.

## 3. Check it works

```bash
./util/dql_agent.sh --check
```

A healthy run looks like this. The exit code is 0.

```
docs:    231 sections, 903 metric keys and fields, from .../docs
aws:     environment variables
model:   us.anthropic.claude-sonnet-5-… in us-east-1 (default, looked up)
         Converse answered: 'OK'
tenant:  https://<env-id>.apps.dynatrace.com
         query ran, 1 record(s)
```

Every line that fails prints the reason and a hint, and the exit code is 1. See [Troubleshooting](#6-troubleshooting).

## 4. Day-to-day use

```bash
./util/dql_agent.sh                       # interactive
./util/dql_agent.sh "question"            # ask once, print the answer, exit
```

In interactive mode:

| Command | Does |
|---------|------|
| `/new` | Start a new conversation. Use it when you change topic; old context costs tokens. |
| `/last` | Print the last query the model ran or proposed. Paste it into a Notebook or dashboard. |
| `/auto` | Stop asking before each query (toggle). |
| `/help`, `/exit` | |

Each tool call is printed as it happens. `run_dql` shows the query and asks `Run this query? [Y/n]`. Answer `n` to get the query without running it. After a query runs you see the record count and the bytes scanned.

Flags:

| Flag | Effect |
|------|--------|
| `--yes`, `-y` | Run queries without asking |
| `--no-run` | Write queries only; never touch the tenant |
| `--check` | Section 3 |
| `--models [FILTER]` | List the model ids you can use in the region (section 2.3) |

Environment:

| Variable | Default | Effect |
|----------|---------|--------|
| `DQL_AGENT_SCAN_LIMIT_GB` | `50` | Grail stops a query that would read more than this |
| `BEDROCK_ENDPOINT_URL` | `https://bedrock-runtime.<region>.amazonaws.com` | For a VPC endpoint |

## 5. Recipes

### Ask about the last hour

```
dql> which hosts had CPU above 90% in the last hour?
dql> top 10 services by failed requests in the last 2 hours
dql> which Kubernetes namespaces use the most container CPU right now?
```

Say the time range in the question. The model adds one if you don't, but yours is what you meant.

### Follow up without repeating yourself

The conversation keeps its context until you type `/new`:

```
dql> error logs in the last 30 minutes, grouped by host
dql> only the top 3 hosts
dql> now show the last 5 messages from the first one
```

### Review the query before it runs

Use `--no-run` when a reviewer wants to see the DQL first, or when the question could scan a lot:

```bash
./util/dql_agent.sh --no-run "all spans slower than 5s over the last 7 days, by service"
```

### Get a query for a Notebook or dashboard

```
dql> hosts with memory above 85% over the last 24 hours, as a timeseries
dql> /last
```

`/last` prints the exact query that ran, ready to paste.

### Explore a data source you don't know

```
dql> what fields do bizevents have here, and which look like an order id?
```

The model runs `describe bizevents` or samples a few records before it writes anything else.

### Script it (no prompts)

```bash
./util/dql_agent.sh --yes "count of ERROR logs per host in the last hour" > errors.txt
```

When stdin is not a terminal, queries are skipped unless you pass `--yes`, so a cron job without `--yes` never touches the tenant.

### Keep a big question cheap

```bash
DQL_AGENT_SCAN_LIMIT_GB=5 ./util/dql_agent.sh "error logs mentioning timeout, last 24h"
```

If the scan cap stops the query, the model gets Grail's error and narrows the time range or the filter.

### Sign in with AWS SSO

```bash
aws sso login --profile bedrock-dev
AWS_PROFILE=bedrock-dev ./util/dql_agent.sh --check
```

### Run it in AWS CloudShell

For when your desktop allows only a browser. CloudShell is already signed in, and the agent picks up its credentials through `aws configure export-credentials`.

```bash
python3 --version                      # needs 3.10+; if older: sudo dnf install -y python3.11
git clone https://github.com/aachtenberg/dynatrace-dql-kb.git   # or Actions > Upload file, then unzip
cd dynatrace-dql-kb
cp .env.example .env && vi .env        # DT_* and BEDROCK_* as in 2.3
./util/dql_agent.sh --check
```

CloudShell has to reach your tenant. A CloudShell that runs inside a VPC may not be able to.

### Use a different model

```bash
./util/dql_agent.sh --models nova                  # find the id
BEDROCK_MODEL_ID=<id from the list> ./util/dql_agent.sh --check
```

Any model that supports tool use in Converse works. Sonnet 5 is the default because this is a multi-step job in a niche language: search, check names, run, read Grail's error, fix. Stronger models get there in fewer rounds. A cheaper model such as Amazon Nova is worth trying when cost matters or when it is the model your AWS team has already approved; give it the same questions you asked Sonnet and compare the queries it ends up running (`/last`).

### Call it from your own app (Flask, a bot, a notebook)

```python
import sys
sys.path.insert(0, "/path/to/dynatrace-dql-kb/util")   # the repo root is found from there
import dql_agent as da

agent = da.Agent(da.Bedrock(da.BEDROCK_MODEL_ID, da.BEDROCK_REGION),
                 da.DocIndex(), can_run=True, approve="always")
answer = agent.ask("which hosts had CPU above 90% in the last hour?")
last_query = agent.last_query
```

Create one `Agent` per user conversation. `approve="ask"` reads from the terminal, so in a web app use `"always"` or `"never"` and put your own approval step in front of it. Tool activity is printed to stderr.

## 6. Troubleshooting

| You see | Cause | Fix |
|---------|-------|-----|
| `Python 3.10 or newer was not found` | Old Python, or only the Microsoft Store alias | Use the company Python; in Git Bash check `python --version` |
| `BEDROCK_MODEL_ID is not set, and the default model could not be looked up` | The identity may not call `ListInferenceProfiles` | Set `BEDROCK_MODEL_ID` to the id your AWS team gives you |
| `no claude-sonnet-5 inference profile is offered in <region>` | Sonnet 5 is not in that region | `--models`, then set `BEDROCK_MODEL_ID`, or change `BEDROCK_REGION` |
| `No AWS credentials found` | None of the sources in 2.4 | Set one; with SSO run `aws sso login` first |
| `Bedrock HTTP 403 … security token` | Expired or wrong credentials | Paste fresh keys or sign in again |
| `Bedrock HTTP 403 … not authorized … bedrock:InvokeModel` | IAM | Policy in 2.2, including the inference-profile ARN |
| `… is not available for this account` or `… access to the model …` | The model is not enabled for this AWS account (IAM is fine) | Ask the AWS team to enable it, or `--models` and set `BEDROCK_MODEL_ID` to one the account can use |
| `model: … (default, looked up)` although you set `BEDROCK_MODEL_ID` | It was set on its own line without `export`, so the script cannot see it | `export BEDROCK_MODEL_ID=…`, put it in `.env`, or write it on the same line: `BEDROCK_MODEL_ID=… ./util/dql_agent.sh` |
| `… on-demand throughput isn't supported …` | The model needs an inference profile | Use the `us.`/`eu.` id |
| `Bedrock HTTP 404` / `identifier is invalid` | Wrong id, or the model is not in that region | Check `BEDROCK_MODEL_ID` and `BEDROCK_REGION` |
| `Bedrock HTTP 429` | Throttled | Wait a minute; ask the AWS team about quotas |
| `Cannot reach https://bedrock-runtime…` | Proxy or firewall | Set `HTTPS_PROXY`; ask for `bedrock-runtime.<region>.amazonaws.com` to be allowed |
| `CERTIFICATE_VERIFY_FAILED` | TLS inspection | `SSL_CERT_FILE=/path/to/company-ca.pem` |
| `tenant: FAILED … 401/403` | Token wrong, or missing scopes | Section 2.1 |
| `tenant: FAILED … 404` | `live.dynatrace.com` URL | Use the `apps.dynatrace.com` host |
| The model says a metric or field "is not in the tenant's docs" | `docs/metric_keys.md` / `entity_schemas.md` are stale or from another tenant | `./dt_fetch.sh all` |
| `[answer cut off at the token limit]` | Very long answer | Ask for less (fewer rows, one host) |
| Every query is `skipped` | stdin is not a terminal and `--yes` was not passed | Add `--yes`, or run it in a terminal |

## 7. Operating notes

- **Data flow.** Your question, doc excerpts, and up to 50 records per query (each value cut to 300 characters) go to Bedrock in your AWS account. Nothing else leaves the machine. Check with your data owner before pointing it at tenants that hold personal data in logs.
- **Cost.** Two meters run: Bedrock tokens (usually several Converse calls per question, up to 10) and Grail bytes scanned (shown after each query, capped by `DQL_AGENT_SCAN_LIMIT_GB`).
- **Read-only.** DQL cannot change data in Grail. The token scopes above are all `read`.
- **Keep names fresh.** Re-run `./dt_fetch.sh all` when new metrics or log attributes arrive, for example after a new extension or OpenTelemetry source.
- **Improve answers.** Add your team's proven queries to `docs/` (as in `docs/dql_example_queries.md`). `search_docs` picks them up on the next start.
