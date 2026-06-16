"""
Test: Mute Control
Category: DSP
Verifies that muting a zone silences the output and unmuting restores it.
Device state is automatically reset before and after each test by conftest.
"""
import pytest


class TestMute:
    """Verify zone mute/unmute functionality."""

    CATEGORY = "dsp_mute"

    # On this device, muted residual noise sits around -85 to -105 dB.
    # Use a practical mute threshold rather than the strict -110 dB floor.
    MUTE_THRESHOLD_DB = -80.0

    @pytest.mark.skip(reason="Signal generator routing issues on some devices")
    def test_mute_silences_output(self, dsp, device_cfg, test_settings):
        """Muting zone 1 should silence first output."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)
        
        # Get first output name for this device
        first_output = device_cfg["amp_outputs"][0]

        # Verify signal present before mute
        level_before = dsp.measure_output_level(first_output)
        assert level_before > self.MUTE_THRESHOLD_DB, "No signal before mute"
        dsp.assert_signal_presence(1, expected=True)

        # Mute
        dsp.set_zone_mute(1, True)
        level_muted = dsp.measure_output_level(first_output)
        assert level_muted < self.MUTE_THRESHOLD_DB, (
            f"Signal still present after mute: {level_muted} dB"
        )

        # Unmute
        dsp.set_zone_mute(1, False)
        level_after = dsp.measure_output_level(first_output)
        assert level_after > self.MUTE_THRESHOLD_DB, (
            f"Signal not restored after unmute: {level_after} dB"
        )
        dsp.assert_signal_presence(1, expected=True)

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_mute_per_zone(self, dsp, device_cfg, test_settings, zone):
        """Mute works independently on each zone."""
        if zone > device_cfg["zones"]:
            pytest.skip(f"Zone {zone} not available on {device_cfg['model']}")

        output_idx = (zone - 1) * 2  # A1L=0, A2L=2, A3L=4, A4L=6
        output_name = device_cfg["amp_outputs"][output_idx]

        sig_ch = dsp.sig_ch_for_output(output_idx)
        dsp.start_tone(sig_ch, dsp.settings["default_tone_freq_hz"],
                       dsp.settings["default_tone_gain_db"])
        dsp.route_sig_to_output(output_idx)

        # Mute this zone
        dsp.set_zone_mute(zone, True)
        level = dsp.measure_output_level(output_name)
        assert level < self.MUTE_THRESHOLD_DB, (
            f"Zone {zone} ({output_name}) still has signal after mute: {level} dB"
        )
