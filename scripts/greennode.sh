#!/usr/bin/env bash
# Run the acb-delta stack on a GreenNode vServer (Self-contained Docker Compose).
# Reads connection details from environment variables or .env.greennode.
#
#   ./scripts/greennode.sh setup     install Docker and Docker Compose on a fresh vServer
#   ./scripts/greennode.sh deploy    upload the latest git commit (GREENNODE_REF), build and start, print URL
#   ./scripts/greennode.sh status    service health and container status on the vServer
#   ./scripts/greennode.sh login     print the URL and active model configuration
#   ./scripts/greennode.sh logs [service]
#   ./scripts/greennode.sh ssh       connect to the vServer via interactive SSH
#   ./scripts/greennode.sh check     verify LLM, embeddings, reranker, and agent connectivity
#   ./scripts/greennode.sh down      stop and remove containers, keep data
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Load local .env.greennode or .env if present
if [ -f .env.greennode ]; then
  # shellcheck disable=SC1091
  set -a && source .env.greennode && set +a
elif [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

HOST="${GREENNODE_HOST:-}"
USER="${GREENNODE_USER:-ubuntu}"
PORT="${GREENNODE_PORT:-234}"
SSH_KEY="${GREENNODE_SSH_KEY:-}"
REF="${GREENNODE_REF:-HEAD}"
REMOTE_DIR="${REMOTE_DIR:-/opt/acb-delta}"
COMPOSE_CMD="docker compose -f docker-compose.prod.yml"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

check_host() {
  [ -n "$HOST" ] || fail "No host configured: set GREENNODE_HOST (in env or .env.greennode)."
}

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -p "$PORT")
[ -n "$SSH_KEY" ] && SSH_OPTS+=(-i "$SSH_KEY")
[ -n "${CI:-}" ] && SSH_OPTS+=(-o BatchMode=yes)

remote() {
  check_host
  ssh "${SSH_OPTS[@]}" "${USER}@${HOST}" "$1"
}

remote_interactive() {
  check_host
  ssh -t "${SSH_OPTS[@]}" "${USER}@${HOST}" "$@"
}

cmd_setup() {
  info "Setting up Docker on GreenNode vServer $HOST ($USER)"
  remote "set -euo pipefail
    sudo apt-get update -y
    command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker \$USER || true
    sudo mkdir -p $REMOTE_DIR
    sudo chown -R \$USER:\$USER $REMOTE_DIR
    docker compose version || sudo apt-get install -y docker-compose-plugin
    echo 'Docker and environment setup complete.'"
}

upload() {
  local tmp
  info "Packaging $REF"
  git rev-parse --verify --quiet "$REF" >/dev/null 2>&1 || git fetch --quiet origin "${REF#origin/}" 2>/dev/null || true
  tmp="$(mktemp -d)"
  git archive "$REF" | tar -x -C "$tmp"
  mkdir -p "$tmp/deploy/greennode" && cp -R deploy/greennode "$tmp/deploy/" 2>/dev/null || true
  info "Uploading $REF @ $(git log -1 --format='%h %s' "$REF") to $HOST:$REMOTE_DIR"

  local tar_flags=()
  tar --version 2>/dev/null | grep -q bsdtar && tar_flags=(--no-mac-metadata)
  COPYFILE_DISABLE=1 tar ${tar_flags[@]+"${tar_flags[@]}"} -czf - -C "$tmp" . |
    remote "set -e
      sudo rm -rf $REMOTE_DIR.new; sudo mkdir -p $REMOTE_DIR.new
      sudo tar --warning=no-unknown-keyword --no-same-owner -xzf - -C $REMOTE_DIR.new
      sudo chmod 755 $REMOTE_DIR.new
      if sudo test -f $REMOTE_DIR/.env; then sudo cp -p $REMOTE_DIR/.env $REMOTE_DIR.new/.env; fi
      sudo rm -rf $REMOTE_DIR; sudo mv $REMOTE_DIR.new $REMOTE_DIR"
  rm -rf "$tmp"
}

