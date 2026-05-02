"""
Test: Input Compensation
Category: DSP
Verifies that input compensation (gain offset) on physical inputs
correctly shifts the signal level through the DSP chain.
Device state is automatically reset before and after each test by conftest.
"""
import pytest
import time


class TestInputCompensation:
    """Verify input compensation applies gain offset at the input stage."""

    CATEGORY = "dsp_input_compensation"

    @staticmethod
    def _set_compensation(dsp, input_ch, compensation, settle_s=0.3):
        """Set input compensation through CresNext when available."""
        input_num = input_ch + 1
        if dsp.cn is not None:
            dsp.set_input_compensation_cresnext(input_num, compensation)
            time.sleep(settle_s)
            src = dsp.get_input_source_audio(input_num)
            assert src.get("Compensation") == compensation, (
                f"Input{input_num:02d} Compensation readback mismatch: {src}"
            )
            return

        # Legacy fallback when CresNext is unavailable in this run setup.
        dsp.set_input_gain(input_ch, compensation)

    @pytest.mark.parametrize("input_ch,input_name", [
        (0, "S1L"), (2, "T1L"), (4, "L1L"), (6, "L2L"),
    ])
    def test_compensation_zero_baseline(self, dsp, device_cfg, test_settings,
                                         input_ch, input_name):
        """With 0dB compensation, input gain column shows 0.0."""
        self._set_compensation(dsp, input_ch, 0)
        state = dsp.read_dsp_state()
        inp = state.inputs.get(input_name)
        if inp:
            assert abs(inp.gain_db) <= test_settings["level_tolerance_db"], (
                f"Gain not zero at baseline on {input_name}: {inp.gain_db}"
            )

    @pytest.mark.parametrize("compensation_db", [-10, -5, 0, 3, 5])
    def test_compensation_gain_shift(self, dsp, device_cfg, test_settings,
                                      compensation_db):
        """Input compensation shifts mixer level by the expected amount.

        We read the input channel's *gain_db* column from the DSP state
        rather than measuring the output, because the output level is
        affected by zone processing that can drift between reads.
        """
        input_ch = 0   # S1L
        input_name = "S1L"

        self._set_compensation(dsp, input_ch, compensation_db)
        dsp.start_tone(input_ch, 1000, -20)
        time.sleep(test_settings["signal_settle_time_s"])

        state = dsp.read_dsp_state()
        inp = state.inputs.get(input_name)
        assert inp, f"{input_name} not found in DSP state"

        tolerance = test_settings["level_tolerance_db"]
        assert abs(inp.gain_db - compensation_db) <= tolerance, (
            f"Compensation {compensation_db}dB: DSP gain column shows "
            f"{inp.gain_db:.2f} (expected {compensation_db})"
        )


    @pytest.mark.parametrize("input_ch,input_name", [
        (0, "S1L"), (4, "L1L"),
    ])
    def test_compensation_reflects_in_dsp_state(self, dsp, device_cfg,
                                                  test_settings,
                                                  input_ch, input_name):
        """The Gain column in DSP state reflects the compensation value."""
        self._set_compensation(dsp, input_ch, 5)
        dsp.start_tone(input_ch, 1000, -20)

        state = dsp.read_dsp_state()
        inp = state.inputs.get(input_name)
        if inp:
            assert abs(inp.gain_db - 5.0) <= test_settings["level_tolerance_db"], (
                f"Gain column should show ~5.0 on {input_name}, got {inp.gain_db}"
            )

    def test_compensation_per_input_independent(self, dsp, device_cfg, test_settings):
        """Compensation on one input does not affect another."""
        # Set +5dB on S1L, 0dB on T1L
        self._set_compensation(dsp, 0, 5)
        self._set_compensation(dsp, 2, 0)
        dsp.start_tone(0, 1000, -20)
        dsp.start_tone(2, 1000, -20)

        state = dsp.read_dsp_state()
        s1l = state.inputs.get("S1L")
        t1l = state.inputs.get("T1L")

        if s1l and t1l:
            assert abs(s1l.gain_db - 5.0) <= test_settings["level_tolerance_db"]
            assert abs(t1l.gain_db - 0.0) <= test_settings["level_tolerance_db"]

    def test_compensation_affects_audio_output_level(self, dsp, device_cfg, test_settings):
        """Input compensation must shift routed output level in the expected direction."""
        input_ch = 0
        output_idx = 0
        output_name = "A1L"

        try:
            dsp.set_mixer(input_ch, output_idx, 0)
            dsp.start_tone(input_ch, 1000, -20)

            # Baseline (0 dB compensation)
            self._set_compensation(dsp, input_ch, 0)
            base_level = dsp.measure_mixer_level(output_name)

            # Boost and cut points
            self._set_compensation(dsp, input_ch, 5)
            boost_level = dsp.measure_mixer_level(output_name)

            self._set_compensation(dsp, input_ch, -5)
            cut_level = dsp.measure_mixer_level(output_name)
        finally:
            dsp.stop_tone(input_ch)
            dsp.clear_mixer(input_ch, output_idx)

        # Verify signal exists and compensation causes clear directional changes.
        assert base_level > test_settings["mute_floor_db"], (
            f"No signal at {output_name} baseline: {base_level:.2f} dB"
        )
        assert boost_level > base_level + 2.0, (
            f"+5 dB compensation did not increase {output_name} enough: "
            f"base={base_level:.2f}dB boost={boost_level:.2f}dB"
        )
        assert cut_level < base_level - 2.0, (
            f"-5 dB compensation did not decrease {output_name} enough: "
            f"base={base_level:.2f}dB cut={cut_level:.2f}dB"
        )

        # End-to-end spread should be close to 10 dB; allow margin for metering drift.
        spread = boost_level - cut_level
        assert spread >= 7.0, (
            f"Input compensation spread too small at {output_name}: "
            f"boost-cut={spread:.2f} dB (expected >= 7 dB)"
        )


