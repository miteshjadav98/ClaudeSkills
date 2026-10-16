#!/usr/bin/env bash
# Builds a throwaway git repo with the seeded-bug change on a feature branch,
# so the reviewer sees a real diff. Usage: ./setup.sh [target-dir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$(mktemp -d)/review-drill}"
mkdir -p "$TARGET/app"
cd "$TARGET"
git init -q -b main
cp "$HERE/base/chat_api.py" app/chat_api.py
printf '# Chat service\nFastAPI chat API backed by an LLM. Sessions belong to a single user.\n' > README.md
git add . && git -c user.name=drill -c user.email=drill@example.com commit -qm "Chat endpoint"
git checkout -qb feat/rag-agent
cp "$HERE/change/chat_api.py" app/chat_api.py
git add . && git -c user.name=drill -c user.email=drill@example.com commit -qm \
  "Add RAG retrieval, tool-calling agent loop, conversation history, and session search"
echo "Drill repo ready: $TARGET (branch feat/rag-agent vs main)"
