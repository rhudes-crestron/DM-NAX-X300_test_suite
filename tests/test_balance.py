"""
Test: Balance Control
Category: DSP
Verifies that balance control correctly attenuates left or right channels.
Tests all selected zones — parametrized the same way as test_eq.py so that
--zone-mode quick/full/explicit all apply.
"""
import pytest
import time

# All possible zones; conftest.pytest_collection_modifyitems filters to the
# session's --zone-mode / --zones selection at collection time.
ALL_ZONES = list(range(1, 9))


@pytest.fixture(autouse=True, scope="module")
def _restore_balance_after_module(cresnext, device_cfg, request):
    """Reset all zone balances to centre (0) after all balance tests complete.

    Cleanup is redirected to a dedicated trace file so it does not appear
    inside the last test's trace log (same pattern as module_reset).
    """
    import lib.test_trace as _tt
    yield
    results_base = request.config.getoption("--results-dir")
    with _tt._LOCK:
        _saved_log = _tt._CURRENT_LOG
    from lib.test_trace import set_current_test
    set_current_test("_module_teardown_tests.test_balance", results_base)

    zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
    for zone in zones:
        try:
            cresnext.set_zone_audio(zone, Balance=0)
        except Exception:
            pass

    with _tt._LOCK:
        _tt._CURRENT_LOG = _saved_log


class TestBalance:
    """Verify zone balance adjusts left/right channel levels — per zone."""

    CATEGORY = "dsp_balance"

    @staticmethod
    def _output_info(zone):
        """Map zone number to (left_idx, right_idx, left_name, right_name).

        Zone N → A{N}L / A{N}R → DSP output channels (N-1)*2 and (N-1)*2+1.
        """
        left_idx = (zone - 1) * 2
        return left_idx, left_idx + 1, f"A{zone}L", f"A{zone}R"

    def _setup_zone(self, dsp, device_cfg, zone):
        """Route signal generator to the zone's L+R amp outputs.

        fw42 Balance architecture:
          Balance is applied to each INPUT channel's level BEFORE the mixer.
          If we route ch0→out0 AND ch0→out1 (same source to both), Balance
          on ch1 is irrelevant (ch1 has no signal).  To make Balance testable,
          we start a tone on BOTH the L and R input channels and route each
          to its own output: chN→outN, chN+1→outN+1.  Then Balance=-500
          attenuates the R input level to -inf, silencing the R output.

        fw21: tone on dsp.sig_ch (ch28=SIG), mixer routes to both L and R outputs.
              Balance on fw21 is applied in the output zone chain (post-mixer).
        """
        left_idx, right_idx, _, _ = self._output_info(zone)
        sig_ch = dsp.sig_ch_for_output(left_idx)

        if device_cfg.get("dsp_fw_version", 21) >= 42:
            # Start tone on BOTH L and R input channels for this zone
            dsp.start_tone(left_idx, dsp.settings["default_tone_freq_hz"],
                           dsp.settings["default_tone_gain_db"])
            dsp.start_tone(right_idx, dsp.settings["default_tone_freq_hz"],
                           dsp.settings["default_tone_gain_db"])
            if dsp.cn is not None:
                dsp._set_tone_source_for_zone(zone)
            dsp.clear_all_sig_routes()
            # Route each input to its own output (1:1 mapping)
            dsp.set_mixer(left_idx, left_idx, 0)
            dsp.set_mixer(right_idx, right_idx, 0)
        else:
            dsp.start_tone(sig_ch, dsp.settings["default_tone_freq_hz"],
                           dsp.settings["default_tone_gain_db"])
            dsp.set_mixer(sig_ch, left_idx, 0)
            dsp.set_mixer(sig_ch, right_idx, 0)

    def _measure_lr(self, dsp, zone, settle_s):
        """Read L/R output levels for the zone from a single DSP snapshot."""
        time.sleep(settle_s)
        _, _, left_name, right_name = self._output_info(zone)
        state = dsp.read_dsp_state()
        out_l = state.outputs.get(left_name)
        out_r = state.outputs.get(right_name)
        assert out_l and out_r, f"{left_name}/{right_name} outputs not found in DSP state"
        return out_l.output_db, out_r.output_db

    def _assert_balance_direction(self, dsp, zone, test_settings, prefer_left):
        """Poll until balance direction is reflected in the DSP outputs."""
        settle = float(test_settings["signal_settle_time_s"])
        mute_floor = float(test_settings["mute_floor_db"])
        margin_db = 2.0

        deadline = time.time() + 6.0
        last_l = float("-inf")
        last_r = float("-inf")
        while time.time() < deadline:
            level_l, level_r = self._measure_lr(dsp, zone, settle)
            last_l, last_r = level_l, level_r
            if prefer_left:
                if (level_l > mute_floor) and (level_l >= level_r + margin_db):
                    return
            else:
                if (level_r > mute_floor) and (level_r >= level_l + margin_db):
                    return

        _, _, left_name, right_name = self._output_info(zone)
        direction = "left" if prefer_left else "right"
        raise AssertionError(
            f"Zone {zone} balance {direction} not reflected: "
            f"{left_name}={last_l:.2f} dB, {right_name}={last_r:.2f} dB"
        )

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_balance_center(self, dsp, cresnext, device_cfg, test_settings, zone):
        """At center balance (0), both L and R outputs have equal level."""
        _, _, left_name, right_name = self._output_info(zone)
        if left_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{left_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)

        time.sleep(test_settings["signal_settle_time_s"])
        level_l, level_r = self._measure_lr(dsp, zone, 0)

        assert level_l > test_settings["mute_floor_db"], f"No signal at {left_name}"
        diff = abs(level_l - level_r)
        assert diff <= test_settings["level_tolerance_db"] * 3, (
            f"Zone {zone} L/R imbalance at center: "
            f"{left_name}={level_l:.2f}, {right_name}={level_r:.2f}, diff={diff:.2f}"
        )
        dsp.assert_signal_presence(zone, expected=True)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_balance_full_left(self, dsp, cresnext, device_cfg, test_settings, zone):
        """Full left balance (-500) attenuates the right channel."""
        _, _, left_name, _ = self._output_info(zone)
        if left_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{left_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)
        dsp.set_zone_balance(zone, -500)
        self._assert_balance_direction(dsp, zone, test_settings, prefer_left=True)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    def test_balance_full_right(self, dsp, cresnext, device_cfg, test_settings, zone):
        """Full right balance (+500) attenuates the left channel."""
        _, _, left_name, _ = self._output_info(zone)
        if left_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{left_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)
        dsp.set_zone_balance(zone, 500)
        self._assert_balance_direction(dsp, zone, test_settings, prefer_left=False)
