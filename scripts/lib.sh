#!/bin/bash
# =============================================================================
# FinanceTracker — Shared shell helpers
# Sourced by run.sh, scripts/start.sh, scripts/stop.sh, scripts/health-check.sh.
# Not meant to be executed directly.
# =============================================================================

# Guard against double-sourcing (e.g. nested scripts) so function redefinition
# noise is avoided. `return` only works when sourced; `exit` covers direct runs.
if [ -n "${FT_LIB_SH_LOADED:-}" ]; then
    return 0 2>/dev/null || exit 0
fi
FT_LIB_SH_LOADED=1

# find_free_port <preferred-port...>
# Pick a free TCP port: try each preferred port in order, else let the OS assign
# a free ephemeral one. Never grabs a port another app is already listening on.
find_free_port() {
    python3 - "$@" <<'PY'
import socket, sys
for p in sys.argv[1:]:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", int(p))); s.close(); print(p); raise SystemExit(0)
    except OSError:
        s.close()
s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()
PY
}

# wait_for_url <url> [tries] [sleep_seconds]
# Poll <url> with curl up to <tries> times (default 40), sleeping
# <sleep_seconds> (default 0.5) between attempts. Returns 0 as soon as the URL
# responds, 1 if it never did. Pass tries=1 for a single non-waiting probe.
wait_for_url() {
    local url="$1"
    local tries="${2:-40}"
    local delay="${3:-0.5}"
    local i=1
    while [ "$i" -le "$tries" ]; do
        if curl -s "$url" > /dev/null 2>&1; then
            return 0
        fi
        [ "$i" -lt "$tries" ] && sleep "$delay"
        i=$((i + 1))
    done
    return 1
}

# _descendants_of <pid>
# Print every live descendant PID of <pid> (children, grandchildren, ...),
# discovered via `pgrep -P` recursion. Descendants only — never unrelated
# processes — so tree-stops stay within our own process family.
_descendants_of() {
    local parent="$1"
    local child
    for child in $(pgrep -P "$parent" 2>/dev/null); do
        echo "$child"
        _descendants_of "$child"
    done
}

# stop_by_pidfile <pidfile> [grace_seconds]
# Stop the exact process whose PID is recorded in <pidfile> AND its descendant
# tree: send SIGTERM to the recorded PID and every descendant (the recorded PID
# is often a wrapper — pnpm/uv — whose real server child would otherwise be
# orphaned still holding the port), wait up to [grace_seconds] (default 1),
# then SIGKILL any survivor. We NEVER kill by port or by process name — a bare
# name like "uvicorn" or a port like 8000/3000 could belong to another app; the
# recorded PID's own tree is the only thing we are entitled to stop.
# Returns 0 if a live process was stopped; 1 if the pidfile was absent or its
# process was already gone (a stale pidfile is still cleaned up).
stop_by_pidfile() {
    local pid_file="$1"
    local grace="${2:-1}"
    [ -f "$pid_file" ] || return 1
    local pid
    pid=$(cat "$pid_file" 2>/dev/null)
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        return 1
    fi
    # Snapshot descendants BEFORE killing the parent — once the parent dies,
    # orphans reparent to PID 1 and pgrep -P can no longer find them.
    local tree
    tree="$pid $(_descendants_of "$pid")"
    local p
    for p in $tree; do
        kill -TERM "$p" 2>/dev/null || true
    done
    local waited=0
    while [ "$waited" -lt "$grace" ]; do
        local alive=""
        for p in $tree; do
            kill -0 "$p" 2>/dev/null && alive=1
        done
        [ -z "$alive" ] && break
        sleep 1
        waited=$((waited + 1))
    done
    for p in $tree; do
        kill -KILL "$p" 2>/dev/null || true
    done
    rm -f "$pid_file"
    return 0
}
