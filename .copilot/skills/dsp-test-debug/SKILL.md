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

```bash
# SSH to build server
ssh builduser@Nj6v-docker-04

# Latest results
ls -lt /opt/dmnax-test-suite/results/ | head -10

# Today's streaming log
cat /opt/dmnax-test-suite/results/$(ls /opt/dmnax-test-suite/results/ | sort -r | head -1)/test_streaming.log
```

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

### Pattern: Zone at -70 dB after streaming stop

- **Symptom:** Zone reports -70.1 dB on Amp (type 15) after player stopped
- **DSP internals show silence:** All gain types 0–14 show 0 dB, ducker/limiter VU = -341.34
- **Root cause:** ALSA/GStreamer PCM device not fully closed on I2S bus
- **Diagnosis:** Check `/proc/asound/card0/pcm*p/sub0/status` — expect CLOSED, not RUNNING
- **Resolution:** Needs application-level fix in MediaStreamer/AudioPlayer pipeline teardown

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
