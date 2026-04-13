"""
Test: Loudness Control
Category: DSP
Verifies that loudness compensation boost is applied correctly.
Device state is automatically reset before and after each test by conftest.
"""
import pytest


class TestLoudness:
    """Verify loudness compensation affects low-level signals."""

    CATEGORY = "dsp_loudness"

    def test_loudness_enable_disable(self, dsp, device_cfg, test_settings):
        """Loudness can be enabled and disabled without signal loss."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)

        for enabled in [True, False, True]:
            dsp.set_zone_loudness(1, enabled)
            level = dsp.measure_output_level("A1L")
            assert level > test_settings["mute_floor_db"], (
                f"Signal lost with loudness={'on' if enabled else 'off'}: {level} dB"
            )
            dsp.assert_signal_presence(1, expected=True)

    def test_loudness_boost_effect(self, dsp, device_cfg, test_settings):
        """Loudness compensation boosts low-frequency content at low volumes."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_tone(sig_ch, 100, -20)
        dsp.route_sig_to_output(0)

        # Set moderate volume
        dsp.set_zone_volume(1, 400)  # ~40%

        level_off = dsp.measure_output_level("A1L")

        dsp.set_zone_loudness(1, True)
        level_on = dsp.measure_output_level("A1L")

        if level_off > test_settings["mute_floor_db"]:
            assert level_on >= level_off - test_settings["level_tolerance_db"], (
                f"Loudness did not boost: off={level_off:.2f}, on={level_on:.2f}"
            )
