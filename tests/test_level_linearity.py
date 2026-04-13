"""
Test: Level Linearity
Category: Audio Quality
═══════════════════════════════════════════════════════════════
Drives the signal generator at multiple gain levels and verifies that
the measured output tracks the input linearly — a 10 dB input increase
must produce a 10 dB output increase (within tolerance).  Non-linear
behaviour indicates compression, distortion, or clipping in the path.

Flow:
  ┌──────────┐    ┌──────────┐    ┌────────────┐    ┌───────────┐    ┌───────────┐
  │ SSH: dsp  │───▶│ SSH: dsp  │───▶│   DSP      │───▶│ SSH: dsp  │───▶│  Assert   │
  │ tone 28   │    │ mix 28→0  │    │ processing │    │ ducker_db │    │  Δ output │
  │ @var gain │    │ @ 0 dB    │    │ (linear)   │    │ (pre-vol) │    │  = Δ input│
  └──────────┘    └──────────┘    └────────────┘    └───────────┘    └───────────┘
═══════════════════════════════════════════════════════════════
"""
import math
import pytest
import logging

logger = logging.getLogger(__name__)

TONE_FREQ = 1000
OUTPUT_IDX = 0
OUTPUT_NAME = "A1L"

# Input drive levels to test linearity across dynamic range
DRIVE_LEVELS = [-60, -50, -40, -30, -20, -10, -6]

# When input changes by X dB, output should change by X ± tolerance
LINEARITY_TOLERANCE_DB = 1.0


class TestLevelLinearity:
    """Level linearity — output must track input gain changes 1:1."""

    _level_map = {}

    @pytest.mark.parametrize("drive_db", DRIVE_LEVELS)
    def test_measure_level_at(self, dsp, device_cfg, test_settings, drive_db):
        """Measure output level at {drive_db} dB input."""
        sig_ch = device_cfg["signal_generator"]["channel"]

        dsp.route_sig_to_output(OUTPUT_IDX, gain_db=0)
        dsp.start_tone(sig_ch, TONE_FREQ, drive_db)

        level = dsp.measure_mixer_level(OUTPUT_NAME)

        # Verify signal presence on the zone (before cleanup)
        dsp.assert_signal_presence(1, expected=True)

        # Cleanup
        dsp.stop_tone(sig_ch)
        dsp.clear_sig_route(OUTPUT_IDX)

        assert level > test_settings["mute_floor_db"], (
            f"No signal at drive {drive_db} dB: {level:.2f} dB"
        )

        TestLevelLinearity._level_map[drive_db] = level
        logger.info("Drive %+3d dB → output %.2f dB", drive_db, level)

    def test_linearity_check(self, dsp, device_cfg):
        """Verify output follows input linearly across all measured levels."""
        results = TestLevelLinearity._level_map
        if len(results) < 2:
            pytest.skip("Need at least 2 measurements for linearity check")

        sorted_drives = sorted(results.keys())
        failures = []

        report = "\n  Level Linearity:\n"
        report += f"  {'Drive (dB)':>10}  {'Output (dB)':>11}  "
        report += f"{'ΔDrive':>7}  {'ΔOutput':>8}  {'Error':>6}  {'Pass':>4}\n"
        report += "  " + "-" * 60 + "\n"

        prev_drive = sorted_drives[0]
        prev_level = results[prev_drive]
        report += f"  {prev_drive:>+10}  {prev_level:>11.2f}  {'(ref)':>7}  {'(ref)':>8}  {'---':>6}  {'---':>4}\n"

        for drive in sorted_drives[1:]:
            level = results[drive]
            expected_delta = drive - prev_drive
            actual_delta = level - prev_level
            error = abs(actual_delta - expected_delta)
            passed = error <= LINEARITY_TOLERANCE_DB

            report += (
                f"  {drive:>+10}  {level:>11.2f}  "
                f"{expected_delta:>+7.1f}  {actual_delta:>+8.2f}  "
                f"{error:>6.2f}  {'OK' if passed else 'FAIL':>4}\n"
            )

            if not passed:
                failures.append(
                    f"{prev_drive}→{drive} dB: expected Δ={expected_delta:.1f}, "
                    f"got Δ={actual_delta:.2f} (error={error:.2f})"
                )

            prev_drive = drive
            prev_level = level

        logger.info(report)

        assert not failures, (
            f"Non-linear output detected:\n  " + "\n  ".join(failures)
        )
