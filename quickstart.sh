#!/usr/bin/env bash
# Quick start — point at Ollama on 192.168.0.150

export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://192.168.0.150:11434
export OLLAMA_MODEL=mistral-small3.2:24b

python dql_rag.py ingest
python dql_rag.py interactive
