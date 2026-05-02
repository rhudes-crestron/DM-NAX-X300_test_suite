"""
Test: Night Mode
Category: DSP
Verifies night mode compression levels (Off, Low, Medium, High).
Device state is automatically reset before and after each test by conftest.
"""
import pytest


class TestNightMode:
    """Verify night mode applies compression to output levels."""

    CATEGORY = "dsp_night_mode"

    @pytest.mark.parametrize("mode_name", [
        "Off", "Low", "Medium", "High",
    ])
    def test_night_mode_applies(self, dsp, device_cfg, test_settings,
                                 mode_name):
        """Each night mode setting can be applied and signal passes."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)

        dsp.set_zone_night_mode(1, mode_name)
        level = dsp.measure_output_level("A1L")

        assert level > test_settings["mute_floor_db"], (
            f"No signal with night mode {mode_name}: {level} dB"
        )
        dsp.assert_signal_presence(1, expected=True)

    def test_night_mode_reduces_dynamic_range(self, dsp, device_cfg, test_settings):
        """Higher night mode should compress (reduce) loud signals more."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_tone(sig_ch, 1000, -6)
        dsp.route_sig_to_output(0)

        levels = {}
        for mode_name in ["Off", "Low", "Medium", "High"]:
            dsp.set_zone_night_mode(1, mode_name)
            levels[mode_name] = dsp.measure_output_level("A1L")

        tol = float(test_settings["level_tolerance_db"])
        if levels["Off"] > test_settings["mute_floor_db"]:
            # Each compression level should reduce the loud signal
            for mode in ["Low", "Medium", "High"]:
                assert levels[mode] <= levels["Off"] - tol, (
                    f"Night mode {mode} ({levels[mode]:.2f}dB) did not "
                    f"compress below Off ({levels['Off']:.2f}dB)"
                )
            # Verify monotonic: High ≤ Medium ≤ Low ≤ Off
            assert levels["High"] <= levels["Medium"] + tol, (
                f"Night mode not monotonic: High={levels['High']:.2f}dB "
                f"> Medium={levels['Medium']:.2f}dB"
            )
            assert levels["Medium"] <= levels["Low"] + tol, (
                f"Night mode not monotonic: Medium={levels['Medium']:.2f}dB "
                f"> Low={levels['Low']:.2f}dB"
            )
