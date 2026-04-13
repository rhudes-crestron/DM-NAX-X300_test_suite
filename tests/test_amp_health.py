"""
Test: Amplifier Health
Category: DSP (Hardware)
Verifies amplifier registers, fault status, and DAC health.
"""
import pytest
import re


class TestAmplifierHealth:
    """Verify amplifier hardware is healthy via register reads."""

    CATEGORY = "dsp_amp_health"

    def test_amp_no_faults(self, dsp, device_cfg):
        """Amplifier reports no fault conditions."""
        output = dsp.get_amp_faults()
        if "bad or incomplete command" in output.lower():
            pytest.skip(f"ampctrl not supported on {device_cfg['model']} (fw{device_cfg.get('dsp_fw_version', '?')})")
        # Look for fault indicators
        if "fault" in output.lower():
            # Check if any fault is active (non-zero)
            fault_values = re.findall(r"fault.*?:\s*(\d+)", output, re.IGNORECASE)
            for val in fault_values:
                assert val == "0", f"Amplifier fault detected: {output}"

    def test_amp_responds(self, dsp, device_cfg):
        """Amplifier control interface responds."""
        output = dsp.get_amp_status()
        if "bad or incomplete command" in output.lower():
            pytest.skip(f"ampctrl not supported on {device_cfg['model']} (fw{device_cfg.get('dsp_fw_version', '?')})")
        assert output.strip(), "No response from ampctrl"

    def test_dac_status(self, dsp, device_cfg):
        """DAC/ICE interface is operational."""
        output = dsp.get_dac_status()
        if "bad or incomplete command" in output.lower():
            pytest.skip(f"ampctrl not supported on {device_cfg['model']} (fw{device_cfg.get('dsp_fw_version', '?')})")
        # Just verify it responds without error
        assert "error" not in output.lower() or "no error" in output.lower(), (
            f"DAC error detected: {output}"
        )
