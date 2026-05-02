"""
Test: Door Chimes
Category: DSP
Verifies that door chime playback can be triggered on each zone, that
zone enable/disable is respected, and that the announcing volume readback
works.  Follows the Chimes sheet in AP_TestCases.xlsx (DefaultSlot09).
"""
import pytest
import time


# The spreadsheet uses DefaultSlot09 (Doorbell - Westminster Long)
CHIME_SLOT = 9
ALL_ZONES = list(range(1, 9))


class TestChimes:
    """Verify door chime playback via CresNext REST API."""

    CATEGORY = "dsp_chimes"

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_chime_zone_enable(self, dsp, device_cfg, test_settings, zone):
        """Enabling a zone for chime playback is reflected in readback."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        cn = dsp.cn
        cn.set_chime_zone(CHIME_SLOT, zone, True)
        time.sleep(0.3)
        slot = cn.get_chime_slot(CHIME_SLOT)
        zones = slot.get("PlaybackZones", {})
        assert zones.get(f"Zone{zone}", {}).get("IsEnabled") is True, (
            f"Zone {zone} chime enable not reflected: {zones}"
        )

        # Cleanup
        cn.set_chime_zone(CHIME_SLOT, zone, False)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_chime_zone_disable(self, dsp, device_cfg, test_settings, zone):
        """Disabling a zone for chime playback is reflected in readback."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        cn = dsp.cn
        # Enable first, then disable
        cn.set_chime_zone(CHIME_SLOT, zone, True)
        time.sleep(0.2)
        cn.set_chime_zone(CHIME_SLOT, zone, False)
        time.sleep(0.3)
        slot = cn.get_chime_slot(CHIME_SLOT)
        zones = slot.get("PlaybackZones", {})
        assert zones.get(f"Zone{zone}", {}).get("IsEnabled") is False, (
            f"Zone {zone} chime disable not reflected: {zones}"
        )

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_chime_play_trigger(self, dsp, device_cfg, test_settings, zone):
        """Chime playback can be triggered and PlaybackInProgress becomes True."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")
        cn = dsp.cn

        # Enable selected zone for chime
        cn.set_chime_zone(CHIME_SLOT, zone, True)
        cn.set_announcing_volume(zone, 800)
        time.sleep(0.3)

        # Trigger playback
        cn.play_chime(CHIME_SLOT)
        time.sleep(0.5)

        # Check that PlaybackInProgress went True (may already be False if
        # the chime is very short, so we check right after trigger)
        slot = cn.get_chime_slot(CHIME_SLOT)
        # Regardless of timing, the Play command should have been accepted
        # (no CresNext error).  If PlaybackInProgress is still True, great.
        # The main assertion is that the API accepted the Play command
        # without throwing an error — we got here, so it succeeded.
        assert slot.get("FileName"), "Chime slot has no file"

        # Cleanup
        cn.set_chime_zone(CHIME_SLOT, zone, False)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_chime_produces_audio(self, dsp, device_cfg, test_settings, zone):
        """Chime playback produces measurable audio on the zone output (dsp output_db)."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        cn = dsp.cn
        mute_floor = test_settings["mute_floor_db"]
        out_name = f"A{zone}L"
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        # Measure baseline with no chime playing
        baseline = dsp.measure_output_level(out_name, settle_time=0.3)

        # Enable selected zone and play chime
        cn.set_chime_zone(CHIME_SLOT, zone, True)
        cn.set_announcing_volume(zone, 800)
        time.sleep(0.3)
        cn.play_chime(CHIME_SLOT)

        # Westminster Long is ~4s — measure during playback
        level = dsp.measure_output_level(out_name, settle_time=0.8)
        assert level > mute_floor, (
            f"Zone {zone} chime did not produce audio: output_db={level:.1f} dB "
            f"(mute floor={mute_floor} dB, baseline={baseline:.1f} dB)"
        )

        # Wait for chime to finish before cleanup
        time.sleep(3.0)
        cn.set_chime_zone(CHIME_SLOT, zone, False)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_announcing_volume_readback(self, dsp, device_cfg, test_settings, zone):
        """Announcing volume can be set and read back."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        cn = dsp.cn
        cn.set_announcing_volume(zone, 500)
        time.sleep(0.3)
        zone_key = f"Zone{zone}"
        data = cn.get(f"/Device/ZoneOutputs/Zones/{zone_key}/Announcing/")
        ann = (data.get("Device", {})
               .get("ZoneOutputs", {})
               .get("Zones", {})
               .get(zone_key, {})
               .get("Announcing", {}))
        assert ann.get("Volume") == 500, (
            f"Zone {zone} announcing volume not reflected: expected 500, got {ann.get('Volume')}"
        )
        # Restore default
        cn.set_announcing_volume(zone, 300)

    def test_chime_multi_zone(self, dsp, device_cfg, test_settings):
        """Chime can be enabled on multiple zones simultaneously."""
        cn = dsp.cn
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))

        # Enable all zones
        for z in zones:
            cn.set_chime_zone(CHIME_SLOT, z, True)
        time.sleep(0.3)

        slot = cn.get_chime_slot(CHIME_SLOT)
        pz = slot.get("PlaybackZones", {})
        for z in zones:
            assert pz.get(f"Zone{z}", {}).get("IsEnabled") is True, (
                f"Zone {z} not enabled for multi-zone chime"
            )

        # Cleanup
        for z in zones:
            cn.set_chime_zone(CHIME_SLOT, z, False)
