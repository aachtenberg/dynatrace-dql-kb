# DQL chat: the browser chat in a container. Standard library only, so there
# is no pip step and no model download; the image is python:3.12-slim plus
# this repo's text files.
#
# Build from the repo root with BuildKit, which reads
# util/dql_chat.Dockerfile.dockerignore instead of the root .dockerignore.
# The legacy builder reads the root one and fails on COPY dt_fetch.py.
#   docker buildx build --load -f util/dql_chat.Dockerfile -t dql-chat .
#
# Run on your machine (the log prints a link with the access token; the
# volume keeps chat history across restarts):
#   docker run --rm -p 8750:8750 --env-file .env -v dql-chat:/data dql-chat
#
# Behind a load balancer that signs users in (ALB + OIDC/Cognito):
#   -e DQL_CHAT_AUTH=proxy        see util/dql_chat.md, "Deploy on AWS"
#
# Run ./dt_fetch.sh all before building: the image carries docs/ as it is,
# including the tenant's metric keys and field names.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DQL_CHAT_HOST=0.0.0.0 \
    DQL_CHAT_PORT=8750 \
    DQL_CHAT_DB=/data/chats.db

WORKDIR /app
COPY dt_fetch.py ./
COPY docs/ ./docs/
COPY .github/agents/dql-expert.md ./.github/agents/dql-expert.md
COPY util/ ./util/

# Chat history (SQLite) is the only thing written at runtime, under /data.
# Mount a volume there to keep it across restarts (EFS on Fargate), or set
# DQL_CHAT_HISTORY=0 to keep chats in memory only. Run as nobody.
RUN mkdir -p /data && chown 65534:65534 /data && chmod 700 /data
VOLUME ["/data"]
USER 65534:65534
EXPOSE 8750
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('DQL_CHAT_PORT', '8750'), timeout=2)"]
CMD ["python", "util/dql_chat.py", "--no-browser"]
