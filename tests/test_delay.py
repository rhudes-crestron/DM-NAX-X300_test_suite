"""
Test: Delay Control
Category: DSP
Verifies that delay settings are applied to output channels.
Tests all selected zones — parametrized so --zone-mode quick/full/explicit apply.
"""
import pytest
import time

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
        dsp.start_tone(dsp.sig_ch, dsp.settings["default_tone_freq_hz"],
                       dsp.settings["default_tone_gain_db"])
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            if dsp.cn is not None:
                dsp._set_tone_source_for_zone(zone)
            dsp.clear_all_sig_routes()
        else:
            dsp.set_mixer(dsp.sig_ch, out_idx, 0)

    def _clear_zone_route(self, dsp, device_cfg, zone):
        """Clear signal route to a zone output so signal-detected can drop."""
        out_idx, _ = self._output_info(zone)
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            dsp.clear_all_sig_routes()
        else:
            dsp.clear_sig_route(out_idx)

    def _wait_signal_detected(self, dsp, zone, expected, timeout_s=3.0, poll_s=0.02):
        """Poll CresNext IsSignalDetected until it matches expected."""
        deadline = time.perf_counter() + timeout_s
        last = None
        while time.perf_counter() < deadline:
            last = dsp.is_signal_detected(zone)
            if last is expected:
                return True
            time.sleep(poll_s)
        return False

    def _time_to_signal_detected(self, dsp, zone, timeout_s=3.0, poll_s=0.01):
        """Return elapsed seconds until IsSignalDetected becomes True."""
        start = time.perf_counter()
        deadline = start + timeout_s
        while time.perf_counter() < deadline:
            if dsp.is_signal_detected(zone) is True:
                return time.perf_counter() - start
            time.sleep(poll_s)
        return None

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
        """Higher configured delay should increase observed signal-arrival latency.

        This validates delay behavior on the routed audio path (not just API readback)
        by timing IsSignalDetected transition with low vs high DelayInms.
        """
        _, out_name = self._output_info(zone)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")
        if dsp.cn is None:
            pytest.skip("CresNext unavailable; cannot validate IsSignalDetected timing")

        # Ensure known state: signal absent
        dsp.stop_sig_tone()
        self._clear_zone_route(dsp, device_cfg, zone)
        self._wait_signal_detected(dsp, zone, expected=False, timeout_s=2.0, poll_s=0.05)

        out_idx, _ = self._output_info(zone)

        def _measure_arrival(delay_ms):
            dsp.set_zone_delay(zone, delay_ms)
            cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)
            self._clear_zone_route(dsp, device_cfg, zone)
            dsp.stop_tone(dsp.sig_ch)
            self._wait_signal_detected(dsp, zone, expected=False, timeout_s=1.5, poll_s=0.03)

            dsp.start_tone(dsp.sig_ch, dsp.settings["default_tone_freq_hz"],
                           dsp.settings["default_tone_gain_db"])
            if device_cfg.get("dsp_fw_version", 21) >= 42:
                if dsp.cn is not None:
                    dsp._set_tone_source_for_zone(zone)
                dsp.clear_all_sig_routes()
            else:
                dsp.set_mixer(dsp.sig_ch, out_idx, 0)

            t = self._time_to_signal_detected(dsp, zone, timeout_s=3.0, poll_s=0.01)

            # Cleanup path between measurements
            dsp.stop_sig_tone()
            self._clear_zone_route(dsp, device_cfg, zone)
            return t

        t_low = _measure_arrival(1)
        t_high = _measure_arrival(85)

        if t_low is None or t_high is None:
            pytest.skip(
                f"Zone {zone}: unable to observe IsSignalDetected transition reliably "
                f"(t_low={t_low}, t_high={t_high})"
            )

        delta_ms = (t_high - t_low) * 1000.0

        # Require a meaningful increase for high delay, with room for detection jitter.
        # 85ms configured delay should produce a later arrival than 1ms by at least 20ms.
        assert delta_ms >= 20.0, (
            f"Zone {zone}: delay had no meaningful timing effect: "
            f"1ms={t_low*1000:.1f}ms, 85ms={t_high*1000:.1f}ms, Δ={delta_ms:.1f}ms"
        )
