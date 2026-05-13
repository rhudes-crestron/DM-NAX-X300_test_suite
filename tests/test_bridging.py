"""
Test: Bridging (Zone Configuration)
Category: DSP
Verifies zone configuration and bridging-related CresNext properties.

On the DM-NAX-4ZSA, only "Standard" zone configuration is supported.
On the DM-NAX-4ZSP and 8ZSA, additional modes like Bridged, BridgedMono,
Bridged2p1 may be supported.  These tests verify that:
  - Each zone reports ZoneConfiguration="Standard"
  - SupportedZoneConfigurations always includes "Standard"
  - Each zone's stereo/mono settings are accessible
  - Audio routing works correctly in Standard mode
  - Volume control operates normally in Standard mode

Follows the Bridged-* sheets in AP_TestCases.xlsx.

CresNext paths:
  Zone:    /Device/ZoneOutputs/Zones/Zone{N}/
  Audio:   /Device/ZoneOutputs/Zones/Zone{N}/ZoneAudio/
  Routing: /Device/AvMatrixRouting/Routes/Zone{N}/
"""
import pytest
import time


class TestBridging:
    """Verify zone configuration and bridging readback via CresNext REST API."""

    CATEGORY = "dsp_bridging"

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_zone_config_standard(self, dsp, device_cfg, test_settings, zone):
        """Each zone is configured as Standard."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        data = dsp.cn.get(f"/Device/ZoneOutputs/Zones/Zone{zone}/")
        zd = (data.get("Device", {})
              .get("ZoneOutputs", {})
              .get("Zones", {})
              .get(f"Zone{zone}", {}))
        assert zd.get("ZoneConfiguration") == "Standard", (
            f"Zone {zone} config not Standard: {zd.get('ZoneConfiguration')}"
        )

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_supported_configs_include_standard(self, dsp, device_cfg, test_settings, zone):
        """Device always reports Standard as a supported zone configuration."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        data = dsp.cn.get(f"/Device/ZoneOutputs/Zones/Zone{zone}/")
        zd = (data.get("Device", {})
              .get("ZoneOutputs", {})
              .get("Zones", {})
              .get(f"Zone{zone}", {}))
        supported = zd.get("SupportedZoneConfigurations", [])
        assert "Standard" in supported, (
            f"Zone {zone}: 'Standard' not in SupportedZoneConfigurations: {supported}"
        )

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_stereo_enabled(self, dsp, device_cfg, test_settings, zone):
        """Each zone has stereo enabled in Standard mode."""
        if zone > device_cfg.get("zones", 4):
            pytest.skip(f"Zone {zone} not available")

        data = dsp.cn.get(f"/Device/ZoneOutputs/Zones/Zone{zone}/ZoneAudio/")
        za = (data.get("Device", {})
              .get("ZoneOutputs", {})
              .get("Zones", {})
              .get(f"Zone{zone}", {})
              .get("ZoneAudio", {}))
        assert za.get("IsStereoSelectionSupported") is True, (
            f"Zone {zone} stereo selection not supported"
        )

    def test_routing_accepted(self, dsp, device_cfg, test_settings):
        """Audio routing can be read for each zone in Standard mode."""
        cn = dsp.cn
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))

        for z in zones:
            zone_key = f"Zone{z}"
            try:
                route = cn.get(f"/Device/AvMatrixRouting/Routes/{zone_key}/")
                route_data = (route.get("Device", {})
                              .get("AvMatrixRouting", {})
                              .get("Routes", {}))
                assert zone_key in route_data or route_data, (
                    f"Route for {zone_key} missing from AvMatrixRouting"
                )
            except Exception as e:
                pytest.fail(f"Failed to read routing for {zone_key}: {e}")

    def test_volume_works_in_standard_mode(self, dsp, device_cfg, test_settings):
        """Volume control produces signal in Standard zone configuration."""
        dsp.set_zone_volume(1, 800)
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)
        time.sleep(test_settings["signal_settle_time_s"])

        level = dsp.measure_output_level("A1L")

        # Cleanup
        dsp.clear_sig_route(0)
        dsp.stop_sig_tone()

        assert level > test_settings["mute_floor_db"], (
            f"No signal in Standard mode at Volume=800: {level:.1f} dB"
        )
        dsp.assert_signal_presence(1, expected=True)

    def test_stereo_output_both_channels(self, dsp, device_cfg, test_settings):
        """Standard mode produces output on both L and R channels."""
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)  # A1L
        dsp.route_sig_to_output(1)  # A1R
        time.sleep(test_settings["signal_settle_time_s"])

        # Read both channels from a single DSP state snapshot to avoid false
        # failures on fw42 (8ZSA/4ZSP) where DspAudioCtl briefly shows
        # -341 dB on A1L while reprogramming the crosspoint.  Separate calls
        # can sample A1L mid-transient while A1R has already settled.
        levels = dsp.measure_output_levels_batch(["A1L", "A1R"], settle_time=0.2)
        level_l = levels["A1L"]
        level_r = levels["A1R"]
        floor = test_settings["mute_floor_db"]

        # Verify signal presence before cleanup
        dsp.assert_signal_presence(1, expected=True)

        # Cleanup
        dsp.clear_sig_route(0)
        dsp.clear_sig_route(1)
        dsp.stop_sig_tone()

        assert level_l > floor and level_r > floor, (
            f"Standard mode missing channel: L={level_l:.1f} dB, R={level_r:.1f} dB"
        )

    def test_zone_name_readable(self, dsp, device_cfg, test_settings):
        """Each zone has a readable name property."""
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
        for z in zones:
            data = dsp.cn.get(f"/Device/ZoneOutputs/Zones/Zone{z}/")
            zd = (data.get("Device", {})
                  .get("ZoneOutputs", {})
                  .get("Zones", {})
                  .get(f"Zone{z}", {}))
            name = zd.get("Name", "")
            assert isinstance(name, str) and len(name) > 0, (
                f"Zone {z} has no name: {name}"
            )
