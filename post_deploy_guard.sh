#!/usr/bin/env bash
# post_deploy_guard.sh (v2 - macOS/BSD awk safe + remote build)
set -euo pipefail

REQUIRED_HOST="0.0.0.0"
REQUIRED_PORT="8080"
FLY_FILES=("fly.api.toml" "fly.toml")

# Use remote builder to avoid local Docker requirement
DEPLOY_CMD_BASE=("fly" "deploy" "--remote-only")

have() { command -v "$1" >/dev/null 2>&1; }
log() { printf '%s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

find_fly_file() {
  for f in "${FLY_FILES[@]}"; do
    [ -f "$f" ] && { echo "$f"; return 0; }
  done
  return 1
}

listening_ok() {
  if have ss; then
    ss -lptn | grep -E "LISTEN.*(${REQUIRED_HOST}|\\[::\\]):${REQUIRED_PORT}" >/dev/null && return 0 || return 1
  elif have netstat; then
    netstat -lntp 2>/dev/null | grep -E "(${REQUIRED_HOST}|\\[::\\]):${REQUIRED_PORT}.*LISTEN" >/dev/null && return 0 || return 1
  else
    # Fallback: very rough /proc/net/tcp check (Linux only)
    [ -r /proc/net/tcp ] || return 1
    awk -v port_hex="$(printf '%04X' "$REQUIRED_PORT")" '
      NR>1 && $4=="0A" {
        split($2,a,":"); if (toupper(a[2])==port_hex) { print "hit"; exit 0 }
      }
    ' /proc/net/tcp >/dev/null 2>&1 && return 0 || return 1
  fi
}

ensure_internal_port_8080() {
  local file="$1"
  local tmp="${file}.tmp.$$"
  local orig_hash new_hash

  # Save original hash
  orig_hash="$(shasum "$file" | awk '{print $1}')"

  # 1) Ensure [http_service] exists and has internal_port = 8080
  if grep -qE '^\s*\[http_service\]\s*$' "$file"; then
    # If internal_port exists under [http_service], set to 8080; else insert it directly below the header
    awk -v ins="internal_port = '"${REQUIRED_PORT}"'" '
      BEGIN { inblk=0; had_key=0 }
      /^\s*\[http_service\]\s*$/ { print; inblk=1; had_key=0; next }
      /^\s*\[.*\]\s*$/ {
        if (inblk && !had_key) { print ins }
        inblk=0
        print
        next
      }
      {
        if (inblk && $0 ~ /^[[:space:]]*internal_port[[:space:]]*=/) {
          sub(/[0-9]+$/, "'"${REQUIRED_PORT}"'"); had_key=1; print; next
        }
        print
      }
      END {
        if (inblk && !had_key) print ins
      }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
  else
    { echo "[http_service]"; echo "internal_port = ${REQUIRED_PORT}"; echo; cat "$file"; } > "$tmp"
    mv "$tmp" "$file"
  fi

  # 2) Patch any internal_port occurrences to 8080 in legacy [[services]] blocks too (safe, targeted)
  awk '
    BEGIN { in_services=0 }
    /^\s*\[\[services\]\]\s*$/ { in_services=1; print; next }
    /^\s*\[.*\]\s*$/ { in_services=0; print; next }
    {
      if (in_services && $0 ~ /^[[:space:]]*internal_port[[:space:]]*=/) {
        sub(/=[[:space:]]*[0-9]+/, "= '"${REQUIRED_PORT}"'")
      }
      print
    }
  ' "$file" > "$tmp" && mv "$tmp" "$file"

  # 3) Ensure helpful flags in [http_service]
  for kv in "force_https = true" "auto_stop_machines = true" "auto_start_machines = true"; do
    key="${kv%% *}"
    awk -v line="$kv" '
      BEGIN { inblk=0; has=0 }
      /^\s*\[http_service\]\s*$/ { inblk=1; print; next }
      /^\s*\[.*\]\s*$/ {
        if (inblk && !has) print line
        inblk=0
        print
        next
      }
      {
        if (inblk && $0 ~ ("^\\s*" "'"$key"'" "\\b")) has=1
        print
      }
      END {
        if (inblk && !has) print line
      }
    ' "$file" > "$tmp" && mv "$tmp" "$file"
  done

  new_hash="$(shasum "$file" | awk '{print $1}')"
  if [ "$orig_hash" != "$new_hash" ]; then
    cp "$file" "${file}.bak.$(date +%Y%m%d%H%M%S)"
    echo "changed"
  else
    echo "unchanged"
  fi
}

start_uvicorn_fallback() {
  if ! have uvicorn; then
    log "uvicorn not found; skipping fallback."
    return 0
  fi
  log "Starting fallback: uvicorn app.main:app --host ${REQUIRED_HOST} --port ${REQUIRED_PORT}"
  nohup uvicorn app.main:app --host "$REQUIRED_HOST" --port "$REQUIRED_PORT" >/dev/null 2>&1 || true
}

main() {
  local fly_file
  fly_file="$(find_fly_file || true)"
  if [ -n "${fly_file:-}" ]; then
    log "Using Fly config: ${fly_file}"
  else
    log "No fly.toml/fly.api.toml found — skipping config patch."
  fi

  local cfg_status="unchanged"
  if [ -n "${fly_file:-}" ]; then
    cfg_status="$(ensure_internal_port_8080 "$fly_file")"
    log "Config patch status: ${cfg_status}"
  fi

  if listening_ok; then
    log "✓ Listener detected on ${REQUIRED_HOST}:${REQUIRED_PORT}"
  else
    log "! No listener on ${REQUIRED_HOST}:${REQUIRED_PORT}"
    start_uvicorn_fallback
    sleep 2
  fi

  # Re-check
  if listening_ok; then
    log "✓ Listener healthy after check."
  else
    log "! Still no listener; proceeding based on config change state."
  fi

  # Compose remote deploy command (respect selected file if present)
  if [ -n "${fly_file:-}" ]; then
    DEPLOY_CMD=("${DEPLOY_CMD_BASE[@]}" "--config" "$fly_file")
  else
    DEPLOY_CMD=("${DEPLOY_CMD_BASE[@]}")
  fi

  if [ "${cfg_status}" = "changed" ] || ! listening_ok; then
    have fly || die "'fly' CLI not found in PATH"
    log "→ Triggering redeploy: ${DEPLOY_CMD[*]}"
    "${DEPLOY_CMD[@]}"
  else
    log "No redeploy needed."
  fi
}

main "$@"
