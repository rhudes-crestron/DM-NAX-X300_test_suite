"""
Test: Input Mute
Category: DSP
Verifies that CresNext input source mute is accepted and reflected in
readback.  CresNext IsMuteEnabled operates at the zone-source layer
(AvMatrixRouting), not at the raw DSP mixer, so we verify the API
contract rather than measuring signal levels through dsp-mix paths.
"""
import pytest
import time


def pytest_generate_tests(metafunc):
    """Generate test parameters based on device physical inputs."""
    if "input_num" in metafunc.fixturenames:
        device_cfg = metafunc.config.cache.get("device_cfg", None)
        if device_cfg is None:
            import yaml
            config_path = metafunc.config.rootdir / "config" / "devices.yaml"
            with open(config_path) as f:
                all_devices = yaml.safe_load(f)
            device_name = metafunc.config.getoption("--device", default="DM-NAX-X300")
            device_cfg = all_devices["devices"].get(device_name, {})
            if "<<" in str(device_cfg):
                template_name = device_cfg.get("<<", "")
                if template_name:
                    template = all_devices["model_templates"].get(template_name, {})
                    merged = template.copy()
                    merged.update(device_cfg)
                    device_cfg = merged
            metafunc.config.cache.set("device_cfg", device_cfg)
        
        # Determine available inputs based on device
        # X300 residential: 2 inputs (Input01, Input02)
        # 8ZSA: 4 inputs (Input01-04), but test only 1 and 3
        physical_inputs = device_cfg.get("physical_inputs", {})
        num_inputs = len(physical_inputs)
        
        # For devices with 2 inputs, test [1, 2]
        # For devices with 3+ inputs, test [1, 3] (original coverage)
        if num_inputs <= 2:
            input_nums = list(range(1, num_inputs + 1))
        else:
            input_nums = [1, 3]
        
        metafunc.parametrize("input_num", input_nums)


class TestInputMute:
    """Verify per-input source mute via CresNext REST API."""

    CATEGORY = "dsp_input_mute"

    def test_input_mute_readback(self, dsp, device_cfg, test_settings, input_num):
        """Muting an input source is accepted and reflected in CresNext readback."""
        input_key = f"Input{input_num:02d}"
        uri = f"/Device/InputSources/Inputs/{input_key}/SourceAudio/"

        # Enable mute
        dsp.set_input_mute_cresnext(input_num, True)
        time.sleep(0.3)
        resp = dsp.cn.get(uri)
        val = (resp.get("Device", {})
               .get("InputSources", {})
               .get("Inputs", {})
               .get(input_key, {})
               .get("SourceAudio", {}))
        assert val.get("IsMuteEnabled") is True, (
            f"Input {input_num} mute not reflected: {val}"
        )

        # Disable mute
        dsp.set_input_mute_cresnext(input_num, False)
        time.sleep(0.3)
        resp = dsp.cn.get(uri)
        val = (resp.get("Device", {})
               .get("InputSources", {})
               .get("Inputs", {})
               .get(input_key, {})
               .get("SourceAudio", {}))
        assert val.get("IsMuteEnabled") is False, (
            f"Input {input_num} unmute not reflected: {val}"
        )
