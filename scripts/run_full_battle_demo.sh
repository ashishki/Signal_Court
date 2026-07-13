#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PREFLIGHT_ONLY=0
case "${1:-}" in
  --preflight-only)
    PREFLIGHT_ONLY=1
    ;;
  -h|--help)
    echo "Usage: scripts/run_full_battle_demo.sh [--preflight-only]"
    exit 0
    ;;
  "")
    ;;
  *)
    echo "Unknown argument: $1" >&2
    echo "Usage: scripts/run_full_battle_demo.sh [--preflight-only]" >&2
    exit 2
    ;;
esac

PYTHON="${PYTHON:-${ROOT_DIR}/.venv/bin/python}"
export PATH="${ROOT_DIR}/.venv/bin:${PATH}"
RUNTIME_DIR="${SIGNAL_COUNT_BATTLE_RUNTIME_DIR:-${ROOT_DIR}/.runtime/full-battle}"
REE_REPO_DIR="${REE_REPO_DIR:-${ROOT_DIR}/.runtime/vendor/ree}"
LOG_DIR="${RUNTIME_DIR}/logs"
PIDS_FILE="${RUNTIME_DIR}/pids"
ENV_FILE="${RUNTIME_DIR}/full-battle.env"
SUMMARY_FILE="${RUNTIME_DIR}/summary.txt"
APP_PORT="${APP_PORT:-8004}"
APP_URL="http://127.0.0.1:${APP_PORT}"
MESH_DIR="${MESH_DIR:-${RUNTIME_DIR}/axl-mesh}"
INDEXER_CONFIRMATIONS="${INDEXER_CONFIRMATIONS:-0}"
FULL_BATTLE_JOB_TIMEOUT_SECONDS="${FULL_BATTLE_JOB_TIMEOUT_SECONDS:-1500}"

START_TS="$(date +%s)"

elapsed() {
  local now
  now="$(date +%s)"
  printf '%s' "$((now - START_TS))"
}

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'
  C_BOLD=$'\033[1m'
else
  C_RESET=""
  C_DIM=""
  C_CYAN=""
  C_GREEN=""
  C_YELLOW=""
  C_RED=""
  C_BOLD=""
fi

append_summary() {
  if (( PREFLIGHT_ONLY )); then
    return 0
  fi
  printf '[%s +%ss] %s\n' "$(date -Is)" "$(elapsed)" "$*" >>"${SUMMARY_FILE}"
}

print_line() {
  local color="$1"
  local label="$2"
  shift 2
  printf '%b[%s +%ss]%b %b%-7s%b %s\n' \
    "${C_DIM}" "$(date +%H:%M:%S)" "$(elapsed)" "${C_RESET}" \
    "${color}" "${label}" "${C_RESET}" "$*"
  append_summary "${label} $*"
}

log() {
  print_line "${C_CYAN}" "INFO" "$*"
}

ok() {
  print_line "${C_GREEN}" "OK" "$*"
}

warn() {
  print_line "${C_YELLOW}" "WARN" "$*"
}

fail() {
  print_line "${C_RED}" "FAIL" "$*"
}

section() {
  printf '\n%b== %s ==%b\n' "${C_BOLD}${C_CYAN}" "$*" "${C_RESET}"
  append_summary "== $* =="
}

banner() {
  printf '%b\n' "${C_BOLD}${C_CYAN}"
  printf '  Signal Count Full Battle Demo\n'
  printf '  AXL mesh -> specialist swarm -> verifier -> REE -> contribution receipts -> indexer\n'
  printf '%b\n\n' "${C_RESET}"
  append_summary "Signal Count Full Battle Demo"
}

start_bg() {
  local name="$1"
  shift
  log "Starting ${name}"
  nohup "$@" >"${LOG_DIR}/${name}.log" 2>&1 </dev/null &
  local pid="$!"
  echo "${pid}" >>"${PIDS_FILE}"
  ok "${name} started pid=${pid} log=${LOG_DIR}/${name}.log"
}

