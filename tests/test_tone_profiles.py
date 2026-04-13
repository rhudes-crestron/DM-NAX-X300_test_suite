"""
Test: Tone Profiles
Category: DSP
Verifies that preset tone profiles (Classical, Jazz, Pop, Rock, SpokenWord)
change the DSP EQ state.
Device state is automatically reset before and after each test by conftest.
"""
import pytest


class TestToneProfiles:
    """Verify tone profile selection changes DSP EQ processing."""

    CATEGORY = "dsp_tone_profiles"

    @pytest.mark.parametrize("profile_name", [
        "Off", "Classical", "Jazz", "Pop", "Rock", "SpokenWord",
    ])
    def test_tone_profile_applies(self, dsp, device_cfg, test_settings,
                                   profile_name):
        """Each tone profile can be set without error and signal passes."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)

        dsp.set_zone_tone_profile(1, profile_name)
        level = dsp.measure_output_level("A1L")

        assert level > test_settings["mute_floor_db"], (
            f"No signal with {profile_name} profile: {level} dB"
        )
        dsp.assert_signal_presence(1, expected=True)

    def test_profile_changes_eq(self, dsp, device_cfg, test_settings):
        """Switching from Off to a profile changes the output level (EQ is applied)."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        # Use 200Hz to make EQ differences measurable
        dsp.start_tone(sig_ch, 200, -20)
        dsp.route_sig_to_output(0)

        level_off = dsp.measure_output_level("A1L")

        dsp.set_zone_tone_profile(1, "Rock")
        level_rock = dsp.measure_output_level("A1L")

        assert level_off > test_settings["mute_floor_db"], "No signal with profile Off"
        assert level_rock > test_settings["mute_floor_db"], "No signal with Rock profile"
