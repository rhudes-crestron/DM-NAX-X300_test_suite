"""
Test: Bass and Treble Controls
Category: DSP
Verifies that bass/treble adjustments change the DSP output level.
Tests all selected zones — parametrized so --zone-mode quick/full/explicit apply.
"""
import pytest

# All possible zones; conftest.pytest_collection_modifyitems filters to the
# session's --zone-mode / --zones selection at collection time.
ALL_ZONES = list(range(1, 9))


@pytest.fixture(autouse=True, scope="module")
def _restore_bass_treble_after_module(cresnext, device_cfg, request):
    """Reset all zone bass and treble to 0 after all tests in this module.

    Cleanup is redirected to a dedicated trace file so it does not appear
    inside the last test's trace log (same pattern as module_reset).
    """
    import lib.test_trace as _tt
    yield
    results_base = request.config.getoption("--results-dir")
    with _tt._LOCK:
        _saved_log = _tt._CURRENT_LOG
    from lib.test_trace import set_current_test
    set_current_test("_module_teardown_tests.test_bass_treble", results_base)

    zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
    for zone in zones:
        try:
            cresnext.set_zone_audio(zone, Bass=0, Treble=0)
        except Exception:
            pass

    with _tt._LOCK:
        _tt._CURRENT_LOG = _saved_log


class TestBassTreble:
    """Verify bass and treble tone controls affect the DSP output — per zone."""

    CATEGORY = "dsp_bass_treble"

    @staticmethod
    def _output_info(zone):
        """Zone N → left amp output index and name (A{N}L)."""
        return (zone - 1) * 2, f"A{zone}L"

    def _setup_zone(self, dsp, device_cfg, zone, freq_hz):
        """Route signal tone to the zone's left amp output.

        fw42: tone on dsp.sig_ch (ch0=T1L=Input01), routed via AvMatrixRouting
              through the full zone chain. No dsp mix (it bypasses zone chain).
        fw21: tone on dsp.sig_ch (ch28=SIG), routed via dsp mix into zone chain.
        """
        out_idx, _ = self._output_info(zone)
        dsp.start_tone(dsp.sig_ch, freq_hz, -20)
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            if dsp.cn is not None:
                dsp._set_tone_source_for_zone(zone)
            dsp.clear_all_sig_routes()
        else:
            dsp.set_mixer(dsp.sig_ch, out_idx, 0)

    @pytest.mark.parametrize("zone", ALL_ZONES)
    @pytest.mark.parametrize("bass_value,direction", [
        (120, "boost +12dB"),
        (-120, "cut -12dB"),
    ])
    def test_bass_changes_level(self, dsp, cresnext, device_cfg, test_settings,
                                zone, bass_value, direction):
        """Bass boost/cut changes the output level for a low-frequency tone."""
        out_idx, out_name = self._output_info(zone)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone, 100)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False, Bass=0)

        level_flat = dsp.measure_output_level(out_name)
        dsp.assert_signal_presence(zone, expected=True)

        dsp.set_zone_bass(zone, bass_value)
        level_changed = dsp.measure_output_level(out_name)

        if level_flat > test_settings["mute_floor_db"]:
            # A ±12 dB shelving filter at 100Hz should produce at least
            # MIN_EFFECT_DB of measurable change.  The 1 dB tolerance is
            # only for measurement jitter — the feature must move the level
            # by a meaningful amount proportional to the setting.
            min_effect_db = abs(bass_value) / 120.0 * 5.0  # 5 dB min at full ±12 dB
            if bass_value > 0:
                assert level_changed >= level_flat + min_effect_db, (
                    f"Zone {zone} bass boost too weak: flat={level_flat:.2f}dB, "
                    f"after={level_changed:.2f}dB (Δ={level_changed - level_flat:+.2f}dB, need ≥+{min_effect_db:.1f}dB)"
                )
            else:
                assert level_changed <= level_flat - min_effect_db, (
                    f"Zone {zone} bass cut too weak: flat={level_flat:.2f}dB, "
                    f"after={level_changed:.2f}dB (Δ={level_changed - level_flat:+.2f}dB, need ≤-{min_effect_db:.1f}dB)"
                )

    @pytest.mark.parametrize("zone", ALL_ZONES)
    @pytest.mark.parametrize("treble_value,direction", [
        (120, "boost +12dB"),
        (-120, "cut -12dB"),
    ])
    def test_treble_changes_level(self, dsp, cresnext, device_cfg, test_settings,
                                  zone, treble_value, direction):
        """Treble boost/cut changes the output level for a high-frequency tone."""
        out_idx, out_name = self._output_info(zone)
        if out_name not in device_cfg.get("amp_outputs", []):
            pytest.skip(f"{out_name} not available on {device_cfg['model']}")

        self._setup_zone(dsp, device_cfg, zone, 10000)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False, Treble=0)

        level_flat = dsp.measure_output_level(out_name)
        dsp.assert_signal_presence(zone, expected=True)

        dsp.set_zone_treble(zone, treble_value)
        level_changed = dsp.measure_output_level(out_name)

        if level_flat > test_settings["mute_floor_db"]:
            # A ±12 dB shelving filter at 10kHz should produce at least
            # MIN_EFFECT_DB of measurable change.
            min_effect_db = abs(treble_value) / 120.0 * 5.0  # 5 dB min at full ±12 dB
            if treble_value > 0:
                assert level_changed >= level_flat + min_effect_db, (
                    f"Zone {zone} treble boost too weak: flat={level_flat:.2f}dB, "
                    f"after={level_changed:.2f}dB (Δ={level_changed - level_flat:+.2f}dB, need ≥+{min_effect_db:.1f}dB)"
                )
            else:
                assert level_changed <= level_flat - min_effect_db, (
                    f"Zone {zone} treble cut too weak: flat={level_flat:.2f}dB, "
                    f"after={level_changed:.2f}dB (Δ={level_changed - level_flat:+.2f}dB, need ≤-{min_effect_db:.1f}dB)"
                )
