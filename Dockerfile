# DQL Knowledge Base — MCP server image.
#
# Build:  docker build -t dql-kb-mcp .
# Run:    docker run --rm -i dql-kb-mcp          # retrieval only (zero config)
#         docker run --rm -i \                   # + generation via Ollama
#           -e LLM_PROVIDER=ollama \
#           -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
#           -e OLLAMA_MODEL=qwen3.6:27b dql-kb-mcp
#
# The server speaks MCP over stdio, so `-i` (interactive stdin) is required.

FROM python:3.12-slim

# Keep the embedding model cache in a known, image-baked location and silence
# noisy HF download chatter on stdout (MCP stdio must stay clean).
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

# Install dependencies first for better layer caching. Install the CPU-only
# torch build explicitly so sentence-transformers doesn't pull the multi-GB
# CUDA wheels (cuts the image from ~9 GB to ~1.5 GB).
COPY requirements.txt requirements-mcp.txt ./
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements-mcp.txt

# Copy the application and knowledge base.
COPY dql_rag.py mcp_server.py ./
COPY docs/ ./docs/

# Build the vector DB AND warm the embedding-model cache at image-build time,
# so the container starts instantly and runs read-only with no network.
# (This step needs network to fetch the model — must run BEFORE going offline.)
RUN python dql_rag.py ingest

# From here on, never phone home: the model + vector DB are already baked in,
# so the running container is fully offline and starts fast.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Retrieval needs no secrets. To enable dql_generate, pass LLM_PROVIDER + creds
# at runtime (see header). Default provider is anthropic with no key => the
# server offers dql_search only.
ENTRYPOINT ["python", "mcp_server.py"]
