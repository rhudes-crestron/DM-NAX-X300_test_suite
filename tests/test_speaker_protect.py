"""
Test: Speaker Protect
Category: DSP
Verifies that speaker protection settings (enable/disable, power rating,
impedance) are accepted and reflected in CresNext readback for each zone.
Follows the SpeakerProtect sheet in AP_TestCases.xlsx.

CresNext path:
  /Device/ZoneOutputs/Zones/Zone{N}/ZoneAudio/Speaker/

Properties:
  IsSpeakerProtectEnabled: bool
  Power: 10, 20, 40, 80 (watts)
  Impedance: "4ohm", "8ohm"
  IsSpeakerProtectSupported: bool (read-only)
  PowerMax: int (read-only, device-dependent)
"""
import pytest
import time


class TestSpeakerProtect:
    """Verify speaker protection configuration via CresNext REST API."""

    CATEGORY = "dsp_speaker_protect"

    def test_speaker_protect_supported(self, dsp, device_cfg, test_settings):
        """Device reports speaker protection as supported."""
        sp = dsp.cn.get_speaker_protect(1)
        assert sp.get("IsSpeakerProtectSupported") is True, (
            f"Speaker protect not supported: {sp}"
        )

    def test_speaker_protect_enable(self, dsp, device_cfg, test_settings):
        """Speaker protection can be enabled."""
        cn = dsp.cn
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=True)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(1)
        assert sp.get("IsSpeakerProtectEnabled") is True, (
            f"Speaker protect enable not reflected: {sp.get('IsSpeakerProtectEnabled')}"
        )
        # Restore
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=False)

    def test_speaker_protect_disable(self, dsp, device_cfg, test_settings):
        """Speaker protection can be disabled."""
        cn = dsp.cn
        # Enable first, then disable
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=True)
        time.sleep(0.2)
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=False)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(1)
        assert sp.get("IsSpeakerProtectEnabled") is False, (
            f"Speaker protect disable not reflected: {sp.get('IsSpeakerProtectEnabled')}"
        )

    @pytest.mark.parametrize("power", [10, 20, 40])
    def test_speaker_power_setting(self, dsp, device_cfg, test_settings, power):
        """Speaker power rating is accepted and reflected in readback."""
        cn = dsp.cn
        # Skip power values above device PowerMax
        sp = cn.get_speaker_protect(1)
        power_max = sp.get("PowerMax", 50)
        if power > power_max:
            pytest.skip(f"Power {power}W exceeds device max {power_max}W")

        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=True, Power=power)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(1)
        assert sp.get("Power") == power, (
            f"Speaker power not reflected: expected {power}, got {sp.get('Power')}"
        )
        # Restore
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=False, Power=40)

    @pytest.mark.parametrize("impedance", ["4ohm", "8ohm"])
    def test_speaker_impedance_setting(self, dsp, device_cfg, test_settings, impedance):
        """Speaker impedance is accepted and reflected in readback."""
        cn = dsp.cn
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=True, Impedance=impedance)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(1)
        assert sp.get("Impedance") == impedance, (
            f"Impedance not reflected: expected {impedance}, got {sp.get('Impedance')}"
        )
        # Restore
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=False, Impedance="8ohm")

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_speaker_protect_per_zone(self, dsp, device_cfg, test_settings, zone):
        """Speaker protection works on each zone independently."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        cn = dsp.cn
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True, Power=20)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(zone)
        assert sp.get("IsSpeakerProtectEnabled") is True
        assert sp.get("Power") == 20
        # Restore
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False, Power=40)

    def test_speaker_protect_does_not_kill_signal(self, dsp, device_cfg, test_settings):
        """Enabling speaker protection doesn't silence normal-level output."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)
        time.sleep(test_settings["signal_settle_time_s"])

        cn = dsp.cn
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=True, Power=40)
        time.sleep(0.5)

        level = dsp.measure_output_level("A1L")
        assert level > test_settings["mute_floor_db"], (
            f"Speaker protect killed signal: {level:.2f} dB"
        )
        dsp.assert_signal_presence(1, expected=True)

        # Restore
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=False)

    def test_speaker_protect_limits_output(self, dsp, device_cfg, test_settings):
        """Speaker protection at min power limits output vs. unprotected.

        Drive the signal generator at a strong level and compare output_db
        with speaker protect OFF versus ON at the lowest power setting.
        The limiter should reduce (or at minimum not increase) the output.
        """
        cn = dsp.cn

        # Drive a loud tone
        dsp.start_sig_tone(gain_db=-6)
        dsp.route_sig_to_output(0)
        dsp.set_zone_volume(1, 1000)  # Max volume
        time.sleep(test_settings["signal_settle_time_s"])

        # Measure without protection
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=False)
        time.sleep(0.5)
        level_off = dsp.measure_output_level("A1L", settle_time=0.5)

        # Enable protection at lowest power rating
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=True, Power=10, Impedance="4ohm")
        time.sleep(0.5)
        level_on = dsp.measure_output_level("A1L", settle_time=0.5)

        # The limiter should reduce or cap the output level
        assert level_on <= level_off + 1.0, (
            f"Speaker protect did not limit: OFF={level_off:.1f} dB, "
            f"ON(10W/4ohm)={level_on:.1f} dB"
        )

        # Restore
        cn.set_speaker_protect(1, IsSpeakerProtectEnabled=False, Power=40, Impedance="8ohm")
        dsp.set_zone_volume(1, 800)
        dsp.stop_sig_tone()
