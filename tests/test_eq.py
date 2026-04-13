"""
Test: Parametric EQ (PEQ)
Category: DSP
Verifies that the 10-band parametric equaliser accepts all filter types,
gain/frequency/bandwidth values, and that zone-level and band-level EQ
bypass work correctly.  Follows the EQ-Speaker sheets in AP_TestCases.xlsx.

CresNext paths:
  Band:   /Device/ZoneOutputs/Zones/Zone{N}/ZoneAudio/Peq/Bands/Band{NN}/
  Bypass: /Device/ZoneOutputs/Zones/Zone{N}/ZoneAudio/  → IsEqBypassEnabled

Band properties: Type, Gain (-200..+200, 0.1dB), Frequency (20-20000),
                 Bandwidth (1-200, 0.01 oct), IsEqBypassEnabled (bool)
Filter types: EQ, BassShelf, TrebleShelf, HighPass, LowPass, Notch
"""
import pytest
import time

# Filter types from the spreadsheet
EQ_TYPES = ["EQ", "BassShelf", "TrebleShelf", "HighPass", "LowPass", "Notch"]

# Default band state to restore after tests
BAND_DEFAULTS = {"Type": "EQ", "Gain": 0, "Bandwidth": 33, "IsEqBypassEnabled": False}


class TestEQ:
    """Verify parametric EQ band configuration via CresNext REST API."""

    CATEGORY = "dsp_eq"

    @pytest.mark.parametrize("eq_type", EQ_TYPES)
    def test_eq_type_accepted(self, dsp, device_cfg, test_settings, eq_type):
        """Each EQ filter type is accepted and reflected in readback."""
        cn = dsp.cn
        cn.set_peq_band(1, 1, Type=eq_type)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("Type") == eq_type, (
            f"EQ type not reflected: expected {eq_type}, got {band.get('Type')}"
        )
        # Restore
        cn.set_peq_band(1, 1, Type="EQ")

    @pytest.mark.parametrize("gain", [100, -100, 200, -200, 0])
    def test_eq_gain_accepted(self, dsp, device_cfg, test_settings, gain):
        """EQ gain values are accepted and reflected in readback."""
        cn = dsp.cn
        cn.set_peq_band(1, 1, Gain=gain)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("Gain") == gain, (
            f"EQ gain not reflected: expected {gain}, got {band.get('Gain')}"
        )
        # Restore
        cn.set_peq_band(1, 1, Gain=0)

    @pytest.mark.parametrize("freq", [32, 125, 1000, 8000, 16000])
    def test_eq_frequency_accepted(self, dsp, device_cfg, test_settings, freq):
        """EQ frequency values are accepted and reflected in readback."""
        cn = dsp.cn
        cn.set_peq_band(1, 1, Frequency=freq)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("Frequency") == freq, (
            f"EQ freq not reflected: expected {freq}, got {band.get('Frequency')}"
        )
        # Restore
        cn.set_peq_band(1, 1, Frequency=32)

    @pytest.mark.parametrize("bw", [10, 33, 100, 200])
    def test_eq_bandwidth_accepted(self, dsp, device_cfg, test_settings, bw):
        """EQ bandwidth values are accepted and reflected in readback."""
        cn = dsp.cn
        cn.set_peq_band(1, 1, Bandwidth=bw)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("Bandwidth") == bw, (
            f"EQ bandwidth not reflected: expected {bw}, got {band.get('Bandwidth')}"
        )
        # Restore
        cn.set_peq_band(1, 1, Bandwidth=33)

    def test_eq_zone_bypass(self, dsp, device_cfg, test_settings):
        """Zone-level EQ bypass enables and disables correctly."""
        cn = dsp.cn
        # Enable bypass
        cn.set_zone_audio(1, IsEqBypassEnabled=True)
        time.sleep(0.3)
        za = cn.get_zone_audio(1)
        assert za.get("IsEqBypassEnabled") is True, (
            f"Zone EQ bypass enable not reflected: {za.get('IsEqBypassEnabled')}"
        )
        # Disable bypass
        cn.set_zone_audio(1, IsEqBypassEnabled=False)
        time.sleep(0.3)
        za = cn.get_zone_audio(1)
        assert za.get("IsEqBypassEnabled") is False, (
            f"Zone EQ bypass disable not reflected: {za.get('IsEqBypassEnabled')}"
        )

    def test_eq_band_bypass(self, dsp, device_cfg, test_settings):
        """Band-level EQ bypass enables and disables correctly."""
        cn = dsp.cn
        cn.set_peq_band(1, 1, IsEqBypassEnabled=True)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("IsEqBypassEnabled") is True, (
            f"Band EQ bypass enable not reflected"
        )
        cn.set_peq_band(1, 1, IsEqBypassEnabled=False)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("IsEqBypassEnabled") is False, (
            f"Band EQ bypass disable not reflected"
        )

    def test_eq_notch_with_gain(self, dsp, device_cfg, test_settings):
        """Notch filter with negative gain is accepted (AP spreadsheet Notch Test)."""
        cn = dsp.cn
        cn.set_peq_band(1, 1, Type="Notch", Gain=-100)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("Type") == "Notch", f"Type not Notch: {band.get('Type')}"
        assert band.get("Gain") == -100, f"Gain not -100: {band.get('Gain')}"
        # Restore
        cn.set_peq_band(1, 1, Type="EQ", Gain=0)

    def test_eq_peq2_custom_params(self, dsp, device_cfg, test_settings):
        """Custom PEQ parameters (Type=EQ, BW=200, Freq=200) are accepted."""
        cn = dsp.cn
        cn.set_peq_band(1, 1, Type="EQ", Bandwidth=200, Frequency=200)
        time.sleep(0.3)
        band = cn.get_peq_band(1, 1)
        assert band.get("Bandwidth") == 200
        assert band.get("Frequency") == 200
        # Restore
        cn.set_peq_band(1, 1, Bandwidth=33, Frequency=32)

    @pytest.mark.parametrize("band_num", [1, 5, 10])
    def test_eq_multi_band(self, dsp, device_cfg, test_settings, band_num):
        """Multiple EQ bands can be configured independently."""
        cn = dsp.cn
        cn.set_peq_band(1, band_num, Gain=50, Type="EQ")
        time.sleep(0.3)
        band = cn.get_peq_band(1, band_num)
        assert band.get("Gain") == 50, (
            f"Band{band_num:02d} gain not reflected: {band.get('Gain')}"
        )
        # Restore
        cn.set_peq_band(1, band_num, Gain=0)

    def test_eq_affects_output_level(self, dsp, device_cfg, test_settings):
        """Boosting EQ gain produces a measurable output level change.

        Uses a low tone gain (-40 dB) so the post-processing output stays
        well below the limiter ceiling, giving headroom for the EQ boost
        to appear in the output_db reading.
        """
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_tone(sig_ch, 1000, -40)
        dsp.route_sig_to_output(0)  # Route to A1L
        time.sleep(test_settings["signal_settle_time_s"])

        # Measure baseline
        state_before = dsp.read_dsp_state()
        level_before = state_before.outputs["A1L"].output_db

        # Apply +12dB boost at 1kHz on Band06
        cn = dsp.cn
        cn.set_peq_band(1, 6, Gain=120, Type="EQ", Frequency=1000)
        time.sleep(test_settings["signal_settle_time_s"])

        state_after = dsp.read_dsp_state()
        level_after = state_after.outputs["A1L"].output_db

        assert level_after > level_before + 3.0, (
            f"EQ +12 dB boost had insufficient effect: "
            f"before={level_before:.2f}, after={level_after:.2f}, "
            f"delta={level_after - level_before:.2f} dB (expected >3)"
        )
        dsp.assert_signal_presence(1, expected=True)

        # Restore
        cn.set_peq_band(1, 6, Gain=0)
        dsp.stop_tone(sig_ch)
