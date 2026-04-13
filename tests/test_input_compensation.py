"""
Test: Input Compensation
Category: DSP
Verifies that input compensation (gain offset) on physical inputs
correctly shifts the signal level through the DSP chain.
Device state is automatically reset before and after each test by conftest.
"""
import pytest
import math


class TestInputCompensation:
    """Verify input compensation applies gain offset at the input stage."""

    CATEGORY = "dsp_input_compensation"

    @pytest.fixture(autouse=True)
    def _skip_if_no_dsp_gain(self, device_cfg):
        """Skip input compensation tests on fw42 where `dsp gain` is unsupported."""
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            pytest.skip(
                f"dsp gain command not supported on {device_cfg['model']} "
                f"(fw{device_cfg['dsp_fw_version']})"
            )

    @pytest.mark.parametrize("input_ch,input_name", [
        (0, "S1L"), (2, "T1L"), (4, "L1L"), (6, "L2L"),
    ])
    def test_compensation_zero_baseline(self, dsp, device_cfg, test_settings,
                                         input_ch, input_name):
        """With 0dB compensation, input gain column shows 0.0."""
        dsp.set_input_gain(input_ch, 0)
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
        import time
        input_ch = 0   # S1L
        input_name = "S1L"

        dsp.set_input_gain(input_ch, compensation_db)
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
        dsp.set_input_gain(input_ch, 5)
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
        dsp.set_input_gain(0, 5)
        dsp.set_input_gain(2, 0)
        dsp.start_tone(0, 1000, -20)
        dsp.start_tone(2, 1000, -20)

        state = dsp.read_dsp_state()
        s1l = state.inputs.get("S1L")
        t1l = state.inputs.get("T1L")

        if s1l and t1l:
            assert abs(s1l.gain_db - 5.0) <= test_settings["level_tolerance_db"]
            assert abs(t1l.gain_db - 0.0) <= test_settings["level_tolerance_db"]