wait_http() {
  local url="$1"
  local name="$2"
  local deadline="$((SECONDS + ${3:-90}))"
  local started="${SECONDS}"
  local next_notice="$((SECONDS + 10))"
  log "Waiting for ${name} at ${url}"
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      fail "Timeout waiting for ${name}: ${url}"
      return 1
    fi
    if (( SECONDS >= next_notice )); then
      log "${name} still starting ($((SECONDS - started))s elapsed)"
      next_notice="$((SECONDS + 10))"
    fi
    sleep 2
  done
  ok "${name} ready after $((SECONDS - started))s"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

preflight_errors=0

preflight_error() {
  preflight_errors=$((preflight_errors + 1))
  fail "$*"
}

check_command() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "Command found: $1"
  else
    preflight_error "Missing required command: $1"
  fi
}

check_file_executable() {
  if [[ -x "$1" ]]; then
    ok "Executable found: $1"
  else
    preflight_error "Missing executable: $1"
  fi
}

check_env_value() {
  if [[ -n "${!1:-}" ]]; then
    ok "Environment configured: $1"
  else
    preflight_error "Missing environment value: $1"
  fi
}

check_docker_image() {
  if docker image inspect "$1" >/dev/null 2>&1; then
    ok "Docker image found: $1"
  else
    preflight_error "Missing Docker image: $1"
  fi
}

check_port_free() {
  local port="$1"
  local label="$2"
  local status
  if [[ ! -x "${PYTHON}" ]]; then
    warn "Skipping port check for ${label}; Python is not executable at ${PYTHON}"
    return 0
  fi
  set +e
  "${PYTHON}" - "${port}" <<'PY'
import socket
import sys

port = int(sys.argv[1])
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        raise SystemExit(0 if sock.connect_ex(("127.0.0.1", port)) != 0 else 1)
except PermissionError:
    raise SystemExit(2)
PY
  status=$?
  set -e
  case "${status}" in
    0)
      ok "Port free: ${label} ${port}"
      ;;
    1)
      preflight_error "Port already in use: ${label} ${port}"
      ;;
    2)
      warn "Skipping port check for ${label} ${port}; socket creation is not permitted"
      ;;
    *)
      preflight_error "Unable to check port: ${label} ${port}"
      ;;
  esac
}

run_preflight_only() {
  banner
  section "Preflight"

  check_command curl
  check_command docker
  check_command git
  check_command openssl
  check_file_executable "${PYTHON}"

  load_env_file "${ROOT_DIR}/.env"
  load_env_file "${ENV_FILE}"
  check_env_value GENSYN_RPC_URL
  if [[ -n "${DEPLOYER_PRIVATE_KEY:-}" || -n "${CHAIN_WRITER_PRIVATE_KEY:-}" ]]; then
    ok "Environment configured: DEPLOYER_PRIVATE_KEY or CHAIN_WRITER_PRIVATE_KEY"
  else
    preflight_error "Missing environment value: DEPLOYER_PRIVATE_KEY or CHAIN_WRITER_PRIVATE_KEY"
  fi

  if [[ -x "${REE_REPO_DIR}/ree.sh" ]]; then
    ok "Gensyn REE checkout ready: ${REE_REPO_DIR}"
  else
    preflight_error "Missing Gensyn REE checkout: ${REE_REPO_DIR}/ree.sh"
  fi

  if docker image inspect ree >/dev/null 2>&1 || docker image inspect gensynai/ree:v0.2.0 >/dev/null 2>&1; then
    ok "REE Docker image found: ree or gensynai/ree:v0.2.0"
  else
    preflight_error "Missing REE Docker image: ree or gensynai/ree:v0.2.0"
  fi
  check_docker_image gensyn-axl-local

  check_port_free "${APP_PORT}" "app"
  check_port_free 9022 "AXL node A"
  check_port_free 9024 "AXL node B"
  check_port_free 9014 "AXL MCP router"
  check_port_free 7161 "regime specialist"
  check_port_free 7162 "narrative specialist"
  check_port_free 7163 "risk specialist"

  if (( preflight_errors )); then
    fail "Preflight failed with ${preflight_errors} issue(s)"
    exit 1
  fi
  ok "Preflight passed"
  exit 0
}

