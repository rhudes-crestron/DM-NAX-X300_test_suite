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
        output_name = device_cfg.get("amp_outputs", ["A1L"])[0]
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)

        for enabled in [True, False, True]:
            dsp.set_zone_loudness(1, enabled)
            level = dsp.measure_output_level(output_name)
            assert level > test_settings["mute_floor_db"], (
                f"Signal lost with loudness={'on' if enabled else 'off'}: {level} dB"
            )
            dsp.assert_signal_presence(1, expected=True)

    def test_loudness_boost_effect(self, dsp, device_cfg, test_settings):
        """Loudness compensation boosts low-frequency content at low volumes."""
        output_name = device_cfg.get("amp_outputs", ["A1L"])[0]
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_tone(sig_ch, 100, -20)
        dsp.route_sig_to_output(0)

        # Set moderate volume where loudness compensation is active
        dsp.set_zone_volume(1, 400)  # ~40%

        dsp.set_zone_loudness(1, False)
        level_off = dsp.measure_output_level(output_name)

        dsp.set_zone_loudness(1, True)
        level_on = dsp.measure_output_level(output_name)

        tol = float(test_settings["level_tolerance_db"])
        if level_off > test_settings["mute_floor_db"]:
            # Loudness compensation must *increase* the low-freq level
            assert level_on >= level_off + tol, (
                f"Loudness had no boost effect at 100Hz: "
                f"off={level_off:.2f}dB, on={level_on:.2f}dB (need +{tol}dB)"
            )
