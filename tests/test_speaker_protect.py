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


# All possible zones; conftest.pytest_collection_modifyitems filters to the
# session's --zone-mode / --zones selection at collection time.
ALL_ZONES = list(range(1, 9))


class TestSpeakerProtect:
    """Verify speaker protection configuration via CresNext REST API."""

    CATEGORY = "dsp_speaker_protect"

    @staticmethod
    def _output_info(zone, device_cfg):
        """Get output index and name for a zone.
        
        Handles both stereo naming (A1L/A2L for zones 1,2) and 
        mono naming (A1/A3 for zones 1,2).
        """
        amp_outputs = device_cfg.get("amp_outputs", [])
        out_name_stereo = f"A{zone}L"
        
        # For mono naming: zone 1 = A1/A2, zone 2 = A3/A4
        out_name_mono = f"A{(zone-1)*2 + 1}"
        
        # Determine which naming scheme is in use
        if out_name_stereo in amp_outputs:
            return (zone - 1) * 2, out_name_stereo
        elif out_name_mono in amp_outputs:
            return (zone - 1) * 2, out_name_mono
        else:
            # Fallback to stereo for backwards compatibility
            return (zone - 1) * 2, out_name_stereo

    @staticmethod
    def _require_zone(device_cfg, zone):
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")
        
        # Handle both stereo naming (A1L/A1R) and mono naming (A1/A2)
        amp_outputs = device_cfg.get("amp_outputs", [])
        out_name_stereo = f"A{zone}L"
        
        # For mono naming: zone 1 = A1/A2, zone 2 = A3/A4, etc.
        out_name_mono = f"A{(zone-1)*2 + 1}"
        
        # Check if either stereo or mono naming exists
        if out_name_stereo not in amp_outputs and out_name_mono not in amp_outputs:
            pytest.skip(f"Zone {zone} output not available on {device_cfg['model']}")

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_speaker_protect_supported(self, dsp, device_cfg, test_settings, zone):
        """Device reports speaker protection as supported."""
        self._require_zone(device_cfg, zone)
        sp = dsp.cn.get_speaker_protect(zone)
        assert sp.get("IsSpeakerProtectSupported") is True, (
            f"Zone {zone} speaker protect not supported: {sp}"
        )

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_speaker_protect_enable(self, dsp, device_cfg, test_settings, zone):
        """Speaker protection can be enabled."""
        self._require_zone(device_cfg, zone)
        cn = dsp.cn
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(zone)
        assert sp.get("IsSpeakerProtectEnabled") is True, (
            f"Zone {zone} speaker protect enable not reflected: {sp.get('IsSpeakerProtectEnabled')}"
        )
        # Restore
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_speaker_protect_disable(self, dsp, device_cfg, test_settings, zone):
        """Speaker protection can be disabled."""
        self._require_zone(device_cfg, zone)
        cn = dsp.cn
        # Enable first, then disable
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True)
        time.sleep(0.2)
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(zone)
        assert sp.get("IsSpeakerProtectEnabled") is False, (
            f"Zone {zone} speaker protect disable not reflected: {sp.get('IsSpeakerProtectEnabled')}"
        )

    @pytest.mark.parametrize("zone", ALL_ZONES)
    @pytest.mark.parametrize("power", [10, 20, 40])
    def test_speaker_power_setting(self, dsp, device_cfg, test_settings, zone, power):
        """Speaker power rating is accepted and reflected in readback."""
        self._require_zone(device_cfg, zone)
        cn = dsp.cn
        # Skip power values above device PowerMax
        sp = cn.get_speaker_protect(zone)
        power_max = sp.get("PowerMax", 50)
        if power > power_max:
            pytest.skip(f"Power {power}W exceeds device max {power_max}W")

        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True, Power=power)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(zone)
        assert sp.get("Power") == power, (
            f"Zone {zone} speaker power not reflected: expected {power}, got {sp.get('Power')}"
        )
        # Restore
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False, Power=40)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    @pytest.mark.parametrize("impedance", ["4ohm", "8ohm"])
    def test_speaker_impedance_setting(self, dsp, device_cfg, test_settings, zone, impedance):
        """Speaker impedance is accepted and reflected in readback."""
        self._require_zone(device_cfg, zone)
        cn = dsp.cn
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True, Impedance=impedance)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(zone)
        assert sp.get("Impedance") == impedance, (
            f"Zone {zone} impedance not reflected: expected {impedance}, got {sp.get('Impedance')}"
        )
        # Restore
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False, Impedance="8ohm")

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_speaker_protect_per_zone(self, dsp, device_cfg, test_settings, zone):
        """Speaker protection works on each zone independently."""
        self._require_zone(device_cfg, zone)

        cn = dsp.cn
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True, Power=20)
        time.sleep(0.3)
        sp = cn.get_speaker_protect(zone)
        assert sp.get("IsSpeakerProtectEnabled") is True
        assert sp.get("Power") == 20
        # Restore
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False, Power=40)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_speaker_protect_does_not_kill_signal(self, dsp, device_cfg, test_settings, zone):
        """Enabling speaker protection doesn't silence normal-level output."""
        self._require_zone(device_cfg, zone)
        out_idx, out_name = self._output_info(zone, device_cfg)

        dsp.start_sig_tone()
        dsp.route_sig_to_output(out_idx)
        # On fw42, route_sig_to_output triggers HandleNewRoute which resets
        # zone volume to ~30%.  Restore before measuring.
        dsp.set_zone_volume(zone, 800)
        time.sleep(test_settings["signal_settle_time_s"])

        cn = dsp.cn
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True, Power=40)
        time.sleep(0.5)

        level = dsp.measure_output_level(out_name)
        assert level > test_settings["mute_floor_db"], (
            f"Zone {zone} speaker protect killed signal at {out_name}: {level:.2f} dB"
        )
        dsp.assert_signal_presence(zone, expected=True)

        # Restore
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_speaker_protect_limits_output(self, dsp, device_cfg, test_settings, zone):
        """Speaker protection at min power limits output vs. unprotected.

        Drive the signal generator at a strong level and compare output_db
        with speaker protect OFF versus ON at the lowest power setting.
        The limiter should reduce (or at minimum not increase) the output.
        """
        self._require_zone(device_cfg, zone)
        cn = dsp.cn
        out_idx, out_name = self._output_info(zone, device_cfg)

        # Drive a loud tone
        dsp.start_sig_tone(gain_db=-6)
        dsp.route_sig_to_output(out_idx)
        dsp.set_zone_volume(zone, 1000)  # Max volume
        time.sleep(test_settings["signal_settle_time_s"])

        # Measure without protection
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False)
        time.sleep(0.5)
        level_off = dsp.measure_output_level(out_name, settle_time=0.5)

        # Enable protection at lowest power rating
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=True, Power=10, Impedance="4ohm")
        time.sleep(0.5)
        level_on = dsp.measure_output_level(out_name, settle_time=0.5)
        sp_on = cn.get_speaker_protect(zone)
        assert sp_on.get("IsSpeakerProtectEnabled") is True, f"Zone {zone}: protect not enabled"
        assert sp_on.get("Power") == 10, f"Zone {zone}: protect power not latched: {sp_on}"
        assert sp_on.get("Impedance") == "4ohm", f"Zone {zone}: protect impedance not latched: {sp_on}"

        # The limiter at min power (10W/4ohm) must actually reduce the level
        tol = float(test_settings["level_tolerance_db"])
        assert level_on <= level_off - tol, (
            f"Zone {zone}: speaker protect did not limit {out_name}: "
            f"OFF={level_off:.1f}dB, ON(10W/4ohm)={level_on:.1f}dB "
            f"(expected >={tol}dB reduction)"
        )

        # Disable and verify level recovers toward OFF reference.
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False, Power=40, Impedance="8ohm")
        time.sleep(0.5)
        level_restored = dsp.measure_output_level(out_name, settle_time=0.5)
        assert level_restored >= level_on + tol, (
            f"Zone {zone}: output did not recover after disabling protect: "
            f"ON={level_on:.1f}dB, restored={level_restored:.1f}dB"
        )

        # Restore
        cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False, Power=40, Impedance="8ohm")
        dsp.set_zone_volume(zone, 800)
        dsp.stop_sig_tone()