load_env_file() {
  local file="$1"
  [[ -f "${file}" ]] || return 0
  set -a
  # shellcheck disable=SC1090
  source "${file}"
  set +a
}

if (( PREFLIGHT_ONLY )); then
  run_preflight_only
fi

mkdir -p "${RUNTIME_DIR}" "${LOG_DIR}" "${MESH_DIR}"

if [[ -f "${PIDS_FILE}" ]]; then
  while read -r pid; do
    [[ -z "${pid}" ]] && continue
    if kill -0 "${pid}" >/dev/null 2>&1; then
      echo "Runtime PID ${pid} is already alive. Run scripts/stop_full_battle_demo.sh first." >&2
      exit 1
    fi
  done <"${PIDS_FILE}"
fi

if [[ -s "${SUMMARY_FILE}" ]]; then
  cp "${SUMMARY_FILE}" "${SUMMARY_FILE}.$(date +%Y%m%d_%H%M%S).bak"
fi
: >"${SUMMARY_FILE}"
: >"${PIDS_FILE}"

banner
section "Preflight"

require_command curl
require_command docker
require_command git
require_command openssl
ok "Required commands present: curl docker git openssl"

ensure_official_ree_repo() {
  if [[ -x "${REE_REPO_DIR}/ree.sh" ]]; then
    ok "Gensyn REE checkout ready: ${REE_REPO_DIR}"
    return 0
  fi

  if [[ -e "${REE_REPO_DIR}" && ! -d "${REE_REPO_DIR}/.git" ]]; then
    echo "REE_REPO_DIR exists but is not a Gensyn REE checkout: ${REE_REPO_DIR}" >&2
    exit 1
  fi

  mkdir -p "$(dirname "${REE_REPO_DIR}")"
  log "Cloning official Gensyn REE checkout into ${REE_REPO_DIR}"
  git clone https://github.com/gensyn-ai/ree.git "${REE_REPO_DIR}"
  chmod +x "${REE_REPO_DIR}/ree.sh"
  ok "Gensyn REE checkout installed"
}

ensure_official_ree_repo
"${PYTHON}" -m mcp_routing.mcp_router --help >/dev/null
ok "Bundled MCP router import check passed"

load_env_file "${ROOT_DIR}/.env"
load_env_file "${ENV_FILE}"

if [[ -z "${GENSYN_RPC_URL:-}" || -z "${DEPLOYER_PRIVATE_KEY:-}" ]]; then
  echo "GENSYN_RPC_URL and DEPLOYER_PRIVATE_KEY must be present in .env or ${ENV_FILE}." >&2
  exit 1
fi
ok "Loaded testnet RPC and deployer configuration"

if [[ "${DEPLOYER_PRIVATE_KEY}" != 0x* ]]; then
  export DEPLOYER_PRIVATE_KEY="0x${DEPLOYER_PRIVATE_KEY}"
fi

if [[ ! -x "${PYTHON}" ]]; then
  echo "Python venv not found or not executable: ${PYTHON}" >&2
  exit 1
fi

if docker image inspect ree >/dev/null 2>&1; then
  ok "REE image found: ree"
elif docker image inspect gensynai/ree:v0.2.0 >/dev/null 2>&1; then
  log "Tagging existing gensynai/ree:v0.2.0 image as ree"
  docker tag gensynai/ree:v0.2.0 ree
  ok "REE image tag ready: ree"
else
  log "Pulling gensynai/ree:v0.2.0"
  docker pull gensynai/ree:v0.2.0
  docker tag gensynai/ree:v0.2.0 ree
  ok "REE image pulled and tagged: ree"
fi

