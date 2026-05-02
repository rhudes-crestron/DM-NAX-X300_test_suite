# DM-NAX DSP Test Suite — Running Tests Guide

This guide covers every way to run the test suite: quick ad-hoc pytest commands,
the full shell script runner, the multi-device orchestrator, the nightly build-server
timer, and how to extend the suite with new tests and new devices.

---

## Table of Contents

1. [Directory Overview](#1-directory-overview)
2. [Prerequisites](#2-prerequisites)
3. [Device Types and Their Profiles](#3-device-types-and-their-profiles)
4. [Running a Single Test or Test File](#4-running-a-single-test-or-test-file)
5. [Running a Full Test Suite for One Device](#5-running-a-full-test-suite-for-one-device)
   - 5a. [Direct pytest](#5a-direct-pytest)
   - 5b. [run_tests.sh helper](#5b-run_testssh-helper)
6. [Zone Modes — full, quick, explicit](#6-zone-modes--full-quick-explicit)
7. [Overriding Device Connection Details at Runtime](#7-overriding-device-connection-details-at-runtime)
8. [Skipping the Firmware Upgrade Phase](#8-skipping-the-firmware-upgrade-phase)
9. [Including or Excluding Specific Tests](#9-including-or-excluding-specific-tests)
10. [Running All Devices in Parallel (Orchestrator)](#10-running-all-devices-in-parallel-orchestrator)
11. [Running on the Build Server (Nightly Timer)](#11-running-on-the-build-server-nightly-timer)
12. [Viewing Results and HTML Reports](#12-viewing-results-and-html-reports)
13. [Adding a New Test to an Existing Device](#13-adding-a-new-test-to-an-existing-device)
14. [Adding a New Device Type](#14-adding-a-new-device-type)
15. [Reference: All pytest CLI Options](#15-reference-all-pytest-cli-options)

---

## 1. Directory Overview

```
nightly_testing/dsp_test_suite/
├── conftest.py               # pytest fixtures and CLI option definitions
├── orchestrator.py           # multi-device parallel runner
├── run_tests.sh              # single-device shell wrapper (upgrade + DSP tests)
├── requirements.txt          # Python dependencies
├── config/
│   ├── devices.yaml          # device hardware profiles (IP, zones, fw version…)
│   └── test_manifest.yaml    # which tests run on which device; test groups
├── tests/                    # all test files (one class / feature per file)
│   ├── test_eq.py
│   ├── test_balance.py
│   ├── test_signal_routing.py
│   └── …
├── lib/                      # shared helpers (SSH, CresNext client, DSP controller…)
├── deploy/                   # systemd service + timer files for build server
└── results/                  # auto-generated; one sub-directory per run
```

---

## 2. Prerequisites

```bash
cd /home/builduser/Linux_jstr1000/nightly_testing/dsp_test_suite

# Install Python dependencies (only needed once)
pip3 install -r requirements.txt
```

All commands below assume the working directory is the suite root above.
The device under test must be reachable on the network (SSH port 22, HTTPS port 443).

---

## 3. Device Types and Their Profiles

Three devices are currently configured in [config/devices.yaml](../config/devices.yaml):

| Profile name    | Model  | IP              | DSP fw | Zones | Signal generator channel |
|-----------------|--------|-----------------|--------|-------|--------------------------|
| `DM-NAX-4ZSA`  | 4ZSA   | 192.168.1.157   | fw21   | 4     | ch28 (dedicated SIG)     |
| `DM-NAX-8ZSA`  | 8ZSA   | 192.168.1.178   | fw42   | 8     | ch0  (S1L / Input01)     |
| `DM-NAX-4ZSP`  | 4ZSP   | 192.168.1.179   | fw42   | 8     | ch0  (T1L / Input01)     |

**Key fw42 differences (8ZSA, 4ZSP):**
- Zone routing uses the `StreamRoutings` REST path instead of per-zone `AvMatrixRouting`.
- `dsp_tone_input` in the profile tells the suite which CresNext input carries the DSP tone bus.
- `quick` zone profile for 8ZSA/4ZSP tests zones `[2, 4, 5, 8]`; for 4ZSA it tests `[1, 3]`.

---

## 4. Running a Single Test or Test File

The fastest way to iterate on a specific test during development.

### Run one test function

```bash
pytest tests/test_eq.py::TestEQ::test_eq_affects_output_level \
    --device DM-NAX-8ZSA --config config/devices.yaml -v
```

### Run one test class

```bash
pytest tests/test_balance.py::TestBalance \
    --device DM-NAX-8ZSA --config config/devices.yaml -v
```

### Run one entire test file

```bash
pytest tests/test_signal_routing.py \
    --device DM-NAX-8ZSA --config config/devices.yaml -v
```

### Run signal routing test and generate HTML report in one command

```bash
# DM-NAX-4ZSA
pytest tests/test_signal_routing.py \
    --device DM-NAX-4ZSA --config config/devices.yaml \
    --json-report --json-report-file=results/routing_4zsa.json -v && \
python3 -c "
import sys, json, yaml
sys.path.insert(0, '.')
from lib.report_generator import generate_report
device = yaml.safe_load(open('config/devices.yaml'))['devices']['DM-NAX-4ZSA']
generate_report('results/routing_4zsa.json', 'results/routing_4zsa.html', device_info=device)
print('Report: results/routing_4zsa.html')
"

# DM-NAX-8ZSA
pytest tests/test_signal_routing.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --json-report --json-report-file=results/routing_8zsa.json -v && \
python3 -c "
import sys, json, yaml
sys.path.insert(0, '.')
from lib.report_generator import generate_report
device = yaml.safe_load(open('config/devices.yaml'))['devices']['DM-NAX-8ZSA']
generate_report('results/routing_8zsa.json', 'results/routing_8zsa.html', device_info=device)
print('Report: results/routing_8zsa.html')
"
```

The `&&` ensures the report is only generated if pytest exits with code 0 (all tests passed).
To generate the report even when tests fail, replace `&&` with `;`.

### Run several test files together

```bash
pytest tests/test_eq.py tests/test_balance.py \
    --device DM-NAX-8ZSA --config config/devices.yaml -v
```

### Run the same test on a different device

Just change `--device`:

```bash
pytest tests/test_eq.py \
    --device DM-NAX-4ZSA --config config/devices.yaml -v

pytest tests/test_eq.py \
    --device DM-NAX-4ZSP --config config/devices.yaml -v
```

---

## 5. Running a Full Test Suite for One Device

### 5a. Direct pytest

Runs all tests in the `tests/` directory for one device, **skipping** the
firmware upgrade test:

```bash
# DM-NAX-4ZSA  (fw21)
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-4ZSA --config config/devices.yaml \
    --zone-mode full -v

# DM-NAX-8ZSA  (fw42)
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --zone-mode full -v

# DM-NAX-4ZSP  (fw42)
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-4ZSP --config config/devices.yaml \
    --zone-mode full -v
```

### 5b. run_tests.sh helper

`run_tests.sh` wraps pytest in two phases (firmware upgrade → DSP tests),
creates a timestamped results directory, and generates an HTML report.

```bash
# Syntax: ./run_tests.sh <DEVICE> [IP] [USERNAME] [PASSWORD] [FIRMWARE_FILE]

# Run with config defaults
./run_tests.sh DM-NAX-4ZSA
./run_tests.sh DM-NAX-8ZSA
./run_tests.sh DM-NAX-4ZSP

# Run with IP override (useful for devices not at the default address)
./run_tests.sh DM-NAX-8ZSA 192.168.10.22

# Skip the firmware upgrade phase
SKIP_UPGRADE=true ./run_tests.sh DM-NAX-8ZSA

# Use quick zone subset
ZONE_MODE=quick ./run_tests.sh DM-NAX-8ZSA

# Test only specific zones (comma-separated)
ZONE_LIST=2,5,8 ./run_tests.sh DM-NAX-8ZSA

# Point at a specific firmware file
FIRMWARE_FILE=/path/to/firmware.puf ./run_tests.sh DM-NAX-8ZSA
```

Results are written to `results/<TIMESTAMP>_<DEVICE>/`.

---

## 6. Zone Modes — full, quick, explicit

The `--zone-mode` option (or `ZONE_MODE` env var) controls which zones are exercised
in parametrized tests (e.g. volume, balance, EQ, routing).

| Mode      | What it does                                                          |
|-----------|-----------------------------------------------------------------------|
| `full`    | All zones on the device (default). 8ZSA = zones 1–8, 4ZSA = 1–4     |
| `quick`   | Representative subset from `zone_profiles` in `devices.yaml`         |
| explicit  | Pass `--zones 2,4,8` to force an exact list, overrides `zone-mode`   |

```bash
# Full run — all 8 zones on 8ZSA
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --zone-mode full

# Quick run — zones 2,4,5,8 only (faster for CI smoke check)
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --zone-mode quick

# Explicit zones
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --zones 1,3,7
```

To change the `quick` zone selection, edit [config/devices.yaml](../config/devices.yaml)
under `zone_profiles.quick.<DEVICE>`.

---

## 7. Overriding Device Connection Details at Runtime

Useful for testing a device that is not at its default IP (e.g. a bench unit
borrowed from another lab), without editing `devices.yaml`.

```bash
# Override IP only
pytest tests/test_signal_routing.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --ip 192.168.50.100

# Override IP, username, and password
pytest tests/test_signal_routing.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --ip 192.168.50.100 --username admin --password MyPassword

# Same overrides work with run_tests.sh
DEVICE_IP=192.168.50.100 DEVICE_USER=admin DEVICE_PASS=MyPassword \
    ./run_tests.sh DM-NAX-8ZSA
```

---

## 8. Skipping the Firmware Upgrade Phase

By default `run_tests.sh` runs `test_device_upgrade.py` first.
Direct `pytest` invocations skip it unless you explicitly include it.

```bash
# run_tests.sh — skip upgrade
SKIP_UPGRADE=true ./run_tests.sh DM-NAX-8ZSA

# Direct pytest — skip upgrade by ignoring the file
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml

# Direct pytest — run ONLY the upgrade test
pytest tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --firmware-file /path/to/firmware.puf -v
```

---

## 9. Including or Excluding Specific Tests

### Crosstalk tests (excluded by default)

Crosstalk tests are excluded from collection unless you opt in:

```bash
# Include crosstalk tests
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --include-crosstalk

# Without the flag, test_crosstalk.py is deselected automatically
```

### Run only a named test group (using -k keyword filter)

```bash
# Only EQ-related tests
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    -k "eq or bass or treble or loudness"

# Only volume and mute tests
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-4ZSA --config config/devices.yaml \
    -k "volume or mute or balance"

# Only signal routing
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    -k "signal_routing or input_mute"

# Exclude a specific test by name
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    -k "not clipping"
```

### Run tests that match a category

The `--category` option is forwarded to pytest markers if you use them
(`dsp`, `streaming`, `firmware`):

```bash
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --category dsp
```

---

## 10. Running All Devices in Parallel (Orchestrator)

`orchestrator.py` reads [config/test_manifest.yaml](../config/test_manifest.yaml)
and launches one pytest child process per enabled device, in parallel.

```bash
# Run all enabled devices (currently 4ZSA, 8ZSA, 4ZSP)
python3 orchestrator.py

# Run specific devices only
python3 orchestrator.py --targets DM-NAX-4ZSA DM-NAX-8ZSA
python3 orchestrator.py --targets DM-NAX-8ZSA

# Run a named schedule (reads the schedule block in test_manifest.yaml)
python3 orchestrator.py --schedule nightly

# Skip firmware upgrade for all targets
python3 orchestrator.py --skip-upgrade

# Skip upgrade for a specific device run
python3 orchestrator.py --targets DM-NAX-8ZSA --skip-upgrade
```

The orchestrator creates a timestamped results directory per device:

```
results/
  2026-04-23_01-00-00_DM-NAX-4ZSA/
    report.html
    console.log
    results.json
    upgrade_results.json
    all_results.json
  2026-04-23_01-00-00_DM-NAX-8ZSA/
    report.html
    …
```

**Per-device timeouts** are controlled by `timeout_minutes` in `test_manifest.yaml`
(default: 180 minutes). After a firmware upgrade, the orchestrator waits up to
`post_upgrade_cresnext_timeout_s` (default: 600 s) for CresNext to become ready
before starting DSP tests.

---

## 11. Running on the Build Server (Nightly Timer)

The build server (`nj6v-docker-04`) runs the full suite automatically every night
at **01:00 local time** using a systemd timer.

---

### ⚠️ Critical: Always use the venv Python

The suite is installed in a Python virtual environment at
`/opt/dmnax-test-suite/venv/`.  **Never use bare `python3`** — it picks up the
system interpreter which is missing `paramiko`, `pytest-json-report`, and other
required packages.

```bash
# WRONG — uses system Python → "No module named 'paramiko'" errors
python3 orchestrator.py

# CORRECT — uses venv Python with all dependencies installed
cd /opt/dmnax-test-suite
venv/bin/python3 orchestrator.py
```

Add a permanent alias so you never have to remember this (run once per user):

```bash
echo 'alias dmnax-run="cd /opt/dmnax-test-suite && venv/bin/python3 orchestrator.py"' >> ~/.bashrc
source ~/.bashrc
```

---

### First-time server setup

```bash
# 1. Clone the repo as builduser (who has the SSH key registered on GitHub)
sudo mkdir -p /opt/dmnax-test-suite
sudo chown builduser:builduser /opt/dmnax-test-suite
git clone git@nj-github.crestron.crestron.com:CrestronEngineering/DM-NAX_test_suite.git \
    /opt/dmnax-test-suite

# 2. Run setup as root (skips git clone since files are already present)
sudo bash /opt/dmnax-test-suite/deploy/setup_server.sh
```

`setup_server.sh` installs system packages, creates the `dmnax-test` service user,
creates the venv, installs Python dependencies (including `paramiko`), and
installs the systemd units.

If pip install fails silently or packages are missing after setup:

```bash
sudo /opt/dmnax-test-suite/venv/bin/pip install -r /opt/dmnax-test-suite/requirements.txt
# Then verify:
/opt/dmnax-test-suite/venv/bin/python3 -c "import paramiko, pytest, requests; print('OK')"
```

Fix the urllib3/requests version warning:

```bash
sudo /opt/dmnax-test-suite/venv/bin/pip install --upgrade "urllib3<2" requests chardet
```

---

### Updating the suite (after code changes on dev machine)

```bash
# SSH into the build server as builduser
cd /opt/dmnax-test-suite

# Allow git to operate on the directory (one-time, if not already set)
sudo git config --system --add safe.directory /mnt/data/opt/dmnax-test-suite

# Fix ownership if root took over the .git directory
sudo chown -R builduser:builduser /opt/dmnax-test-suite

# Pull latest changes
git pull origin master
```

---

### Manual runs on the build server

```bash
cd /opt/dmnax-test-suite

# Run all enabled devices (full nightly equivalent, no upgrade)
venv/bin/python3 orchestrator.py --skip-upgrade

# Run a specific device only
venv/bin/python3 orchestrator.py --targets DM-NAX-4ZSP --skip-upgrade
venv/bin/python3 orchestrator.py --targets DM-NAX-8ZSA --skip-upgrade
venv/bin/python3 orchestrator.py --targets DM-NAX-4ZSA --skip-upgrade

# Run with firmware upgrade
venv/bin/python3 orchestrator.py --targets DM-NAX-4ZSP

# Run a single test file against one device
venv/bin/python3 -m pytest tests/test_signal_routing.py \
    --device DM-NAX-4ZSP --config config/devices.yaml -v

# Override device IP at runtime (without editing devices.yaml)
venv/bin/python3 -m pytest tests/test_signal_routing.py \
    --device DM-NAX-4ZSP --config config/devices.yaml \
    --ip dm-nax-4zsp-00107fca06ff -v
```

---

### Systemd units (build server: `/opt/dmnax-test-suite/`)

| File                        | Purpose                                     |
|-----------------------------|---------------------------------------------|
| `dmnax-nightly.timer`       | Fires at `01:00:00` daily                   |
| `dmnax-nightly.service`     | Runs `orchestrator.py --schedule nightly`   |
| `dmnax-dashboard.service`   | Serves the web dashboard on port 8080       |

```bash
# Check timer status and next trigger time
systemctl status dmnax-nightly.timer

# Manually trigger a nightly run right now (does not wait for 01:00)
sudo systemctl start dmnax-nightly.service

# Watch live log output during a run
journalctl -fu dmnax-nightly.service
# or read the log file directly
tail -f /var/log/dmnax-test/nightly.log

# Check dashboard service
systemctl status dmnax-dashboard.service

# Restart dashboard after a code change
sudo systemctl restart dmnax-dashboard.service

# Change the nightly time (e.g. to 02:30)
# Edit /etc/systemd/system/dmnax-nightly.timer → OnCalendar=*-*-* 02:30:00
sudo systemctl daemon-reload
sudo systemctl restart dmnax-nightly.timer
```

---

### Firmware directories (build server mount points)

Firmware files are auto-detected by newest modification time — no manual
path configuration needed as long as the nightly build drops files into the
correct directories.

| Device       | Mount path                  | File pattern              |
|--------------|-----------------------------|---------------------------|
| DM-NAX-4ZSA  | `/mnt/nightly/DM-NAX-4ZSA`  | `dm-nax-4zsa*.zip`        |
| DM-NAX-8ZSA  | `/mnt/nightly/DM-NAX`       | `dm-nax-trunk-nightly*.puf` |
| DM-NAX-4ZSP  | `/mnt/nightly/DM-NAX`       | `dm-nax-trunk-nightly*.puf` |

Verify mounts are accessible before running:

```bash
ls /mnt/nightly/DM-NAX-4ZSA/*.zip   # should show latest 4ZSA zip
ls /mnt/nightly/DM-NAX/*.puf        # should show latest 8ZSA/4ZSP puf
```

---

### Viewing results on the build server

The dashboard is served by gunicorn behind nginx on **port 80**:

```
http://<build-server-hostname>/
```

Raw result directories are at `/opt/dmnax-test-suite/results/`.
Results older than `results_retention_days` (default: 30 days, set in
`test_manifest.yaml` under `defaults`) are automatically purged.

---

## 12. Viewing Results and HTML Reports

After every run (via script, orchestrator, or nightly timer) a self-contained
HTML report is generated:

```
results/<TIMESTAMP>_<DEVICE>/report.html
```

Open it in any browser. It contains:
- Pass/fail/skip summary table
- Per-test duration
- Failure messages and tracebacks
- Device info (model, IP, firmware version)

Programmatic access: `results.json` (DSP tests), `upgrade_results.json` (firmware),
`all_results.json` (merged, used by the HTML generator).

---

## 13. Adding a New Test to an Existing Device

### Step 1 — Create the test file

Add `tests/test_<feature>.py`. Follow the existing class pattern:

```python
# tests/test_my_feature.py
import pytest

class TestMyFeature:
    def test_something(self, dsp, device_cfg, test_settings):
        # dsp       → DSPController instance (SSH + CresNext)
        # device_cfg → dict from devices.yaml for the active device
        # test_settings → dict from devices.yaml test_settings block
        ...
```

Available session-scoped fixtures (defined in `conftest.py`):

| Fixture         | Type             | Description                                      |
|-----------------|------------------|--------------------------------------------------|
| `dsp`           | `DSPController`  | SSH + CresNext combined controller               |
| `ssh`           | `DeviceSSH`      | Raw SSH connection                               |
| `cresnext`      | `CresNextClient` | REST API client (authenticated)                  |
| `device_cfg`    | `dict`           | Active device profile from `devices.yaml`        |
| `test_settings` | `dict`           | Shared tolerances and timing constants           |
| `selected_zones`| `list[int]`      | Zone numbers after mode/profile filtering        |
| `config`        | `dict`           | Full parsed `devices.yaml`                       |

For zone-parametrized tests, parametrize on `selected_zones`:

```python
@pytest.fixture(params=range(1, 9))   # let conftest filter by selected_zones
def zone(request):
    return request.param

class TestMyFeature:
    def test_per_zone(self, dsp, device_cfg, zone, test_settings):
        ...
```

### Step 2 — Add the test to test_manifest.yaml

Either add it to an existing group or create a new group:

```yaml
# In config/test_manifest.yaml

# Option A: add to an existing group
  dsp_processing: &dsp_processing
    - tests/test_eq.py
    - tests/test_my_feature.py   # ← add here

# Option B: create a new group and reference it under each device
test_groups:
  my_group: &my_group
    - tests/test_my_feature.py

test_targets:
  DM-NAX-8ZSA:
    tests:
      - *my_group
```

### Step 3 — If the test only applies to certain devices

Use `skip_tests` in `test_manifest.yaml`:

```yaml
  DM-NAX-4ZSA:
    skip_tests:
      - tests/test_my_feature.py   # not supported on fw21
```

Or add a runtime guard inside the test:

```python
def test_something(self, device_cfg):
    if device_cfg.get("dsp_fw_version", 21) < 42:
        pytest.skip("Requires fw42")
```

---

## 14. Adding a New Device Type

### Step 1 — Add hardware profile to devices.yaml

```yaml
# config/devices.yaml
devices:
  DM-NAX-NEW:
    ip: "192.168.1.200"
    username: "admin"
    password: "crestron"
    model: "NEW"
    zones: 4
    amp_outputs: ["A1L","A1R","A2L","A2R","A3L","A3R","A4L","A4R"]
    line_outputs: ["L1L","L1R"]
    network_outputs: ["N1L","N1R","N2L","N2R","N3L","N3R","N4L","N4R"]
    physical_inputs:
      S1: { channels: ["S1L","S1R"], index: [0,1], type: "stream" }
    signal_generator: { channel: 28, name: "SIG" }   # or ch0 for fw42
    mixer_outputs: 8
    dsp_fw_version: 21      # or 42
    has_speaker_protect: false
    ssh_port: 22
    dsp_tone_input: "Input01"   # required for fw42 devices
    streaming:
      base_port: 60001
      zones:
        1: { input: "Input05", port: 60001, tone_hz: 100 }
        2: { input: "Input06", port: 60002, tone_hz: 200 }
      audio_server_port: 8088
```

Key fields that affect test behaviour:

| Field               | Effect                                                              |
|---------------------|---------------------------------------------------------------------|
| `dsp_fw_version`    | `42` enables StreamRoutings REST path for zone source routing       |
| `signal_generator.channel` | DSP tone-generator channel used for routing/DSP tests        |
| `dsp_tone_input`    | CresNext input name that carries the DSP tone bus (fw42 only)       |
| `has_speaker_protect` | Enables/disables `test_speaker_protect.py`                       |
| `zones`             | Upper bound for zone parametrization                                |

Also add the device to `zone_profiles.quick` if you want a quick-mode subset:

```yaml
zone_profiles:
  quick:
    DM-NAX-NEW: [1, 3]
```

### Step 2 — Add a test target to test_manifest.yaml

```yaml
test_targets:
  DM-NAX-NEW:
    enabled: true          # set false to register but not run yet
    device: "DM-NAX-NEW"
    firmware_file: ""
    tests:
      - *firmware
      - *audio_quality
      - *dsp_processing
      - *volume_controls
      - *signal_routing
      - *amplifier
      - *streaming
    skip_tests:
      - tests/test_input_compensation.py   # if not applicable
    extra_pytest_args: "--zone-mode=quick"
```

### Step 3 — Verify the new device is discovered

```bash
# The orchestrator will include DM-NAX-NEW automatically
python3 orchestrator.py --targets DM-NAX-NEW --skip-upgrade

# Or run a single quick sanity check
pytest tests/test_signal_routing.py \
    --device DM-NAX-NEW --config config/devices.yaml -v
```

---

## 15. Reference: All pytest CLI Options

All custom options are defined in `conftest.py → pytest_addoption()`.

| Option                 | Default                        | Description                                              |
|------------------------|--------------------------------|----------------------------------------------------------|
| `--device`             | `DM-NAX-4ZSA`                 | Device profile name from `devices.yaml`                  |
| `--config`             | `config/devices.yaml`          | Path to the devices config file                          |
| `--results-dir`        | `results/`                     | Where to write JSON / HTML reports                       |
| `--ip`                 | _(from devices.yaml)_          | Override device IP address                               |
| `--username`           | _(from devices.yaml)_          | Override SSH/API username                                |
| `--password`           | _(from devices.yaml)_          | Override SSH/API password                                |
| `--firmware-file`      | _(auto-detect)_                | Explicit path to `.puf` or `.zip` for upgrade test       |
| `--zone-mode`          | `full`                         | `full` = all zones, `quick` = profiled subset            |
| `--zones`              | _(from zone-mode)_             | Explicit comma-separated zone list, e.g. `2,4,5,8`       |
| `--category`           | _(none)_                       | Test category filter: `dsp`, `streaming`, `firmware`     |
| `--include-crosstalk`  | `false`                        | Include `test_crosstalk.py` (excluded by default)        |

Standard pytest options that are especially useful:

| Option        | Description                                              |
|---------------|----------------------------------------------------------|
| `-v`          | Verbose — show each test name and result                 |
| `-q`          | Quiet — minimal output                                   |
| `-rs`         | Show reasons for skipped tests in summary                |
| `-x`          | Stop after the first failure                             |
| `--tb=short`  | Short tracebacks (default in run_tests.sh)               |
| `--tb=long`   | Full tracebacks for detailed debugging                   |
| `-k EXPR`     | Run only tests matching keyword expression               |
| `--lf`        | Re-run only last-failed tests                            |
| `--co`        | Collect only — list tests without running them           |

### Quick reference cheatsheet

```bash
# Smoke check — 2 zones, skip upgrade, one device
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --zone-mode quick -q

# Debug a single failing test with full traceback
pytest tests/test_balance.py::TestBalance::test_balance_full_left \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --tb=long -v -s

# List all tests that would run (dry-run)
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --co -q

# Re-run only the tests that failed in the last session
pytest tests/ --ignore=tests/test_device_upgrade.py \
    --device DM-NAX-8ZSA --config config/devices.yaml \
    --lf -v

# Full nightly-equivalent run for one device (with upgrade)
./run_tests.sh DM-NAX-8ZSA

# Full parallel run across all three devices
python3 orchestrator.py
```
