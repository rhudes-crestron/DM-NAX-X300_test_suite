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

    @staticmethod
    def _set_profile_and_assert_readback(dsp, profile_name):
        dsp.set_zone_tone_profile(1, profile_name)
        if dsp.cn is None:
            return
        zone_audio = dsp.get_zone_audio(1)
        actual = zone_audio.get("ToneProfile")
        assert actual == profile_name, (
            f"ToneProfile readback mismatch: expected={profile_name}, actual={actual}"
        )

    @pytest.mark.parametrize("profile_name", [
        "Off", "Classical", "Jazz", "Pop", "Rock", "SpokenWord",
    ])
    def test_tone_profile_applies(self, dsp, device_cfg, test_settings,
                                   profile_name):
        """Each tone profile can be set without error and signal passes."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)

        self._set_profile_and_assert_readback(dsp, profile_name)
        level = dsp.measure_output_level("A1L")

        assert level > test_settings["mute_floor_db"], (
            f"No signal with {profile_name} profile: {level} dB"
        )
        dsp.assert_signal_presence(1, expected=True)

    # SpokenWord has a subtle ~1 dB presence boost at 1 kHz and near-zero effect at
    # 200 Hz / 8 kHz.  Using the general level_tolerance_db (1.0 dB) as the assertion
    # floor puts SpokenWord right on the edge of measurement noise (±0.1–0.2 dB) and
    # causes intermittent failures.  0.75 dB is still well above noise and will still
    # catch a completely non-functional (0 dB) profile.
    _MIN_EQ_DELTA_DB = 0.75

    def test_profile_changes_eq(self, dsp, device_cfg, test_settings):
        """Each non-Off profile must measurably alter output at one or more frequencies."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        output_name = "A1L"
        output_idx = 0
        tone_gain = -20
        # 4000 Hz added to improve coverage of SpokenWord's vocal-presence range
        freqs_hz = [200, 1000, 4000, 8000]
        non_off_profiles = ["Classical", "Jazz", "Pop", "Rock", "SpokenWord"]

        try:
            dsp.route_sig_to_output(output_idx)

            off_levels = {}
            for freq in freqs_hz:
                dsp.start_tone(sig_ch, freq, tone_gain)
                self._set_profile_and_assert_readback(dsp, "Off")
                off_levels[freq] = dsp.measure_output_level(output_name)
                dsp.stop_tone(sig_ch)

            for profile in non_off_profiles:
                deltas = []
                for freq in freqs_hz:
                    dsp.start_tone(sig_ch, freq, tone_gain)
                    self._set_profile_and_assert_readback(dsp, profile)
                    profile_level = dsp.measure_output_level(output_name)
                    off_level = off_levels[freq]

                    assert off_level > test_settings["mute_floor_db"], (
                        f"No signal with Off profile at {freq}Hz: {off_level:.2f}dB"
                    )
                    assert profile_level > test_settings["mute_floor_db"], (
                        f"No signal with {profile} profile at {freq}Hz: {profile_level:.2f}dB"
                    )

                    deltas.append(abs(profile_level - off_level))
                    dsp.stop_tone(sig_ch)

                assert max(deltas) >= self._MIN_EQ_DELTA_DB, (
                    f"{profile} had no measurable EQ effect across {freqs_hz}: "
                    f"max |delta|={max(deltas):.2f}dB (need >= {self._MIN_EQ_DELTA_DB:.2f}dB)"
                )
        finally:
            self._set_profile_and_assert_readback(dsp, "Off")
            dsp.stop_tone(sig_ch)
            dsp.clear_sig_route(output_idx)
