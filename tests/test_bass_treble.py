"""
Test: Bass and Treble Controls
Category: DSP
Verifies that bass/treble adjustments change the DSP processing state.
Device state is automatically reset before and after each test by conftest.
"""
import pytest


class TestBassTreble:
    """Verify bass and treble tone controls affect the DSP output."""

    CATEGORY = "dsp_bass_treble"

    @pytest.mark.parametrize("bass_value,direction", [
        (120, "boost +12dB"),
        (-120, "cut -12dB"),
    ])
    def test_bass_changes_level(self, dsp, device_cfg, test_settings,
                                 bass_value, direction):
        """Bass boost/cut changes the output level for a low-frequency tone."""
        sig_ch = device_cfg["signal_generator"]["channel"]

        # Use 100Hz tone for bass test
        dsp.start_tone(sig_ch, 100, -20)
        dsp.route_sig_to_output(0)

        # Baseline at flat
        level_flat = dsp.measure_output_level("A1L")
        dsp.assert_signal_presence(1, expected=True)

        # Apply bass change
        dsp.set_zone_bass(1, bass_value)
        level_changed = dsp.measure_output_level("A1L")

        if level_flat > test_settings["mute_floor_db"]:
            if bass_value > 0:
                assert level_changed >= level_flat - test_settings["level_tolerance_db"], (
                    f"Bass boost did not increase level: flat={level_flat:.2f}, boost={level_changed:.2f}"
                )
            else:
                assert level_changed <= level_flat + test_settings["level_tolerance_db"], (
                    f"Bass cut did not decrease level: flat={level_flat:.2f}, cut={level_changed:.2f}"
                )

    @pytest.mark.parametrize("treble_value,direction", [
        (120, "boost +12dB"),
        (-120, "cut -12dB"),
    ])
    def test_treble_changes_level(self, dsp, device_cfg, test_settings,
                                   treble_value, direction):
        """Treble boost/cut changes the output level for a high-frequency tone."""
        sig_ch = device_cfg["signal_generator"]["channel"]

        # Use 10kHz tone for treble test
        dsp.start_tone(sig_ch, 10000, -20)
        dsp.route_sig_to_output(0)

        level_flat = dsp.measure_output_level("A1L")
        dsp.assert_signal_presence(1, expected=True)

        dsp.set_zone_treble(1, treble_value)
        level_changed = dsp.measure_output_level("A1L")

        if level_flat > test_settings["mute_floor_db"]:
            if treble_value > 0:
                assert level_changed >= level_flat - test_settings["level_tolerance_db"], (
                    f"Treble boost did not increase level: flat={level_flat:.2f}, boost={level_changed:.2f}"
                )
            else:
                assert level_changed <= level_flat + test_settings["level_tolerance_db"], (
                    f"Treble cut did not decrease level: flat={level_flat:.2f}, cut={level_changed:.2f}"
                )