cmd_deploy() {
  upload
  info "Building and starting containers on GreenNode vServer"
  remote "set -euo pipefail; cd $REMOTE_DIR
    until sudo docker info >/dev/null 2>&1; do echo 'waiting for Docker daemon...'; sleep 3; done

    # Initialize .env from template if missing
    if ! sudo test -f .env; then
      if sudo test -f deploy/greennode/.env.greennode.example; then
        sudo cp deploy/greennode/.env.greennode.example .env
      else
        sudo cp .env.example .env
      fi
      sudo sed -i 's/CHANGEME/'\"\$(openssl rand -hex 12)\"'/g' .env || true
    fi

    # Stop and remove existing containers and volumes before starting fresh
    # sudo $COMPOSE_CMD down -v || true

    # Build and start all services (frontend listens on 80/443; other services are internal)
    sudo $COMPOSE_CMD up -d --build --wait

    # Seed the illustrative demo evaluation runs so the dashboard is populated (insert when empty)
    sudo $COMPOSE_CMD exec -T api python -m app.evaluation.demo_seed || true
    sudo $COMPOSE_CMD ps"

  check_models
  cmd_login
}

check_models() {
  info "Checking models and agent connectivity on GreenNode vServer..."
  remote "set -euo pipefail; cd $REMOTE_DIR
    sudo $COMPOSE_CMD exec -T api python -c '
from app.ria import embeddings, llm, rerank
if llm.llm_model():
    llm.chat_json(\"Return the JSON object {\\\"ok\\\": true}.\", \"ping\")
    print(\"chat ok:\", llm.llm_model())
else:
    print(\"chat: rule-based fallback (LLM_MODEL is not set)\")
if rerank.rerank_model():
    rerank.rerank(\"ping\", [\"ping\"])
    print(\"rerank ok:\", rerank.rerank_model())
else:
    print(\"rerank: relevance gate fallback (RERANK_MODEL is not set)\")
if embeddings.embedding_version():
    dim = len(embeddings.embed([\"ping\"])[0])
    print(\"embedding ok:\", embeddings.embedding_version(), dim, \"dims\")
else:
    print(\"embedding: sparse retrieval fallback (EMBEDDING_BASE_URL is not set)\")'
    sudo $COMPOSE_CMD exec -T agent python -c '
import json, urllib.request
req = urllib.request.Request(\"http://localhost:8080/invoke\", json.dumps({\"vbpl_text\": \"Thông tư thử nghiệm.\"}).encode(), {\"Content-Type\": \"application/json\"})
urllib.request.urlopen(req, timeout=300)
print(\"agent ok\")'"
}

cmd_login() {
  echo
  info "Deployment details on $HOST:"
  printf '  HTTP URL:    http://%s\n' "$HOST"
  printf '  HTTPS URL:   https://%s\n' "$HOST"
  remote "cd $REMOTE_DIR && sudo grep -E '^(OPENAI_BASE_URL|LLM_MODEL|EMBEDDING_MODEL)=' .env" |
    sed -e 's|^OPENAI_BASE_URL=|  LLM URL:     |' -e 's|^LLM_MODEL=|  LLM Model:   |' \
      -e 's|^EMBEDDING_MODEL=|  Embedding:   |' || true
  echo
}

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }

case "${1:-}" in
  setup) cmd_setup ;;
  deploy) cmd_deploy ;;
  down) remote "cd $REMOTE_DIR && sudo $COMPOSE_CMD down" ;;
  status) remote "cd $REMOTE_DIR && sudo $COMPOSE_CMD ps -a --format 'table {{.Service}}\t{{.Status}}' && curl -sk https://localhost/api/health/ready || curl -s http://localhost/api/health/ready; echo" ;;
  login) cmd_login ;;
  logs) shift; remote "cd $REMOTE_DIR && sudo $COMPOSE_CMD logs --tail 100 $*" ;;
  ssh) remote_interactive "${@:2}" ;;
  check) check_models ;;
  -h | --help | help | "") usage ;;
  *) usage; fail "Unknown command: $1" ;;
esac
