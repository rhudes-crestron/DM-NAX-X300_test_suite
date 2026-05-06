# DM-NAX DSP Test Suite — Session State & Hot-Start Document

**Last Updated:** 2026-05-06  
**Primary Developer:** praghupathy@crestron.com  
**Repository:** [CrestronEngineering/DM-NAX_test_suite](https://nj-github.crestron.crestron.com/CrestronEngineering/DM-NAX_test_suite)  
**Branch:** `master`  
**Latest Commit:** `13bb696` — "config: add recipients to nightly email notification list"

---

## 1. SYSTEM ARCHITECTURE

### 1.1 Repository Layout

```
dsp_test_suite/
├── conftest.py              # Fixtures: ssh, cresnext, dsp, device_cfg, module_reset, zone filtering
├── orchestrator.py          # Parallel runner: launches pytest per device from test_manifest.yaml
├── dashboard.py             # Flask web dashboard (Gunicorn/systemd)
├── run_tests.sh             # Nightly entry point (called by systemd timer)
├── start_dashboard.sh       # Dashboard startup script
├── requirements.txt         # Python deps
├── config/
│   ├── devices.yaml         # Hardware profiles: IPs, credentials, DSP params, sig-gen channels
│   └── test_manifest.yaml   # Which tests run on which devices, email config, schedule
├── lib/
│   ├── device_ssh.py        # SSH via paramiko; execute(), can_open_bash(), enable_engineering_debug()
│   ├── dsp_controller.py    # High-level DSP facade: tones, routing, zone-API via CresNext
│   ├── dsp_parser.py        # Parses `dsp` console output → DSPState dataclass (fw21 + fw42 formats)
│   ├── cresnext_client.py   # CresNext REST API wrapper (zone audio, routing, eq, etc.)
│   ├── streaming_client.py  # MediaPlayer/MediaStreamer HTTP + bash curl for streaming tests
│   ├── firmware_upgrader.py # SFTP upload + imgupd/puf execution for OTA test
│   ├── email_notifier.py    # SMTP HTML report sender
│   ├── report_generator.py  # Jinja2 HTML report builder (per-device + index)
│   ├── generate_tones.py    # Offline WAV generation for streaming test server
│   └── test_trace.py        # Per-test SSH command tracing to `.log` files
├── tests/
│   ├── test_volume.py       │
│   ├── test_mute.py         │
│   ├── test_eq.py           │  Core DSP zone-chain processing tests
│   ├── test_balance.py      │  (all use Amp/output_db measurement)
│   ├── test_bass_treble.py  │
│   ├── test_delay.py        │
│   ├── test_loudness.py     │
│   ├── test_night_mode.py   │
│   ├── test_tone_profiles.py│
│   ├── test_streaming.py         # End-to-end streaming (requires engineering debug)
│   ├── test_signal_routing.py    # CresNext AvMatrix + mixer verification
│   ├── test_input_mute.py        # CresNext input mute readback
│   ├── test_input_compensation.py # Input gain verification
│   ├── test_freq_response.py     # 20Hz–20kHz sweep flatness (audio quality)
│   ├── test_level_linearity.py   # Input-output linearity
│   ├── test_signal_to_noise.py   # Noise floor + SNR
│   ├── test_clipping.py          # AGC gain reduction under hot signal
│   ├── test_crosstalk.py         # Zone isolation (off by default — slow)
│   ├── test_amp_health.py        # ampctrl register readback
│   ├── test_bridging.py          # ZoneConfiguration API
│   ├── test_speaker_protect.py   # Speaker protection limit
│   ├── test_chimes.py            # Chime playback audio presence
│   └── test_device_upgrade.py    # Firmware upgrade lifecycle
├── docs/
│   └── audio_signal_flow_reference.html  # Interactive HTML reference (just committed)
├── audiofiles/              # Pre-generated WAV tones for streaming test server
├── results/                 # Timestamped run output (auto-purged after 30 days)
├── static/                  # Dashboard CSS/JS assets
├── templates/               # Jinja2 report templates
└── deploy/
    └── setup_server.sh      # Server provisioning: venv, systemd timer + dashboard service
```

### 1.2 Core Integration Points

```
┌──────────────────────────────────────────────────────────────────────┐
│  Build Server: nj6v-docker-04                                         │
│  ┌──────────────┐  systemd timer (1am)  ┌──────────────────────────┐│
│  │ orchestrator │ ───────────────────── │ pytest (per device)       ││
│  │   .py        │                       │   conftest fixtures       ││
│  └──────┬───────┘                       │   module_reset → dsp      ││
│         │                               │   tests (parametrized)    ││
│         │                               └───────┬───────────────────┘│
│         │                                       │                     │
│         │  ┌────────────────────────────────────┼─────────────────┐  │
│         ▼  │  DUT Network (10.64.36.0/24)       ▼                 │  │
│            │  ┌───────────────────────────────────────────────┐   │  │
│            │  │  DM-NAX Device (SSH port 22)                  │   │  │
│            │  │    • Console: dsp, ampctrl, ver, imgupd       │   │  │
│            │  │    • CresNext REST API (:443/cws/...)         │   │  │
│            │  │    • Engineering Debug SSH (port 6022)         │   │  │
│            │  │    • SFTP upload (firmware/, logs/)            │   │  │
│            │  └───────────────────────────────────────────────┘   │  │
│            └──────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────┐  HTTP :5050         ┌─────────────────────┐       │
│  │ Dashboard    │ ◄──── browser ──── │ Flask + Gunicorn     │       │
│  │ (results)    │                     │ (systemd service)    │       │
│  └──────────────┘                     └─────────────────────┘       │
│                                                                      │
│  /mnt/nightly/AM335x_dinap3/eng_dbg/engineering_debug.zip            │
│  (NFS mount from \\nj22l-fw-01\shares\NightlyBuild)                 │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.3 Device Under Test (DUT) Inventory

| Device | IP / Hostname | Creds | DSP Platform | Zones | Status |
|--------|---------------|-------|--------------|-------|--------|
| DM-NAX-4ZSA | dm-nax-4zsa-50-c4426800017c | admin / admin123 | fw21 (single SHARC) | 4 | Stable |
| DM-NAX-8ZSA | dm-nax-8zsa-00107fb5d1e3 (10.64.36.64) | admin / Crestron123 | fw42 (dual SHARC) | 8 | Active debug target |
| DM-NAX-4ZSP | dm-nax-4zsp-00107fca06ff | admin / crestron | fw42 (single block) | 4 | Stable |

---

## 2. DECISION LOG — Chronological

### Phase 1: Foundation (Apr 12–15)

| Date | Decision | Rationale |
|------|----------|-----------|
| Apr 12 | Initial commit: pytest + paramiko + yaml config | pytest gives parametrize + fixtures + HTML reports. paramiko for SSH. YAML for multi-device config. Zero CI dependency — runs standalone from a cron/systemd timer. |
| Apr 15 | Parallel orchestrator (one pytest session per DUT) | Devices are independent — running sequentially wastes 3x wall-clock time. Orchestrator launches subprocesses, collects results, merges reports. |
| Apr 15 | CresNext REST API for zone properties (NOT joins) | Joins are deprecated on DM-NAX. CresNext is the official control API and exactly mirrors the Toolbox UI. Avoids join-number lookup tables. |

### Phase 2: Deployment & Stabilization (May 2–4)

| Date | Decision | Rationale |
|------|----------|-----------|
| May 2 | systemd timer + service instead of cron | Cron doesn't capture stdout/stderr properly. systemd gives log journaling, restart-on-failure, and `systemctl status` visibility. |
| May 2 | Email notification via SMTP relay | Team needs morning visibility without checking dashboard. HTML summary with pass/fail counts and link to full report. |
| May 3 | `ampctrl faultst` timeout fix | Command hangs indefinitely if amp is in fault state. Added 10s timeout with forced channel close. |
| May 3 | Mark run as FAILED if 0 tests collected | Orchestrator was reporting "success" when pytest found no tests (bad config). Now explicitly fails. |
| May 4 | Python 3.8 compat: `removesuffix()` → manual slice | Build server has Python 3.8 (WSL). `str.removesuffix()` is 3.9+. Used `s[:-len(suffix)] if s.endswith(suffix) else s`. |
| May 4 | systemd TimeoutStopSec=14h | Full 8-zone + streaming + upgrade takes 8–10 hours. Default 90s timeout was killing mid-run. |

### Phase 3: 8ZSA Bring-Up — The Hard Part (May 5–6)

This is where 80% of the complexity lives. The 8ZSA has a fundamentally different DSP architecture that broke every assumption from the 4ZSA work.

| Date | Commit | Problem | Root Cause | Solution |
|------|--------|---------|------------|----------|
| May 5 | `1805c15` | Zones 5–8 show no signal | Only one signal generator (ch0/T1L) exists on block 0. Outputs 8–15 are on block 1 which has its own sig gen (ch8/T2L). | Added `signal_generator_dsp1` config key. `sig_ch_for_output(idx)` returns ch8 when idx≥8. |
| May 5 | `11754b5` | Even zones (2,4) Bass/Treble tests fail | Firmware bug: Bass/Treble CresNext writes are silently dropped on even zones. | Quick mode now uses odd zones only: `[1,3,5,7]`. |
| May 5 | `a7826e2` | fw42 zone tests show -inf despite mixer route | On fw42, `dsp mix` alone does NOT activate zone-chain processing (EQ/Bass/Treble/Volume are bypassed). | Use `AvMatrixRouting` via CresNext to activate zone chain. |
| May 5 | `5087da3` | Using ONLY AvMatrixRouting → -inf at amp output | AvMatrixRouting activates the chain but doesn't inject the DSP tone into it. The tone generator is a debug feature separate from real inputs. | Need BOTH: AvMatrixRouting (activates chain) + `dsp mix` (injects tone). |
| May 5 | `42c02e6` | Volume resets to default after route change | `HandleNewRoute` in DspAudioCtl firmware resets zone volume to ~30% when a new source is routed. | Added `route_settle_time_s` (0.5s) delay after AvMatrixRouting, then re-apply Volume=800. |
| May 5 | `b6a3fff` | Zone chain still not active after AvMatrixRouting | If the zone is already routed to "Input01", setting it again is a no-op in DspAudioCtl. | Toggle to a different input ("Input02") first, wait 200ms, then route back. Forces genuine HandleNewRoute. |
| May 5 | `f66d0cb` | Using `dsp mixout` (MIXER_CFG_CH_OUT) destroyed EQ | `dsp mixout` sends AUDIO_DSP_CMD_MIXER_CFG_CH_OUT which re-programs the output from scratch — wiping PEQ/Bass/Treble that AvMatrixRouting set up. | **NEVER use `dsp mixout` for test routing on fw42.** Only use `dsp mix` (MIXER_CFG_NODE) for crosspoints. |
| May 6 | `62ae03f` | Residual MIXER_CFG_CH_OUT usage | Same root cause as above — one code path still called `set_mixer_output()`. | Audit all fw42 paths; replaced with `set_mixer()`. |
| May 6 | `b3a7681` | EQ test "passes" but actually measuring pre-EQ signal | Parser regex captured group(7) = "Line" level (pre-EQ) instead of group(8) = "Amp" level (post-EQ). | Changed `output_db = _parse_float(out_m.group(8))` — uses OutA (amp output, post-everything). |
| May 6 | `3ca6644` | Zones 5,7 EQ test: -inf signal | Test was using `dsp.sig_ch` (ch0) for ALL zones. ch0 is on block 0 and cannot route to outputs 8–15 (block 1). | Every test now calls `dsp.sig_ch_for_output(output_idx)` to get the correct block's sig gen. |
| May 6 | `465f770` | Balance test shows 0dB difference at Full-Left | On fw42, Balance is applied to the INPUT channel level BEFORE the mixer (not in the output zone chain like fw21). Routing the same sig source to both L+R means Balance has nothing to differentiate. | Must use SEPARATE L and R tone channels (ch0→out0, ch1→out1) so Balance on each input matters. |
| May 6 | `8010542` | Balance test intermittently fails with KeyError | SSH response truncation on large DSP tables (16-zone dual-block output). Block 1 outputs sometimes missing from parsed state. | Added retry: if expected output name not in parsed results, re-read after 2s delay. |
| May 6 | `be7d0ec` | Streaming test looks for `M{n}L` (mux inputs) — doesn't exist on 8ZSA | 8ZSA DSP table has no mux input rows. Streaming audio enters differently on fw42. | Model-aware helpers: `_streaming_inputs_for_zone()` → returns `A{n}L/R` for fw42 (amp output), `M{n}L/R` for fw21 (mux input). Uses `measure_output_level()` for fw42. |

---

## 3. MINUTE DETAILS — Obscure Bugs & Naming Conventions

### 3.1 Critical Naming Conventions

| Term | Meaning | Gotcha |
|------|---------|--------|
| `output_db` | **Amp level (post-EQ, post-limiter)** — the ONLY measurement used for pass/fail | Parser bug #b3a7681: was reading `Line` column. |
| `ducker_db` | Post-mixer, pre-volume level | Used only by linearity/freq-response tests. |
| `Line` column | 4ZSA DSP output column = signal BEFORE zone EQ | Never use for EQ/Bass/Treble verification! |
| `Amp` / `OutA` | The actual amplifier output level | 8ZSA format: `outL / outA` — we use `outA` (group 8). |
| `Z{n}L` → `A{n}L` | 8ZSA zone names in DSP output | Parser auto-maps: `Z1L`→`A1L`, `Z1R`→`A1R` etc. Tests always reference `A{n}L`. |
| `sig_ch` | Signal generator channel for the DSP block | 4ZSA=ch28, 8ZSA block0=ch0, 8ZSA block1=ch8 |
| `MIXER_CFG_NODE` | `dsp mix` — sets single crosspoint WITHOUT affecting zone chain | Safe on all platforms. |
| `MIXER_CFG_CH_OUT` | `dsp mixout` — programs full output channel, DESTROYS zone state | **NEVER use on fw42 for test routing.** |
| `HandleNewRoute` | DspAudioCtl internal: resets volume to default on new input route | Must re-set Volume=800 after any AvMatrixRouting change. |
| `route_settle_time_s` | 0.5s delay after AvMatrixRouting | Needed because HandleNewRoute is async — volume reset races with our set. |
| `engineering_debug` | Special firmware mode enabling bash (port 6022) | Requires: upload zip → `imgupd engdbg` → reboot → port 6022 opens. |

### 3.2 Obscure Bugs & Edge Cases

1. **SPI Bus Hang:** Cross-block mixer commands (e.g., `dsp mix 8 2 -200` — ch8 is block1, out2 is block0) can hang the SPI bus. `clear_all_sig_routes()` only clears same-block routes.

2. **AvMatrixRouting No-Op:** If a zone is already routed to "Input01" and you set it again, DspAudioCtl ignores it. You MUST toggle to a different source first ("Input02"), wait 200ms, then set back. This is the "toggle trick."

3. **Even-Zone Bass/Treble Bug:** CresNext accepts Bass/Treble writes on zones 2,4 without error, but the DSP firmware silently ignores them. Only odd zones (1,3,5,7) on the 8ZSA respond to tone controls. Quick-mode profiles use `[1,3,5,7]` to work around this.

4. **SSH Response Truncation:** Large DSP tables (16+ rows) occasionally get truncated by paramiko's `recv()` if the device pauses mid-output. This manifests as missing outputs (typically block 1). Fix: retry read after 2s sleep in critical measurement paths.

5. **`dsp gain` Syntax Variance:** Some firmware images expect `dsp gain {ch} {val}`, others expect `dsp gain {ch} set {val}`. The `set_input_gain()` method tries both with fallback.

6. **CresNext Balance Range:** API uses -500 to +500 (0.1% steps), NOT -100 to +100. The test converts: `balance_pct * 5` for API calls.

7. **StreamRoutings vs AvMatrixRouting:** Two CresNext endpoints exist for zone source:
   - `set_zone_source(zone, input)` — AvMatrixRouting (original, per-zone)
   - `set_zone_sources_streamrouting({zone: input})` — StreamRoutings (batch, preferred on fw42)
   The streaming routing endpoint is more reliable for multi-zone operations.

8. **`imgupd engdbg` Does NOT Reboot:** Unlike `imgupd` for firmware, `imgupd engdbg` applies engineering debug mode in-place. After running it, `ver -v` shows "Eng Debug Mode: True" and port 6022 (dropbear) opens without a full reboot.

9. **`linux` Console Command:** NEVER use. It is user-access-level restricted on production-mode firmware. The ONLY supported bash path is: upload engineering_debug.zip → `imgupd engdbg` → SSH port 6022.

10. **Zone Output Index Formula:** Zone N → Left output = `(N-1)*2`, Right output = `(N-1)*2 + 1`. Zone 5 → out8/out9.

### 3.3 DSP Output Column Map

**4ZSA (fw21) — Single-line per channel pair:**
```
|Ch|Name |-|VCG|AG|DVO| (Balance)  Line    |Source    | |Ch| (Bal/Trim)  Ducker  AGC  (Gain)  Limiter  [Amp]  Invert| Output| Delay|
                         ↑                                                                              ↑
                         Pre-EQ (DO NOT USE)                                                            Post-EQ (USE THIS)
```

**8ZSA (fw42) — Pipe-delimited sections:**
```
| InputName |(Gain) Level |  | Ch| ZoneName |[Freq@dB] (Bal/Gain) MixLvl |(Trim) Ducker AGC (GainL/GainA) Lim OutL/[OutA] |
                                                                                                              ↑
                                                                                                   regex group(8) = output_db
```

---

## 4. STATE OF PLAY — Where We Stopped

### 4.1 Completed & Passing

- ✅ All DSP zone-chain tests (Volume, Mute, EQ, Bass/Treble, Delay, Loudness, Night Mode, Tone Profiles)
- ✅ Balance test with platform-aware L/R routing
- ✅ Signal routing and input mute tests
- ✅ Amp health and bridging tests
- ✅ Audio quality tests (freq response, linearity, SNR, clipping)
- ✅ Firmware upgrade test
- ✅ Chimes test
- ✅ Nightly orchestrator, email notifications, HTML dashboard
- ✅ HTML signal flow reference document

### 4.2 Blocked: Streaming Tests on 8ZSA

**Status:** Code is correct but CANNOT execute because bash access is unavailable on the build server.

**The Problem Chain:**
1. Streaming tests need to run `curl <url> | aplay` on the DUT's Linux subsystem
2. This requires bash access via engineering debug SSH (port 6022)
3. Port 6022 only opens after `imgupd engdbg` is run with the engineering_debug.zip uploaded
4. The zip lives at `/mnt/nightly/AM335x_dinap3/eng_dbg/engineering_debug.zip`
5. `/mnt/nightly/` is mounted on `nj6v-docker-04` (build server) but NOT on the dev machine (NJ116561LT)
6. The test suite currently runs from the dev machine
7. We verified: on nj6v-docker-04, the zip EXISTS and `sshpass` is NOT installed (but SSH key is now set up)

**Resolution Path:**
- Deploy the test suite to `nj6v-docker-04` (where `/mnt/nightly/` is mounted)
- OR: mount the NFS share on the dev machine
- OR: pre-copy the zip to a local path and configure `devices.yaml` → `engineering_debug.zip_file`

**In `device_ssh.py`:**
- `execute_bash()` has TWO paths: `_execute_via_debug_ssh` (port 6022) and `_execute_bash_via_console` (sends `linux` command)
- User directive: **REMOVE the `linux` command path entirely.** Only use engineering_debug + port 6022.
- The `_find_engineering_debug_zip()` method checks:
  1. `ENG_DEBUG_LINUX_MOUNT_ROOT` = `/mnt/nightly/AM335x_dinap3/eng_dbg` 
  2. `ENG_DEBUG_NETWORK_ROOT` = `\\nj22l-fw-01\shares\NightlyBuild\AM335x_dinap3\eng_dbg` (via smbclient)

### 4.3 Pending Tasks

| Priority | Task | Details |
|----------|------|---------|
| P0 | Deploy test suite to nj6v-docker-04 | `rsync` the suite; configure systemd timer there. /mnt/nightly is mounted. |
| P0 | Remove `_execute_bash_via_console` from device_ssh.py | User explicitly said: never use `linux` command. Only `imgupd engdbg`. |
| P1 | Verify streaming tests end-to-end on 8ZSA | After deploy, run: `pytest tests/test_streaming.py --device=DM-NAX-8ZSA -v` |
| P1 | Fix engineering_debug config in devices.yaml | Set `zip_file` or `search_roots` to point to `/mnt/nightly/AM335x_dinap3/eng_dbg/` |
| P2 | Add crosstalk test to nightly (currently excluded) | Needs `--include-crosstalk` flag; takes ~30min per device due to sequential zone isolation |
| P2 | Speaker protection limit verification | test_speaker_protect exists but needs hardware load to verify current limiting |
| P3 | Input compensation test for fw42 | Marked skip_tests — `dsp gain` syntax differs, needs ampctrl integration |

### 4.4 The Very Next Line of Code

In `lib/device_ssh.py`, the `execute_bash()` method:

```python
def execute_bash(self, command, timeout=30):
    """Execute a command via engineering debug bash shell (port 6022)."""
    # CURRENT: tries _execute_via_debug_ssh, then falls back to _execute_bash_via_console
    # REQUIRED: remove _execute_bash_via_console fallback entirely
    result = self._execute_via_debug_ssh(command, timeout)
    if result is not None:
        return result
    # ❌ DELETE THIS FALLBACK:
    return self._execute_bash_via_console(command, timeout)
```

After that, in `enable_engineering_debug()`:
```python
def enable_engineering_debug(self):
    # 1. _find_engineering_debug_zip() — needs /mnt/nightly/ to be accessible
    # 2. SFTP upload to device:/firmware/engineering_debug.zip
    # 3. execute("imgupd engdbg")
    # 4. wait + verify via ver -v → "Eng Debug Mode: True"
    # 5. Port 6022 should now be open
```

---

## 5. ENVIRONMENT CONTEXT

### 5.1 Python & Dependencies

```
Python: 3.8.10 (WSL Ubuntu on NJ116561LT) / 3.8.x on nj6v-docker-04
Virtual env: /home/builduser/Linux_jstr1000/nightly_testing/dsp_test_suite/.venv/

Required packages (requirements.txt):
  paramiko>=3.0.0          # SSH/SFTP
  pytest>=7.0.0            # Test framework
  pytest-html>=4.0.0       # HTML report plugin
  pytest-json-report>=1.5.0 # JSON output for dashboard
  PyYAML>=6.0              # Config parsing
  Jinja2>=3.1.0            # Report templates
  Flask>=3.0.0             # Dashboard web server
  openpyxl>=3.1.0          # Excel report export
  gunicorn>=21.2.0         # WSGI server for Flask
  requests>=2.31.0         # CresNext REST client
```

### 5.2 System-Level Requirements

- `sshpass` — available on nj6v-docker-04 (NOT on dev machine)
- `/mnt/nightly/` NFS mount — only on nj6v-docker-04
- Network access to DUT subnet `10.64.36.0/24`
- SSH key: `~/.ssh/id_ed25519` (installed to nj6v-docker-04 from dev machine)

### 5.3 Running Tests Locally

```bash
cd /home/builduser/Linux_jstr1000/nightly_testing/dsp_test_suite
source .venv/bin/activate  # if venv exists; otherwise: pip install -r requirements.txt

# Single device, quick mode (odd zones only):
pytest tests/test_volume.py tests/test_eq.py --device=DM-NAX-8ZSA --zone-mode=quick -v

# Full nightly (all devices, parallel):
python orchestrator.py --config config/test_manifest.yaml

# Specific zones:
pytest tests/test_balance.py --device=DM-NAX-8ZSA --zones=1,5,7 -v

# Override DUT IP at runtime:
pytest tests/ --device=DM-NAX-8ZSA --ip=10.64.36.64 --password=Crestron123 -v
```

### 5.4 Deployment on nj6v-docker-04

```bash
ssh nj6v-docker-04
cd /home/builduser/dsp_test_suite   # ← needs to be rsynced here
./deploy/setup_server.sh             # Creates venv, installs systemd units
systemctl start dmnax-nightly.timer  # Starts nightly 1am trigger
systemctl start dmnax-dashboard      # Starts Flask on :5050
```

### 5.5 Key Firmware Versions on DUTs

| DUT | Firmware (PUF) | DSP FW | ctrl-audio-dsp | Eng Debug |
|-----|---------------|--------|----------------|-----------|
| 8ZSA | 3.2.0005.17116 | v42 | FW v21 (Driver v4.03) | **Enabled** (True) |
| 4ZSA | 3.2.xxxx | v21 | FW v21 (Driver v4.0x) | Enabled |
| 4ZSP | 3.2.xxxx | v42 | FW v21 (Driver v4.0x) | Unknown |

---

## 6. CAVEATS & GOTCHAS — Critical Knowledge for New Agents

### The fw42 Routing Dance (Most Important)

On 8ZSA/4ZSP, getting signal to an amp output for measurement requires a precise sequence:

```
1. CresNext: AvMatrixRouting → toggle to Input02 (force route change)
2. Wait 200ms
3. CresNext: AvMatrixRouting → set to Input01 (tone input)
4. Wait 500ms (route_settle_time_s — HandleNewRoute resets volume)
5. CresNext: Set Volume=800 (re-apply after HandleNewRoute reset)
6. DSP console: dsp tone {sig_ch} 1000 -20  (start tone on correct block's sig gen)
7. DSP console: dsp mix {sig_ch} {out} 0  (MIXER_CFG_NODE — NOT mixout!)
8. Wait 1.5s (signal_settle_time_s)
9. DSP console: dsp  (read state table)
10. Parse output_db from Amp/OutA column
```

Miss any step and you get -inf at the measurement point.

### Why `dsp mixout` is Forbidden on fw42

`dsp mixout` sends `AUDIO_DSP_CMD_MIXER_CFG_CH_OUT` which:
- Re-initializes the output channel on the SHARC firmware
- Wipes any PEQ bands, Bass/Treble settings, Volume, Loudness configuration
- The zone chain must then be completely re-programmed by DspAudioCtl
- This takes the firmware several seconds and races with our next measurement

`dsp mix` sends `AUDIO_DSP_CMD_MIXER_CFG_NODE` which:
- Sets a SINGLE crosspoint gain
- Does NOT touch the output processing chain
- Safe to call at any time without corrupting zone state

### Balance Architecture Difference

```
4ZSA:  Input → Mixer → [BALANCE] → Ducker → AGC → EQ → Limiter → Amp
                         ↑ Post-mixer, each output independently balanced

8ZSA:  [BALANCE] → Input → Mixer → Ducker → AGC → EQ → Limiter → Amp
        ↑ Pre-mixer, applied to INPUT level

4ZSA test: Same tone source → both outputs. Balance attenuates each output.
8ZSA test: SEPARATE tone on L input (ch0) and R input (ch1). Balance attenuates inputs.
```

### The Parser Group(8) Fix

The fw42 output regex has 8 capture groups:
```
(1)=trim  (2)=ducker  (3)=agc  (4)=gainL  (5)=gainA  (6)=limiter  (7)=outL  (8)=outA
```
`outL` = Line-level equivalent (pre-EQ on some paths)
`outA` = Amp output (POST-EQ, post-everything) ← **THIS is output_db**

### Engineering Debug — The Only Bash Path

```
❌ `linux` command → "Your user access prevents execution" (user-level restricted)
❌ Port 6022 without imgupd engdbg → Connection refused (dropbear not running)
✅ Upload zip → imgupd engdbg → ver -v shows "Eng Debug Mode: True" → port 6022 works
```

The engineering_debug.zip is a Crestron-signed package that:
1. Installs dropbear SSH server on port 6022
2. Adds root-equivalent bash access
3. Survives reboots until firmware upgrade
4. Required for any `curl | aplay` streaming test

### Quick-Mode Zone Selection Rationale

```yaml
quick:
  DM-NAX-8ZSA: [1, 3, 5, 7]  # Odd zones only
```

Why odd only:
- Zone 1: Block 0, first zone — catches basic routing issues
- Zone 3: Block 0, non-adjacent — catches index math errors
- Zone 5: **Block 1** — catches dual-block sig gen issues (ch8 vs ch0)
- Zone 7: Block 1, non-adjacent — catches block-1 index math
- Zones 2,4: **SKIP** — firmware bug drops Bass/Treble on even zones
- Cuts runtime from ~2h to ~1h while maintaining architectural coverage

---

## 7. GIT & DEPLOYMENT STATE

```
Remote: origin → nj-github.crestron.crestron.com:CrestronEngineering/DM-NAX_test_suite.git
Branch: master (39 commits total, Apr 12 – May 6 2026)
Last push: 13bb696 (May 6 2026 17:46)
Clean: working tree clean after last commit

Related repo (streaming apps): 
  git push cres dm-nax_4zsa_rc_v3.2  (audio-streaming-services)
  ← most recent streaming-related FW branch
```

---

*End of Session State. A new agent reading this document should be able to:*
1. *Understand WHY each architectural decision was made*
2. *Know which DSP column to read and why the other is wrong*
3. *Reproduce the exact fw42 routing dance sequence*
4. *Resume work on the streaming test deployment to nj6v-docker-04*
5. *Know to NEVER use `linux` command or `dsp mixout` on fw42*
