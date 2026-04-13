"""
Test: Delay Control
Category: DSP
Verifies that delay settings are applied to output channels.
Device state is automatically reset before and after each test by conftest.
"""
import pytest


class TestDelay:
    """Verify per-zone delay configuration."""

    CATEGORY = "dsp_delay"

    @pytest.mark.parametrize("delay_ms", [1, 10, 50, 85])
    def test_delay_setting_accepted(self, dsp, device_cfg, test_settings, delay_ms):
        """Delay values are accepted and signal continues to pass."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)

        dsp.set_zone_delay(1, delay_ms)
        level = dsp.measure_output_level("A1L")

        assert level > test_settings["mute_floor_db"], (
            f"No signal with {delay_ms}ms delay: {level} dB"
        )
        dsp.assert_signal_presence(1, expected=True)

    def test_delay_reflected_in_dsp_state(self, dsp, device_cfg, test_settings):
        """Delay value appears in the CresNext readback."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)

        dsp.set_zone_delay(1, 50)
        za = dsp.get_zone_audio(1)
        assert za.get("DelayInms") == 50, (
            f"Delay not reflected: expected 50ms, got {za.get('DelayInms')}ms"
        )
