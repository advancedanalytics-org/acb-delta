#!/usr/bin/env bash
# One entry point for running acb-delta locally. Wraps the plain docker compose
# commands documented in AGENTS.md; it never changes ports or deletes data unless asked.
#
#   ./scripts/run.sh up       first run creates .env, then builds and starts everything
#   ./scripts/run.sh down     stop (data kept)
#   ./scripts/run.sh status   service health + readiness
#   ./scripts/run.sh logs [service]
#   ./scripts/run.sh reset    stop and DELETE all data volumes (asks first)
#   ./scripts/run.sh test     lint + tests for backend, agent, frontend (no Docker needed)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Read a value from .env, falling back to a default.
env_value() {
  local value
  value="$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  echo "${value:-$2}"
}

require_docker() {
  command -v docker >/dev/null || fail "Docker is not installed. Install Docker Desktop first."
  docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop and retry."
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required (docker compose)."
}

# First run: copy .env.example and fill the CHANGEME passwords with random hex
# (hex only: passwords go into connection URLs unencoded).
ensure_env() {
  [ -f .env ] && return
  command -v openssl >/dev/null || fail "openssl is needed to generate passwords; or create .env from .env.example by hand."
  info "Creating .env from .env.example with generated passwords"
  local tmp
  tmp="$(mktemp)"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *=CHANGEME) echo "${line%=CHANGEME}=$(openssl rand -hex 16)" ;;
      *) echo "$line" ;;
    esac
  done < .env.example > "$tmp"
  mv "$tmp" .env
  chmod 600 .env
}

# Refuse to start when another program holds one of our ports, instead of silently picking another.
check_ports() {
  command -v lsof >/dev/null || return 0
  [ -n "$(docker compose ps -q 2>/dev/null)" ] && return 0 # our own stack already holds them
  local busy="" port
  for port in \
    "$(env_value FRONTEND_PORT 3000)" "$(env_value API_PORT 8000)" "$(env_value AGENT_PORT 8080)" \
    "$(env_value POSTGRES_PORT 5432)" "$(env_value MINIO_PORT 9000)" "$(env_value MINIO_CONSOLE_PORT 9001)" \
    "$(env_value FALKORDB_PORT 6379)"; do
    if lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
      busy="$busy $port"
    fi
  done
  [ -z "$busy" ] && return 0
  echo "Ports already in use:$busy" >&2
  for port in $busy; do lsof -iTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | tail -n +2 >&2; done
  fail "Stop the programs above, or change the *_PORT values in .env."
}

print_urls() {
  cat <<EOF

  UI              http://localhost:$(env_value FRONTEND_PORT 3000)
  API readiness   http://localhost:$(env_value API_PORT 8000)/api/health/ready
  Agent           http://localhost:$(env_value AGENT_PORT 8080)/health
  MinIO console   http://127.0.0.1:$(env_value MINIO_CONSOLE_PORT 9001)  (login: MINIO_ROOT_USER / MINIO_ROOT_PASSWORD in .env)

  Stop: ./scripts/run.sh down
EOF
}

cmd_up() {
  require_docker
  ensure_env
  grep -qE '=CHANGEME$' .env && fail ".env still has CHANGEME values; replace them first."
  check_ports
  info "Building and starting the stack (first run takes a few minutes)"
  docker compose up -d --build --wait
  cmd_status
  print_urls
}

cmd_status() {
  require_docker
  docker compose ps -a --format 'table {{.Service}}\t{{.Status}}'
  local url="http://localhost:$(env_value API_PORT 8000)/api/health/ready"
  echo
  if command -v curl >/dev/null; then
    printf 'Readiness: '
    curl -s --max-time 5 "$url" || printf 'API not reachable'
    echo
  fi
}

cmd_reset() {
  require_docker
  printf 'This deletes the Postgres and MinIO data volumes. Type "reset" to continue: '
  local answer
  read -r answer
  [ "$answer" = "reset" ] || fail "Cancelled."
  docker compose down -v
}

cmd_test() {
  command -v uv >/dev/null || fail "uv is required: https://docs.astral.sh/uv/"
  command -v npm >/dev/null || fail "Node.js 22+ and npm are required."
  local dir
  for dir in backend agent; do
    info "$dir: ruff + pytest"
    (cd "$dir" && uv run ruff check . && uv run ruff format --check . && uv run pytest -q)
  done
  info "frontend: lint + build"
  (cd frontend && npm ci --no-audit --no-fund && npm run lint && npm run build)
  info "All checks passed"
}

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
  up) cmd_up ;;
  down) require_docker; docker compose down ;;
  status) cmd_status ;;
  logs) require_docker; shift; docker compose logs -f "$@" ;;
  reset) cmd_reset ;;
  test) cmd_test ;;
  -h | --help | help | "") usage ;;
  *) usage; fail "Unknown command: $1" ;;
esac
