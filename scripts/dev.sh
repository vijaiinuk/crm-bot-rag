#!/usr/bin/env bash
# Start, stop and inspect the local dev servers.
#
#   scripts/dev.sh start   [api|widget|admin ...]   (default: all)
#   scripts/dev.sh stop    [api|widget|admin ...]
#   scripts/dev.sh restart [api|widget|admin ...]
#   scripts/dev.sh status
#   scripts/dev.sh logs    [api|widget|admin]        (follows; Ctrl-C to quit)
#
# Each server runs its Makefile target (`make run`, `make widget-dev`,
# `make admin-dev`) in its own process group, so stopping it also stops
# uvicorn's reloader and Vite's children. PIDs live in .local/run, logs in
# .local/logs. Written for macOS's bash 3.2.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.local/run"
LOG_DIR="$ROOT/.local/logs"
ALL="api widget admin"

# name -> port / make target / URL to open / URL that answers when ready
port_of()   { case "$1" in api) echo 8000 ;; widget) echo 5173 ;; admin) echo 5174 ;; esac; }
target_of() { case "$1" in api) echo run ;; widget) echo widget-dev ;; admin) echo admin-dev ;; esac; }
url_of()    { case "$1" in api) echo "http://localhost:8000/docs" ;; *) echo "http://localhost:$(port_of "$1")" ;; esac; }
probe_of()  { case "$1" in api) echo "http://localhost:8000/healthz" ;; *) echo "http://localhost:$(port_of "$1")" ;; esac; }

if [ -t 1 ]; then GREEN=$'\e[32m'; RED=$'\e[31m'; DIM=$'\e[2m'; OFF=$'\e[0m'; else GREEN=; RED=; DIM=; OFF=; fi

die() { echo "${RED}$*${OFF}" >&2; exit 1; }

check_names() {
  for n in "$@"; do
    case " $ALL " in *" $n "*) ;; *) die "unknown server '$n' (expected: $ALL)" ;; esac
  done
}

listener_pids() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u || true; }

managed_pgid() {
  local f="$RUN_DIR/$1.pid"
  [ -f "$f" ] || return 1
  local pgid; pgid="$(cat "$f")"
  if kill -0 -- "-$pgid" 2>/dev/null; then echo "$pgid"; else rm -f "$f"; return 1; fi
}

# A process belongs to this repo if its command line mentions the repo path.
# Only those are stopped when they weren't started by this script.
ours() { ps -o command= -p "$1" 2>/dev/null | grep -qF "$ROOT"; }

wait_port_free() {
  local port="$1" i
  for i in $(seq 1 50); do
    [ -z "$(listener_pids "$port")" ] && return 0
    sleep 0.2
  done
  return 1
}

ensure_prereqs() {
  case "$1" in
    api)
      [ -f "$ROOT/.local/keys/private.pem" ] || { echo "${DIM}no signing key yet: running make keys${OFF}"; make -C "$ROOT" -s keys; } ;;
    widget|admin)
      [ -d "$ROOT/$1/node_modules" ] || { echo "${DIM}installing $1 dependencies (npm ci)${OFF}"; (cd "$ROOT/$1" && npm ci --no-fund --no-audit >/dev/null); } ;;
  esac
}

