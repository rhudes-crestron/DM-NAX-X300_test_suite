#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  DM-NAX DSP Test Suite - Main Runner
#  Phase 1: Firmware upgrade (imgupd / puf)
#  Phase 2: DSP tests
#  Generates JSON + HTML report, stores results
# ═══════════════════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults
DEVICE="${1:-DM-NAX-4ZSA}"
CONFIG="config/devices.yaml"
RESULTS_BASE="results"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
RESULTS_DIR="${RESULTS_BASE}/${TIMESTAMP}"
SKIP_UPGRADE="${SKIP_UPGRADE:-false}"

# Optional overrides (env vars or positional args)
DEVICE_IP="${DEVICE_IP:-${2:-}}"
DEVICE_USER="${DEVICE_USER:-${3:-}}"
DEVICE_PASS="${DEVICE_PASS:-${4:-}}"
FIRMWARE_FILE="${FIRMWARE_FILE:-${5:-}}"

# Build extra pytest args for CLI overrides
EXTRA_ARGS=""
[ -n "${DEVICE_IP}" ]      && EXTRA_ARGS="${EXTRA_ARGS} --ip=${DEVICE_IP}"
[ -n "${DEVICE_USER}" ]    && EXTRA_ARGS="${EXTRA_ARGS} --username=${DEVICE_USER}"
[ -n "${DEVICE_PASS}" ]    && EXTRA_ARGS="${EXTRA_ARGS} --password=${DEVICE_PASS}"
[ -n "${FIRMWARE_FILE}" ]  && EXTRA_ARGS="${EXTRA_ARGS} --firmware-file=${FIRMWARE_FILE}"

# Resolve effective IP for device_info (CLI override or from YAML)
EFFECTIVE_IP="${DEVICE_IP}"
if [ -z "${EFFECTIVE_IP}" ]; then
    EFFECTIVE_IP=$(python3 -c "import yaml; d=yaml.safe_load(open('${CONFIG}')); print(d['devices']['${DEVICE}']['ip'])" 2>/dev/null || echo "unknown")
fi

echo "═══════════════════════════════════════════════════════════"
echo "  DM-NAX Nightly Test Suite"
echo "  Device:  ${DEVICE}"
[ -n "${DEVICE_IP}" ] && echo "  IP:      ${DEVICE_IP} (override)"
echo "  Time:    ${TIMESTAMP}"
echo "  Results: ${RESULTS_DIR}"
echo "═══════════════════════════════════════════════════════════"

# Create results directory
mkdir -p "${RESULTS_DIR}"

# Install dependencies if needed
if ! python3 -c "import paramiko, pytest, yaml, jinja2" 2>/dev/null; then
    echo "[*] Installing Python dependencies..."
    pip3 install -r requirements.txt --quiet
fi

# ───────────────────────────────────────────────────────────────
#  PHASE 1: Firmware Upgrade
# ───────────────────────────────────────────────────────────────
UPGRADE_EXIT=0
if [ "${SKIP_UPGRADE}" = "true" ]; then
    echo "[*] Firmware upgrade SKIPPED (SKIP_UPGRADE=true)"
else
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  PHASE 1: Firmware Upgrade"
    echo "═══════════════════════════════════════════════════════════"
    python3 -m pytest tests/test_device_upgrade.py \
        --device="${DEVICE}" \
        --config="${CONFIG}" \
        --results-dir="${RESULTS_DIR}" \
        --json-report \
        --json-report-file="${RESULTS_DIR}/upgrade_results.json" \
        --tb=short \
        -v \
        ${EXTRA_ARGS} \
        2>&1 | tee "${RESULTS_DIR}/upgrade_console.log"

    UPGRADE_EXIT=${PIPESTATUS[0]}

    if [ ${UPGRADE_EXIT} -ne 0 ]; then
        echo ""
        echo "[!] Firmware upgrade FAILED (exit code ${UPGRADE_EXIT})"
        echo "[!] Continuing with DSP tests on current firmware..."
    else
        echo "[*] Firmware upgrade PASSED"
    fi
fi

# ───────────────────────────────────────────────────────────────
#  PHASE 2: DSP Tests
# ───────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PHASE 2: DSP Tests"
echo "═══════════════════════════════════════════════════════════"

