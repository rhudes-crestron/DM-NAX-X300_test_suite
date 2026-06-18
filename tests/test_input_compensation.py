"""
Test: Input Compensation
Category: DSP
Verifies that input compensation (gain offset) on physical inputs
correctly shifts the signal level through the DSP chain.
Device state is automatically reset before and after each test by conftest.
"""
import pytest
import time


def pytest_generate_tests(metafunc):
    """Dynamically parametrize tests based on device physical inputs."""
    if "input_ch" in metafunc.fixturenames and "input_name" in metafunc.fixturenames:
        device_cfg = metafunc.config.cache.get("device_cfg", None)
        if not device_cfg:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent / "config" / "devices.yaml"
            with open(cfg_path, "r", encoding="utf-8") as f:
                all_devs = yaml.safe_load(f)
            device_name = metafunc.config.getoption("--device", "DM-NAX-X300")
            device_cfg = all_devs.get(device_name, {})
            metafunc.config.cache.set("device_cfg", device_cfg)
        
        # Extract first channel from each physical input for testing
        physical_inputs = device_cfg.get("physical_inputs", {})
        input_params = []
        for input_key, input_data in physical_inputs.items():
            channels = input_data.get("channels", [])
            indices = input_data.get("index", [])
            if channels and indices:
                # Use first channel (left channel) of each input
                # Store (input_key, indices[0], channels[0]) tuple
                input_params.append((input_key, indices[0], channels[0]))
        
        if input_params:
            # Parameters: input_key (e.g., "Input01", "S1"), input_ch (DSP channel), input_name (DSP state key)
            metafunc.parametrize("input_key,input_ch,input_name", input_params)


class TestInputCompensation:
    """Verify input compensation applies gain offset at the input stage."""

    CATEGORY = "dsp_input_compensation"

    @staticmethod
    def _get_first_inputs(device_cfg, count=2):
        """Get first N input keys, channels, and names from device config."""
        physical_inputs = device_cfg.get("physical_inputs", {})
        inputs = []
        for input_key, input_data in physical_inputs.items():
            channels = input_data.get("channels", [])
            indices = input_data.get("index", [])
            if channels and indices:
                # Return (input_key, input_ch, input_name) tuple
                inputs.append((input_key, indices[0], channels[0]))
            if len(inputs) >= count:
                break
        return inputs

    @staticmethod
    def _set_compensation(dsp, input_key, input_ch, compensation, settle_s=0.3):
        """Set input compensation through CresNext when available.
        
        Args:
            input_key: Input identifier (e.g., "Input01", "S1") from device config
            input_ch: DSP channel index (for legacy fallback)
            compensation: Compensation value in dB
        """
        if dsp.cn is not None:
            # For X300: input_key = "Input01", "Input02"
            # For 8ZSA: input_key = "S1", "T1", "L1", "L2"  
            # Try to extract input number from key
            import re
            match = re.search(r'(\d+)', input_key)
            if match:
                input_num = int(match.group(1))
            else:
                # For non-numbered keys like "S1", "T1", use channel-based fallback
                input_num = input_ch + 1
            
            # CresNext API expects compensation in 0.1 dB steps (range -100..100)
            # So multiply dB value by 10: e.g., 5 dB -> 50, -10 dB -> -100
            compensation_api = int(compensation * 10)
            dsp.set_input_compensation_cresnext(input_num, compensation_api)
            time.sleep(settle_s)
            src = dsp.get_input_source_audio(input_num)
            assert src.get("Compensation") == compensation_api, (
                f"Input{input_num:02d} Compensation readback mismatch: {src}"
            )
            return

        # Legacy fallback when CresNext is unavailable in this run setup.
        dsp.set_input_gain(input_ch, compensation)

    def test_compensation_zero_baseline(self, dsp, device_cfg, test_settings,
                                         input_key, input_ch, input_name):
        """With 0dB compensation, input gain column shows 0.0."""
        self._set_compensation(dsp, input_key, input_ch, 0)
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
        inputs = self._get_first_inputs(device_cfg, 1)
        if not inputs:
            pytest.skip("No physical inputs configured")
        input_key, input_ch, input_name = inputs[0]

        self._set_compensation(dsp, input_key, input_ch, compensation_db)
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

    def test_compensation_reflects_in_dsp_state(self, dsp, device_cfg,
                                                  test_settings,
                                                  input_key, input_ch, input_name):
        """The Gain column in DSP state reflects the compensation value."""
        self._set_compensation(dsp, input_key, input_ch, 5)
        dsp.start_tone(input_ch, 1000, -20)

        state = dsp.read_dsp_state()
        inp = state.inputs.get(input_name)
        if inp:
            assert abs(inp.gain_db - 5.0) <= test_settings["level_tolerance_db"], (
                f"Gain column should show ~5.0 on {input_name}, got {inp.gain_db}"
            )

    def test_compensation_per_input_independent(self, dsp, device_cfg, test_settings):
        """Compensation on one input does not affect another."""
        inputs = self._get_first_inputs(device_cfg, 2)
        if len(inputs) < 2:
            pytest.skip("Need at least 2 inputs for independence test")
        
        input1_key, input1_ch, input1_name = inputs[0]
        input2_key, input2_ch, input2_name = inputs[1]
        
        # Set +5dB on first input, 0dB on second input
        self._set_compensation(dsp, input1_key, input1_ch, 5)
        self._set_compensation(dsp, input2_key, input2_ch, 0)
        dsp.start_tone(input1_ch, 1000, -20)
        dsp.start_tone(input2_ch, 1000, -20)

        state = dsp.read_dsp_state()
        inp1 = state.inputs.get(input1_name)
        inp2 = state.inputs.get(input2_name)

        if inp1 and inp2:
            assert abs(inp1.gain_db - 5.0) <= test_settings["level_tolerance_db"]
            assert abs(inp2.gain_db - 0.0) <= test_settings["level_tolerance_db"]

    def test_compensation_affects_audio_output_level(self, dsp, device_cfg, test_settings):
        """Input compensation must shift routed output level in the expected direction."""
        inputs = self._get_first_inputs(device_cfg, 1)
        if not inputs:
            pytest.skip("No physical inputs configured")
        input_key, input_ch, _ = inputs[0]
        
        output_idx = 0
        output_name = device_cfg.get("amp_outputs", ["A1L"])[output_idx]

        try:
            dsp.set_mixer(input_ch, output_idx, 0)
            dsp.start_tone(input_ch, 1000, -20)

            # Baseline (0 dB compensation)
            self._set_compensation(dsp, input_key, input_ch, 0)
            base_level = dsp.measure_mixer_level(output_name)

            # Boost and cut points
            self._set_compensation(dsp, input_key, input_ch, 5)
            boost_level = dsp.measure_mixer_level(output_name)

            self._set_compensation(dsp, input_key, input_ch, -5)
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