if ! docker image inspect gensyn-axl-local >/dev/null 2>&1; then
  echo "Missing Docker image gensyn-axl-local. Build or restore it before the full battle run." >&2
  exit 1
fi
ok "AXL image found: gensyn-axl-local"

NODE_WALLET_ADDRESS="$("${PYTHON}" - <<'PY'
import os
from eth_account import Account

key = os.environ["DEPLOYER_PRIVATE_KEY"]
print(Account.from_key(key if key.startswith("0x") else "0x" + key).address)
PY
)"
export NODE_WALLET_ADDRESS

export MESH_DIR
export APP_PORT
export SIGNAL_COUNT_BATTLE_RUNTIME_DIR="${RUNTIME_DIR}"
export DATABASE_URL="sqlite:///${RUNTIME_DIR}/signal_count.db"
export SIGNAL_COUNT_OFFLINE_DEMO=0
export SIGNAL_COUNT_DEMO_LLM=1
export SIGNAL_COUNT_CHAIN_RECEIPTS=1
export SIGNAL_COUNT_REE_ENABLED=1
export GENSYN_SDK_COMMAND="${REE_REPO_DIR}/ree.sh"
export REE_CPU_ONLY=1
export SIGNAL_REPUTATION_VAULT_ADDRESS="0x0000000000000000000000000000000000000000"
export SIGNAL_COUNT_NATIVE_TEST_PAYOUTS=0
export FULL_BATTLE_JOB_TIMEOUT_SECONDS
export AXL_LOCAL_BASE_URL="http://127.0.0.1:9022"
export AXL_MCP_ROUTER_URL="http://127.0.0.1:9014"
export AXL_DISPATCH_TIMEOUT_SECONDS="${FULL_BATTLE_JOB_TIMEOUT_SECONDS}"
export MCP_ROUTER_FORWARD_TIMEOUT_SECONDS="${FULL_BATTLE_JOB_TIMEOUT_SECONDS}"
warn "Runtime reputation and payout transactions are unavailable: the normal AXL transport returns unsigned SpecialistResponse objects"

section "AXL Mesh"
log "Preparing persistent AXL mesh in ${MESH_DIR}"
MESH_DIR="${MESH_DIR}" scripts/prepare_axl_mesh_demo.sh >"${LOG_DIR}/prepare-axl-mesh.log" 2>&1
ok "AXL mesh config prepared"

start_bg axl-router scripts/run_axl_mesh_router.sh
start_bg axl-node-a env AXL_CONTAINER_NAME=signal-count-axl-node-a scripts/run_axl_mesh_node_a.sh
start_bg axl-node-b env AXL_CONTAINER_NAME=signal-count-axl-node-b scripts/run_axl_mesh_node_b.sh

wait_http "http://127.0.0.1:9022/topology" "AXL node A" 120
wait_http "http://127.0.0.1:9024/topology" "AXL node B" 120

curl -fsS "http://127.0.0.1:9024/topology" >"${RUNTIME_DIR}/node-b-topology.json"
AXL_REMOTE_PEER_ID="$("${PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

runtime = Path(os.environ["SIGNAL_COUNT_BATTLE_RUNTIME_DIR"])
payload = json.loads((runtime / "node-b-topology.json").read_text())
peer = payload.get("our_public_key") or payload.get("local_peer_id")
if not peer:
    tree = payload.get("tree") or []
    if tree and isinstance(tree[0], dict):
        peer = tree[0].get("public_key")
if not peer:
    raise SystemExit("Could not resolve AXL remote peer id from node-b topology")
print(peer)
PY
)"
export AXL_REMOTE_PEER_ID
export REGIME_PEER_ID="${AXL_REMOTE_PEER_ID}"
export NARRATIVE_PEER_ID="${AXL_REMOTE_PEER_ID}"
export RISK_PEER_ID="${AXL_REMOTE_PEER_ID}"
ok "AXL remote peer resolved: ${AXL_REMOTE_PEER_ID}"