python3 -m pytest tests/ \
    --ignore=tests/test_device_upgrade.py \
    --device="${DEVICE}" \
    --config="${CONFIG}" \
    --results-dir="${RESULTS_DIR}" \
    --json-report \
    --json-report-file="${RESULTS_DIR}/results.json" \
    --tb=short \
    -v \
    ${EXTRA_ARGS} \
    2>&1 | tee "${RESULTS_DIR}/console.log"

TEST_EXIT_CODE=${PIPESTATUS[0]}

# Save device info
python3 -c "
import yaml, json, sys
sys.path.insert(0, '.')
from lib.device_ssh import DeviceSSH
with open('${CONFIG}') as f:
    cfg = yaml.safe_load(f)
dev = cfg['devices']['${DEVICE}']
# Apply CLI overrides
ip = '${DEVICE_IP}' or dev['ip']
user = '${DEVICE_USER}' or dev['username']
pw = '${DEVICE_PASS}' or dev['password']
info = {'model': dev['model'], 'ip': ip, 'zones': dev['zones']}
try:
    ssh = DeviceSSH(ip, user, pw)
    ssh.connect()
    info['version'] = ssh.get_version()
    ssh.disconnect()
except:
    info['version'] = 'N/A'
with open('${RESULTS_DIR}/device_info.json', 'w') as f:
    json.dump(info, f, indent=2)
print('[*] Device info saved')
"

# Merge upgrade + DSP results into a single JSON for unified HTML report
python3 -c "
import json, os, sys
results_dir = '${RESULTS_DIR}'
dsp_path = os.path.join(results_dir, 'results.json')
upgrade_path = os.path.join(results_dir, 'upgrade_results.json')
merged_path = os.path.join(results_dir, 'all_results.json')

# Start with DSP results
with open(dsp_path) as f:
    merged = json.load(f)

# Prepend upgrade results if available
if os.path.isfile(upgrade_path):
    with open(upgrade_path) as f:
        upgrade = json.load(f)
    upgrade_tests = upgrade.get('tests', [])
    merged['tests'] = upgrade_tests + merged.get('tests', [])
    # Merge summary counts
    for key in ('passed', 'failed', 'skipped', 'error'):
        merged.setdefault('summary', {})[key] = (
            merged.get('summary', {}).get(key, 0)
            + upgrade.get('summary', {}).get(key, 0)
        )
    merged['summary']['total'] = len(merged['tests'])
    merged['summary']['duration'] = (
        merged.get('summary', {}).get('duration', 0)
        + upgrade.get('summary', {}).get('duration', 0)
    )
    print('[*] Merged upgrade + DSP results')
else:
    print('[*] No upgrade results to merge')

with open(merged_path, 'w') as f:
    json.dump(merged, f, indent=2)
"

# Generate HTML report from merged results
python3 -c "
import sys
sys.path.insert(0, '.')
from lib.report_generator import generate_report
import json

device_info = {}
try:
    with open('${RESULTS_DIR}/device_info.json') as f:
        device_info = json.load(f)
except: pass

generate_report(
    '${RESULTS_DIR}/all_results.json',
    '${RESULTS_DIR}/report.html',
    device_info=device_info,
)
print('[*] HTML report generated')
"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  RESULTS"
echo "  Upgrade: ${RESULTS_DIR}/upgrade_results.json  (exit=${UPGRADE_EXIT})"
echo "  DSP:     ${RESULTS_DIR}/results.json           (exit=${TEST_EXIT_CODE})"
echo "  Merged:  ${RESULTS_DIR}/all_results.json"
echo "  HTML:    ${RESULTS_DIR}/report.html"
echo "  Log:     ${RESULTS_DIR}/console.log"
echo ""
echo "  Start dashboard:  python3 dashboard.py"
echo "  Then visit:       http://localhost:5000"
echo "═══════════════════════════════════════════════════════════"

# Exit with failure if either phase failed
if [ ${UPGRADE_EXIT} -ne 0 ] || [ ${TEST_EXIT_CODE} -ne 0 ]; then
    exit 1
fi
