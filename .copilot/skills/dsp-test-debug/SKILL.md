---
name: dsp-test-debug
description: >
  Debug DSP test failures on the DM-NAX-8ZSA nightly test suite. Activate when
  user mentions: nightly failure, test failure, streaming cleanup, zone silence,
  -70 dB, dsp gain, ducker, limiter, ALSA residual, Zone 7, signal routing,
  results log, build server results, amp health, noise floor, crosstalk.
---

# DSP Test Debug Skill

## Purpose

Guides investigation of nightly test failures for the DM-NAX DSP test suite.
Covers how to find and interpret results on the build server, diagnose DSP
pipeline issues, check ALSA/GStreamer state, and identify common failure
patterns.

## Reference Documents

Read these for full context before debugging:

- `docs/SESSION_STATE.md` — architecture, known issues, device profiles
- `docs/audio_signal_flow_reference.html` — signal chain from input to amp output
- `docs/sample_log_with_phase_markers.log` — annotated test output

## Build Server Results Access

**ALWAYS review results on the build server, not locally.** Unless the user explicitly says "local results" or "local run", ALL result analysis must use `/opt/dmnax-test-suite/results/` on `Nj6v-docker-04`. Never read from the local workspace `results/` folder for nightly analysis.

Before running any SSH command to the build server, prompt the user:
> "Please provide the password for builduser@Nj6v-docker-04."

```bash
# Latest nightly results for DM-NAX-8ZSA
ssh builduser@Nj6v-docker-04 'ls -td /opt/dmnax-test-suite/results/*_DM-NAX-8ZSA | head -3'

# Summary: pass/fail counts
ssh builduser@Nj6v-docker-04 'grep -E "PASSED|FAILED|passed|failed" /opt/dmnax-test-suite/results/<DIR>/console.log | tail -40'

# Specific failing test log
ssh builduser@Nj6v-docker-04 'cat /opt/dmnax-test-suite/results/<DIR>/test_logs/<logfile>.log | tail -60'
```

## Running Individual Tests on the Build Server

The build server venv is at `/opt/dmnax-test-suite/venv/`. Always activate it before running pytest:

```bash
ssh builduser@Nj6v-docker-04 '
  cd /opt/dmnax-test-suite && \
  TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S") && \
  mkdir -p results/${TIMESTAMP}_manual_<label> && \
  source venv/bin/activate && \
  python3 -m pytest tests/test_streaming.py \
    --device=DM-NAX-8ZSA --config=config/devices.yaml \
    --results-dir=results/${TIMESTAMP}_manual_<label> \
    --tb=short -v 2>&1 | tee results/${TIMESTAMP}_manual_<label>/console.log
'

# Run bridging + speaker protect + streaming together
ssh builduser@Nj6v-docker-04 '
  cd /opt/dmnax-test-suite && \
  TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S") && \
  mkdir -p results/${TIMESTAMP}_manual_multi && \
  source venv/bin/activate && \
  python3 -m pytest \
    tests/test_bridging.py tests/test_speaker_protect.py tests/test_streaming.py \
    --device=DM-NAX-8ZSA --config=config/devices.yaml \
    --results-dir=results/${TIMESTAMP}_manual_multi \
    --tb=short -v 2>&1 | tee results/${TIMESTAMP}_manual_multi/console.log
'
```

> **Do NOT use** bare `pytest` or `pip3` — they resolve to the wrong Python environment and will fail with OpenSSL/paramiko import errors.

## DSP Investigation Checklist

When a zone reports unexpected level (not silence):

1. **Check which gain type contributes:**
   ```
   dsp gain <type> <channel>
   ```
   Types 0–15: PreGain(0), PostGain(1), Fader(2), Mute(3), Bass(4), Treble(5),
   Loudness(6), Ducker(7), Limiter(8), AGC(9), Chime(10), Tone(11),
   AutoMixer(12), NightMode(13), EQ(14), Amp(15/output_db)

2. **Check route source:**
   ```
   dsp route source <channel>
   ```
   Self-routed (ch N from ch N) means nothing is feeding the channel from crosspoint.

3. **Check ducker/limiter VU for activity:**
   ```
   dsp ducker <channel>   → vu_level field
   dsp limiter <channel>  → vu_level field
   ```
   Values of -341.34 dB = digital silence.

