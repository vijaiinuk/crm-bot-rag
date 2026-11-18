#!/usr/bin/env bash
# Local infrastructure on Colima (S1.4.1). Usage: scripts/infra.sh up|down|reset|shell
set -euo pipefail
cd "$(dirname "$0")/.."

# Always Colima's Docker, never Docker Desktop by accident.
export DOCKER_CONTEXT=colima
COLIMA_ARGS=(--cpu 2 --memory 3 --disk 20)

# The compose plugin if it works, else Homebrew's standalone docker-compose.
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose not found: brew install docker-compose" >&2
  exit 1
fi

need_colima() {
  command -v colima >/dev/null || { echo "colima is not installed: brew install colima docker docker-compose" >&2; exit 1; }
  if ! colima status >/dev/null 2>&1; then
    echo "starting Colima (${COLIMA_ARGS[*]})..."
    colima start "${COLIMA_ARGS[@]}"
  fi
}

wait_healthy() {
  local id status
  id=$("${COMPOSE[@]}" ps -q postgres)
  for _ in $(seq 1 60); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo starting)
    [[ $status == healthy ]] && return 0
    sleep 1
  done
  echo "postgres did not become healthy; see: DOCKER_CONTEXT=colima ${COMPOSE[*]} logs postgres" >&2
  exit 1
}

case "${1:-}" in
  up)
    need_colima
    "${COMPOSE[@]}" up -d
    wait_healthy
    uv run alembic upgrade head
    echo
    echo "  Postgres  postgresql://chatbot@localhost:5432/chatbot  (tests: chatbot_test)"
    echo "  Phoenix   http://localhost:6006"
    echo
    echo "  'make down' stops the containers; 'colima stop' frees the VM's 3 GB."
    ;;
  down)
    colima status >/dev/null 2>&1 && "${COMPOSE[@]}" down || echo "Colima is not running; nothing to stop."
    ;;
  reset)
    read -r -p "Delete ALL local Postgres and Phoenix data? [y/N] " answer
    [[ $answer == y || $answer == Y ]] || { echo "kept"; exit 0; }
    need_colima
    "${COMPOSE[@]}" down -v
    echo "volumes deleted; 'make up' recreates them"
    ;;
  shell)
    need_colima
    "${COMPOSE[@]}" exec postgres psql -U chatbot -d chatbot
    ;;
  *)
    echo "usage: $0 up|down|reset|shell" >&2
    exit 2
    ;;
esac