section "Specialist Services"
start_bg specialist-regime env NODE_PUBLIC_URL=http://127.0.0.1:7161 scripts/run_axl_mesh_specialist.sh regime 7161
start_bg specialist-narrative env NODE_PUBLIC_URL=http://127.0.0.1:7162 scripts/run_axl_mesh_specialist.sh narrative 7162
start_bg specialist-risk env NODE_PUBLIC_URL=http://127.0.0.1:7163 scripts/run_axl_mesh_specialist.sh risk 7163

wait_http "http://127.0.0.1:7161/health" "regime specialist" 90
wait_http "http://127.0.0.1:7162/health" "narrative specialist" 90
wait_http "http://127.0.0.1:7163/health" "risk specialist" 90
wait_http "http://127.0.0.1:9014/services" "AXL MCP router services" 90

section "Signal Count App"
start_bg app scripts/run_app_mesh_live.sh
wait_http "${APP_URL}/health" "Signal Count app" 90

section "Live Job"
log "Submitting live job through AXL, REE, and task/contribution chain receipts"
SUBMIT_LOG="${LOG_DIR}/job-submit.log"
"${PYTHON}" - <<'PY' >"${SUBMIT_LOG}" 2>&1 &
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

runtime = Path(os.environ["SIGNAL_COUNT_BATTLE_RUNTIME_DIR"]) if os.environ.get("SIGNAL_COUNT_BATTLE_RUNTIME_DIR") else Path(".runtime/full-battle")
app_url = f"http://127.0.0.1:{os.environ.get('APP_PORT', '8004')}"
payload = {
    "thesis": "ETH can rally on improving ETF flows, stable liquidity, and stronger on-chain activity.",
    "asset": "ETH",
    "horizon_days": 30,
}
request = Request(
    f"{app_url}/jobs",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
started = time.time()
with urlopen(request, timeout=float(os.environ.get("FULL_BATTLE_JOB_TIMEOUT_SECONDS", "1500"))) as response:  # noqa: S310
    created = json.loads(response.read().decode("utf-8"))
job_id = created["job_id"]
with urlopen(f"{app_url}/jobs/{job_id}", timeout=60) as response:  # noqa: S310
    job = json.loads(response.read().decode("utf-8"))
with urlopen(app_url, timeout=60) as response:  # noqa: S310
    html = response.read().decode("utf-8")
runtime.mkdir(parents=True, exist_ok=True)
(runtime / "created-job.json").write_text(json.dumps(created, indent=2), encoding="utf-8")
(runtime / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
(runtime / "index.html").write_text(html, encoding="utf-8")
(runtime / "job-submit-seconds.txt").write_text(f"{time.time() - started:.3f}\n", encoding="utf-8")
print(job_id)
PY
SUBMIT_PID="$!"
while kill -0 "${SUBMIT_PID}" >/dev/null 2>&1; do
  sleep 30
  if kill -0 "${SUBMIT_PID}" >/dev/null 2>&1; then
    log "Live job still running: waiting on AXL dispatch, REE, or chain receipts"
  fi
done
if ! wait "${SUBMIT_PID}"; then
  fail "Live job failed. Last submit log lines:"
  tail -n 80 "${SUBMIT_LOG}" >&2 || true
  exit 1
fi

JOB_ID="$(cat "${RUNTIME_DIR}/created-job.json" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
ok "Job completed: ${JOB_ID}"

section "Indexer"
log "Running one-shot chain event indexer"
"${PYTHON}" - <<'PY' >"${LOG_DIR}/indexer-once.log" 2>&1
import asyncio
import json
import os
from pathlib import Path

from app.chain.broadcaster import JsonRpcTransport
from app.chain.config import ChainConfig
from app.config.settings import Settings
from app.indexer.chain_events import ChainEventPoller
from app.indexer.scheduler import ChainIndexerScheduler
from app.store import JobStore

runtime = Path(os.environ.get("SIGNAL_COUNT_BATTLE_RUNTIME_DIR") or ".runtime/full-battle")
job = json.loads((runtime / "job.json").read_text())
receipts = job.get("run_metadata", {}).get("chain_receipts", [])
transport = JsonRpcTransport(os.environ["GENSYN_RPC_URL"])
blocks = []
for receipt in receipts:
    tx_hash = receipt.get("tx_hash")
    if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
        continue
    tx_receipt = transport.call("eth_getTransactionReceipt", [tx_hash])
    if isinstance(tx_receipt, dict) and isinstance(tx_receipt.get("blockNumber"), str):
        blocks.append(int(tx_receipt["blockNumber"], 16))

if not blocks:
    raise SystemExit("No transaction blocks available for indexing")

settings = Settings()
config = ChainConfig.from_settings(settings)
addresses = [
    config.task_registry_address,
    config.receipt_registry_address,
]
if config.reputation_vault_address != "0x0000000000000000000000000000000000000000":
    addresses.append(config.reputation_vault_address)

async def main() -> None:
    store = JobStore()
    poller = ChainEventPoller(transport=transport, contract_addresses=addresses)
    scheduler = ChainIndexerScheduler(
        store=store,
        poller=poller,
        start_block=max(0, min(blocks) - 2),
        confirmations=int(os.environ.get("INDEXER_CONFIRMATIONS", "0")),
        reorg_window=8,
    )
    result = await scheduler.run_once()
    print(json.dumps(result.__dict__, indent=2))

asyncio.run(main())
PY

curl -fsS "${APP_URL}/jobs/${JOB_ID}" >"${RUNTIME_DIR}/job-after-indexer.json"
curl -fsS "${APP_URL}" >"${RUNTIME_DIR}/index-after-indexer.html"

section "Evidence Summary"
"${PYTHON}" - <<'PY' | while IFS= read -r line; do ok "${line}"; done
import asyncio
import json
import os
from pathlib import Path

from app.store import JobStore

runtime = Path(os.environ["SIGNAL_COUNT_BATTLE_RUNTIME_DIR"])
job = json.loads((runtime / "job-after-indexer.json").read_text())
run_metadata = job.get("run_metadata", {})
ledger = job.get("provenance_ledger", [])
roles = ", ".join(
    f"{item.get('node_role')}={item.get('status')}"
    for item in ledger
    if isinstance(item, dict)
) or "none"
receipts = [
    item for item in run_metadata.get("chain_receipts", [])
    if isinstance(item, dict) and item.get("tx_hash")
]
ree = [
    item.get("ree_status")
    for item in run_metadata.get("chain_receipts", [])
    if isinstance(item, dict) and item.get("ree_status")
]
reputation_receipts = [
    item for item in receipts if item.get("kind") == "reputation"
]
if reputation_receipts:
    raise SystemExit(
        "Unexpected reputation receipt: unsigned runtime responses must not receive credit"
    )
credit_eligible_updates = [
    item for item in run_metadata.get("reputation_updates", [])
    if isinstance(item, dict) and item.get("credit_eligible") is True
]
if credit_eligible_updates:
    raise SystemExit(
        "Unexpected credit-eligible update from unsigned SpecialistResponse transport"
    )
projection = asyncio.run(JobStore().get_indexed_chain_projection())
print(f"roles: {roles}")
print(f"chain receipts: {len(receipts)}")
print(f"REE status: {ree[0] if ree else 'not present'}")
print(
    "runtime reputation/payout transactions: unavailable "
    "(unsigned SpecialistResponse transport)"
)
print(
    "indexed events: "
    f"tasks={len(projection.tasks)}, "
    f"contributions={len(projection.contributions)}, "
    f"verifications={len(projection.verifications)}"
)
PY

TOTAL_SECONDS="$(elapsed)"
section "Done"
ok "Full battle run completed in ${TOTAL_SECONDS}s"
ok "UI: ${APP_URL}"
ok "Runtime: ${RUNTIME_DIR}"
ok "Logs: ${LOG_DIR}"
warn "Stop with: scripts/stop_full_battle_demo.sh"
