---
name: dsp-test-develop
description: >
  Develop new tests or modify existing tests for the DM-NAX DSP test suite.
  Activate when user mentions: new test, add test, test pattern, fixture,
  conftest, parametrize, zone measurement, DSPController, CresNextClient,
  StreamingClient, DeviceSSH, test class, test method, module_reset, dsp_tone,
  signal routing test, zone iteration, measurement tolerance.
---

# DSP Test Development Skill

## Purpose

Guides creation and modification of pytest-based DSP tests for
DM-NAX devices. Covers framework conventions, fixture usage,
measurement patterns, and zone iteration.

## Reference Documents

Read these before writing tests:

- `docs/RUNNING_TESTS.md` — how to run, CLI options, zone modes, device profiles
- `docs/test_methods_reference.html` — measurement API and class patterns
- `docs/SESSION_STATE.md` § "Repository Layout" and § "Test Pattern"

## Test File Conventions

- One file per feature: `tests/test_<feature>.py`
- One class per file: `class Test<Feature>`
- Class inherits nothing (plain pytest class)
- Methods prefixed `test_` — each is a single assertion scenario
- Use `@pytest.mark.parametrize` for zone iteration

## Standard Fixtures (from conftest.py)

| Fixture        | Scope    | Provides                                  |
|----------------|----------|-------------------------------------------|
| `device_cfg`   | session  | Dict from `config/devices.yaml` for `--device` |
| `ssh`          | session  | `DeviceSSH` instance (port 22)            |
| `eng_ssh`      | session  | `DeviceSSH` instance (port 6022, eng debug) |
| `cresnext`     | session  | `CresNextClient` (REST API)               |
| `dsp`          | session  | `DSPController` (wraps ssh + cresnext)    |
| `streaming`    | session  | `StreamingClient` (HTTP to MediaStreamer)  |
| `module_reset` | function | Resets DSP state between tests            |
| `zone_list`    | session  | List of zone numbers to test (from `--zones`) |

## Measurement Pattern

```python
class TestMyFeature:
    """Verify feature X affects output level."""

    @pytest.mark.parametrize("zone", indirect=True)
    def test_feature_changes_level(self, dsp, cresnext, zone, module_reset):
        # 1. Set up: route tone to zone
        dsp.route_tone_to_zone(zone)

        # 2. Measure baseline
        baseline_db = dsp.read_output_db(zone, channel="left")

        # 3. Apply the feature under test
        cresnext.set_zone_property(zone, "MyFeature", value)

        # 4. Measure result
        result_db = dsp.read_output_db(zone, channel="left")

        # 5. Assert with tolerance
        expected_delta = -6.0  # dB
        assert abs((result_db - baseline_db) - expected_delta) < 1.0, \
            f"Zone {zone}: expected {expected_delta} dB change, got {result_db - baseline_db:.1f}"
```

## DSPController Key Methods

```python
dsp.route_tone_to_zone(zone)          # Route sig-gen → zone via mixer
dsp.clear_all_sig_routes()            # Clear all mixer crosspoints
dsp.read_output_db(zone, channel)     # Read Amp gain (type 15) in dB
dsp.read_dsp_state(zone)              # Full DSPState dataclass
dsp.set_tone(freq_hz, amp_dbfs)       # Configure signal generator
dsp.mute_mixer_output(zone)           # Mute zone at mixer
dsp.set_mixer_output(zone, gain_db)   # Set mixer crosspoint level
dsp.get_ducker(channel)               # Ducker state dict
dsp.get_limiter(channel)              # Limiter state dict
dsp.get_agc(channel)                  # AGC state dict
```

## CresNextClient Key Methods

```python
cresnext.set_zone_volume(zone, pct)        # 0–100
cresnext.set_zone_mute(zone, muted)        # True/False
cresnext.set_zone_bass(zone, value)        # -12 to +12
cresnext.set_zone_treble(zone, value)      # -12 to +12
cresnext.set_zone_balance(zone, value)     # -20 to +20
cresnext.set_zone_loudness(zone, enabled)
cresnext.set_zone_eq(zone, band, gain_db)
cresnext.set_zone_source(zone, input_id)   # "Input01"–"Input16"
cresnext.get_zone_status(zone)             # Full zone state dict
```

## StreamingClient Key Methods

```python
streaming.start_player(zone, url, port)     # Start MediaPlayer for zone
streaming.stop_player(zone)                 # Stop playback
streaming.get_player_status(zone)           # State dict
streaming.start_media_server(url, port)     # Start server-side stream
streaming.stop_media_server(port)           # Stop server
```

## Zone/Channel Mapping Helper

```python
def zone_to_channels(zone: int) -> tuple[int, int]:
    """Return (left_ch, right_ch) global channel numbers for a zone."""
    return (zone - 1) * 2, (zone - 1) * 2 + 1
```

## Adding a New Test — Checklist

1. Create `tests/test_<feature>.py` with `class Test<Feature>`
2. Use `module_reset` fixture to ensure clean state per test
3. Parametrize over zones: `@pytest.mark.parametrize("zone", indirect=True)`
4. Route tone → measure baseline → apply change → measure → assert
5. Use tolerance of ±1.0 dB for level comparisons (±0.5 for precision tests)
6. Add the test file to `config/test_manifest.yaml` under the appropriate device
7. Run locally: `pytest tests/test_<feature>.py --device DM-NAX-8ZSA --config config/devices.yaml -v`
8. Verify in nightly by checking next day's results

## Silence Floor Constants

```python
SILENCE_FLOOR_DB = -100.0   # Below this = silence
NOISE_FLOOR_DB = -85.0      # Typical analog noise floor
TONE_PRESENT_DB = -60.0     # Above this = signal present
```