start_one() {
  local name="$1" port target log pgid i
  port="$(port_of "$name")"; target="$(target_of "$name")"; log="$LOG_DIR/$name.log"

  if pgid="$(managed_pgid "$name")"; then
    echo "$name: already running (pgid $pgid) at $(url_of "$name")"
    return 0
  fi
  if [ -n "$(listener_pids "$port")" ]; then
    echo "${RED}$name: port $port is already in use${OFF} (pid $(listener_pids "$port" | tr '\n' ' ')). Run 'make stop' first."
    return 1
  fi

  ensure_prereqs "$name"
  mkdir -p "$RUN_DIR" "$LOG_DIR"
  echo "--- $(date '+%Y-%m-%d %H:%M:%S') make $target ---" >>"$log"
  # Job control on just for the launch: the server gets its own process group,
  # so stop can signal make, uvicorn's reloader and Vite's children together.
  set -m
  nohup make -C "$ROOT" "$target" >>"$log" 2>&1 </dev/null &
  echo $! >"$RUN_DIR/$name.pid"
  set +m

  printf "%s: starting on :%s " "$name" "$port"
  for i in $(seq 1 60); do
    if curl -sf -o /dev/null "$(probe_of "$name")"; then
      echo "${GREEN}up${OFF}  $(url_of "$name")"
      return 0
    fi
    if ! kill -0 "$(cat "$RUN_DIR/$name.pid")" 2>/dev/null; then
      echo "${RED}exited${OFF}; last log lines:"; tail -n 15 "$log" | sed 's/^/    /'
      rm -f "$RUN_DIR/$name.pid"; return 1
    fi
    printf "."; sleep 0.5
  done
  echo "${RED}not answering after 30s${OFF}; see $log"
  return 1
}

stop_one() {
  local name="$1" port pgid pid stopped=0
  port="$(port_of "$name")"

  if pgid="$(managed_pgid "$name")"; then
    kill -TERM -- "-$pgid" 2>/dev/null || true
    stopped=1
  fi
  # Also stop a server of this repo started some other way (e.g. `make run` in a terminal).
  for pid in $(listener_pids "$port"); do
    if ours "$pid"; then
      kill -TERM "$pid" 2>/dev/null || true
      stopped=1
    else
      echo "${RED}$name: port $port is held by pid $pid, which isn't from this repo; leaving it alone${OFF}"
    fi
  done

  if [ "$stopped" = 0 ]; then echo "$name: not running"; return 0; fi
  if ! wait_port_free "$port"; then
    [ -n "${pgid:-}" ] && kill -KILL -- "-$pgid" 2>/dev/null || true
    for pid in $(listener_pids "$port"); do ours "$pid" && kill -KILL "$pid" 2>/dev/null || true; done
    wait_port_free "$port" || { echo "${RED}$name: still listening on :$port${OFF}"; return 1; }
  fi
  rm -f "$RUN_DIR/$name.pid"
  echo "$name: stopped"
}

status_all() {
  local name port pgid pids state
  printf "%-8s %-6s %-29s %s\n" SERVER PORT URL STATE
  for name in $ALL; do
    port="$(port_of "$name")"; pids="$(listener_pids "$port" | tr '\n' ' ')"
    if pgid="$(managed_pgid "$name")"; then
      if curl -sf -o /dev/null "$(probe_of "$name")"; then state="${GREEN}up${OFF} (pgid $pgid)"; else state="${RED}starting or unhealthy${OFF} (pgid $pgid)"; fi
    elif [ -n "$pids" ]; then
      state="up, not started by this script (pid ${pids% })"
    else
      state="${DIM}stopped${OFF}"
    fi
    printf "%-8s %-6s %-29s %b\n" "$name" "$port" "$(url_of "$name")" "$state"
  done
}

cmd="${1:-status}"; shift || true
names="${*:-$ALL}"
check_names $names

case "$cmd" in
  start)
    rc=0; for n in $names; do start_one "$n" || rc=1; done
    [ "$rc" = 0 ] && echo "${DIM}logs: make logs · stop: make stop${OFF}"
    exit "$rc" ;;
  stop)
    rc=0; for n in $names; do stop_one "$n" || rc=1; done; exit "$rc" ;;
  restart)
    for n in $names; do stop_one "$n"; done
    rc=0; for n in $names; do start_one "$n" || rc=1; done; exit "$rc" ;;
  status)
    status_all ;;
  logs)
    mkdir -p "$LOG_DIR"; files=""
    for n in $names; do touch "$LOG_DIR/$n.log"; files="$files $LOG_DIR/$n.log"; done
    # shellcheck disable=SC2086
    exec tail -n 30 -F $files ;;
  *)
    die "usage: scripts/dev.sh start|stop|restart|status|logs [api widget admin]" ;;
esac
