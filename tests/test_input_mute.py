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


class TestInputMute:
    """Verify per-input source mute via CresNext REST API."""

    CATEGORY = "dsp_input_mute"

    @pytest.mark.parametrize("input_num", [1, 3])
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
