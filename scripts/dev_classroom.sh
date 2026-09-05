#!/usr/bin/env bash
# Start the existing backend and teacher website together for a local demo.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
runtime_root="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies"
if ! command -v node >/dev/null && [[ -x "$runtime_root/node/bin/node" ]]; then
  export PATH="$runtime_root/node/bin:$PATH"
fi
if ! command -v pnpm >/dev/null && [[ -x "$runtime_root/bin/fallback/pnpm" ]]; then
  export PATH="$runtime_root/bin/fallback:$PATH"
fi
if ! command -v pnpm >/dev/null || ! command -v node >/dev/null; then
  echo 'Install Node.js 22.13 or newer and pnpm before starting the teacher website.' >&2
  exit 1
fi
if ! command -v python3.12 >/dev/null && [[ -x "$runtime_root/python/bin/python3" ]]; then
  export PYTHON_BIN="${PYTHON_BIN:-$runtime_root/python/bin/python3}"
fi
demo_address=127.0.0.1
bind_address=127.0.0.1
case "${1:-}" in
  --lan)
    demo_address="${DEMO_HOST:-}"
    if [[ -z "$demo_address" ]] && command -v ipconfig >/dev/null; then
      network_interface="$(route -n get default 2>/dev/null | awk '/interface:/ { print $2 }')"
      demo_address="$(ipconfig getifaddr "${network_interface:-en0}" 2>/dev/null || true)"
    fi
    if [[ -z "$demo_address" ]]; then
      echo 'Set DEMO_HOST to this computer’s Wi-Fi IP address, then run again with --lan.' >&2
      exit 1
    fi
    bind_address=0.0.0.0
    ;;
  '') ;;
  *) echo 'Usage: bash scripts/dev_classroom.sh [--lan]' >&2; exit 1 ;;
esac
backend_port="${BACKEND_PORT:-8000}"
teacher_port="${TEACHER_PORT:-3000}"
if [[ ! -d teacher_portal/node_modules ]]; then
  (cd teacher_portal && pnpm install --frozen-lockfile)
fi
backend_pid=''
teacher_pid=''
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$teacher_pid" ]] || kill "$teacher_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM
BACKEND_HOST="$bind_address" PUBLIC_BASE_URL="http://$demo_address:$backend_port" bash scripts/dev_backend.sh &
backend_pid=$!
(cd teacher_portal && BACKEND_URL="http://127.0.0.1:$backend_port" exec pnpm dev --hostname "$bind_address" --port "$teacher_port") &
teacher_pid=$!
echo "Starting teacher website: http://$demo_address:$teacher_port"
echo "iPad backend setting: http://$demo_address:$backend_port/"
echo 'Keep this window open. Press Control-C to stop both services.'
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$teacher_pid" 2>/dev/null; do sleep 1; done
echo 'A service stopped. Check the messages above.' >&2
exit 1