4. **Check ALSA PCM state (via engineering debug SSH port 6022):**
   ```
   cat /proc/asound/card0/pcm*p/sub0/status
   ```
   If state=RUNNING after playback stopped → pipeline leak.

5. **Check mixer crosspoints:**
   ```
   dsp mixer read <channel>
   ```
   All crosspoints should be -inf (or 0 dB for the intended route).

## Common Failure Patterns

### Pattern: Zone 7 at -70 dB after streaming stop (fw42 8ZSA)

- **Symptom:** A7L/A7R = -70.1 dB on amp output after player stopped and route cleared
- **DSP route says:** "DSP ch4 (Zone7L) is sourced from input 0" — ch12 routes from input 0
- **Ducker VU = -20 dB** (signal entering output chain); **Limiter VU = -70 dB** (after limiting)
- **ALSA loopback (card1) = all_closed**; no PIDs holding `/dev/snd`; mixer routes = none
- **Root cause:** Residual signal in FPGA input 0 / I2S hardware path — NOT a GStreamer/ALSA leak
- **New DIAG logs to check** (added 2026-05-30):
  - `zone7_active_inputs`: shows all non-silent DSP inputs — find which one has signal
  - `input0_gain`: raw gain reading of DSP input 0
  - `input0_crosspoints`: all outputs fed by input 0
  - `fpga_inp_status`: I2S clock/lock status per input block
  - `alsa_all_cards_open`: checks ALL ALSA cards (card0 = HW I2S, card1 = loopback)
  - `dsp_output_channel_count`: confirms DSP state is not truncated
- **Resolution:** Needs FPGA firmware fix — signal persists in the I2S hardware buffer

### Pattern: DSP state returns truncated output list

- **Symptom:** `dsp` command returns 11–12 lines instead of expected 16 (8ZSA, 8 zones = 16 channels)
  Missing channels: A7L, A7R (or A4L etc.) → test measures -inf and fails
- **Timing note:** These failures are **independent** — check timestamps; they can appear in
  delay/routing tests that run hours **before** streaming tests, not after
- **Root cause:** DSP firmware on 8ZSA fw42 intermittently returns partial state table
- **Diagnosis:** Check `dsp_output_channel_count` DIAG line — expect 16 lines for 8ZSA
- **Resolution:** Needs DSP firmware fix; workaround is more retries in the test framework

### Pattern: "No route to host" in streaming tests

- **Symptom:** All streaming tests fail with connection refused
- **Root cause:** Device IP changed or device rebooted mid-test
- **Diagnosis:** `ping 192.168.1.178` from build server

### Pattern: Zone passes in isolation but fails in sequence

- **Symptom:** Zone N fails only when run after Zone M
- **Root cause:** Mixer crosspoint not cleared between tests
- **Diagnosis:** Check `module_reset` fixture is running `clear_all_sig_routes()`

## DSP Channel Mapping (fw42, 8ZSA)

| Zone | Global Ch (L/R) | DSP Block | Local Ch (L/R) | Streaming Input | Port  |
|------|-----------------|-----------|----------------|-----------------|-------|
| 1    | 0 / 1           | DSP0      | 0 / 1          | Input09         | 60001 |
| 2    | 2 / 3           | DSP0      | 2 / 3          | Input10         | 60002 |
| 3    | 4 / 5           | DSP0      | 4 / 5          | Input11         | 60003 |
| 4    | 6 / 7           | DSP0      | 6 / 7          | Input12         | 60004 |
| 5    | 8 / 9           | DSP1      | 0 / 1          | Input13         | 60005 |
| 6    | 10 / 11         | DSP1      | 2 / 3          | Input14         | 60006 |
| 7    | 12 / 13         | DSP1      | 4 / 5          | Input15         | 60007 |
| 8    | 14 / 15         | DSP1      | 6 / 7          | Input16         | 60008 |

## Workflow

1. SSH to build server, find latest results directory
2. Read the failing test log (e.g., `test_streaming.log`)
3. Identify the zone, reported dB, and expected dB
4. If DSP-internal, SSH to device and walk the gain chain (types 0–15)
5. If all DSP stages show silence, check ALSA/GStreamer state
6. Document findings and recommend fix or additional logging
