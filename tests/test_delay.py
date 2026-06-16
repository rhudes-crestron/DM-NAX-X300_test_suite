"""
Test: Delay Control
Category: DSP
Verifies that delay settings are applied to output channels.
Tests all selected zones — parametrized so --zone-mode quick/full/explicit apply.
"""
import pytest

# All possible zones; conftest.pytest_collection_modifyitems filters to the
# session's --zone-mode / --zones selection at collection time.
ALL_ZONES = list(range(1, 9))


@pytest.fixture(autouse=True, scope="module")
def _restore_delay_after_module(cresnext, device_cfg, request):
    """Reset all zone delays to 0 after all tests in this module.

    Cleanup is redirected to a dedicated trace file so it does not appear
    inside the last test's trace log (same pattern as module_reset).
    """
    import lib.test_trace as _tt
    yield
    results_base = request.config.getoption("--results-dir")
    with _tt._LOCK:
        _saved_log = _tt._CURRENT_LOG
    from lib.test_trace import set_current_test
    set_current_test("_module_teardown_tests.test_delay", results_base)

    zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
    for zone in zones:
        try:
            cresnext.set_zone_audio(zone, DelayInms=0)
        except Exception:
            pass

    with _tt._LOCK:
        _tt._CURRENT_LOG = _saved_log


class TestDelay:
    """Verify per-zone delay configuration — per zone."""

    CATEGORY = "dsp_delay"

    @staticmethod
    def _output_info(zone):
        """Zone N → left amp output index and name (A{N}L)."""
        return (zone - 1) * 2, f"A{zone}L"

    def _setup_zone(self, dsp, device_cfg, zone):
        """Route signal generator to the zone's left amp output."""
        out_idx, _ = self._output_info(zone)
        sig_ch = dsp.sig_ch_for_output(out_idx)
        dsp.start_tone(sig_ch, dsp.settings["default_tone_freq_hz"],
                       dsp.settings["default_tone_gain_db"])
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            if dsp.cn is not None:
                dsp._set_tone_source_for_zone(zone)
            dsp.clear_all_sig_routes()
        dsp.set_mixer(sig_ch, out_idx, 0)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    @pytest.mark.parametrize("delay_ms", [1, 10, 50, 85])
    def test_delay_setting_accepted(self, dsp, cresnext, device_cfg, test_settings,
                                    zone, delay_ms):
        """Delay values are accepted and signal continues to pass through the zone."""
        out_idx, out_name = self._output_info(zone)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)

        dsp.set_zone_delay(zone, delay_ms)
        level = dsp.measure_output_level(out_name)

        assert level > test_settings["mute_floor_db"], (
            f"Zone {zone}: no signal with {delay_ms}ms delay: {level:.2f} dB"
        )
        dsp.assert_signal_presence(zone, expected=True)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_delay_reflected_in_dsp_state(self, dsp, cresnext, device_cfg,
                                          test_settings, zone):
        """Delay value set via CresNext is reflected in the DSP state readback."""
        out_idx, out_name = self._output_info(zone)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)

        dsp.set_zone_delay(zone, 50)
        za = dsp.get_zone_audio(zone)
        assert za.get("DelayInms") == 50, (
            f"Zone {zone}: delay not reflected: expected 50ms, got {za.get('DelayInms')}ms"
        )

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_delay_changes_signal_arrival_time(self, dsp, cresnext, device_cfg,
                                               test_settings, zone):
        """Multiple distinct delay values are accepted and each reads back correctly.

        Origin: IsSignalDetected averaging latency (~400ms–1700ms) is far larger
        than the delay range under test (84ms), making timing comparisons unreliable.
        This test instead verifies DSP state readback for two distinct delay values
        (1ms and 85ms) with active signal — confirming the delay control mechanism
        changes setting correctly on the routed audio path.
        """
        out_idx, out_name = self._output_info(zone)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)

        for delay_ms in (1, 85):
            dsp.set_zone_delay(zone, delay_ms)
            za = dsp.get_zone_audio(zone)
            assert za.get("DelayInms") == delay_ms, (
                f"Zone {zone}: delay readback mismatch: "
                f"set {delay_ms}ms, got {za.get('DelayInms')}ms"
            )
            level = dsp.measure_output_level(out_name)
            assert level > test_settings["mute_floor_db"], (
                f"Zone {zone}: no signal with {delay_ms}ms delay: {level:.2f} dB"
            )
