"""
Test: Balance Control
Category: DSP
Verifies that balance control correctly attenuates left or right channels.
Device state is automatically reset before and after each test by conftest.
"""
import pytest
import math


class TestBalance:
    """Verify zone balance adjusts left/right channel levels."""

    CATEGORY = "dsp_balance"

    def test_balance_center(self, dsp, device_cfg, test_settings):
        """At center balance (0), both L and R outputs have equal level."""
        import time
        sig_ch = device_cfg["signal_generator"]["channel"]

        dsp.start_sig_tone()
        # Clear all sig routes first (fw42: ch0 bleeds to all outputs)
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            dsp.clear_all_sig_routes()
        dsp.set_mixer(sig_ch, 0, 0)  # A1L
        dsp.set_mixer(sig_ch, 1, 0)  # A1R

        # Wait for signal to settle, then read BOTH channels from a single
        # DSP snapshot so the levels are from the same instant.
        time.sleep(test_settings["signal_settle_time_s"])
        state = dsp.read_dsp_state()
        a1l = state.outputs.get("A1L")
        a1r = state.outputs.get("A1R")

        assert a1l and a1r, "A1L/A1R outputs not found"
        assert a1l.output_db > test_settings["mute_floor_db"], "No signal at A1L"
        diff = abs(a1l.output_db - a1r.output_db)
        assert diff <= test_settings["level_tolerance_db"] * 3, (
            f"L/R imbalance at center: L={a1l.output_db:.2f}, R={a1r.output_db:.2f}, diff={diff:.2f}"
        )

        # Verify CresNext signal presence on zone 1
        dsp.assert_signal_presence(1, expected=True)

    def test_balance_full_left(self, dsp, device_cfg, test_settings):
        """Full left balance attenuates right channel."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_sig_tone()
        # Clear all sig routes first (fw42: ch0 bleeds to all outputs)
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            dsp.clear_all_sig_routes()
        dsp.set_mixer(sig_ch, 0, 0)
        dsp.set_mixer(sig_ch, 1, 0)

        dsp.set_zone_balance(1, -500)  # Full left

        level_l = dsp.measure_output_level("A1L")
        level_r = dsp.measure_output_level("A1R", settle_time=0.5)

        if level_l > test_settings["mute_floor_db"]:
            assert level_r < level_l - 3.0, (
                f"Right not attenuated with full-left balance: L={level_l:.2f}, R={level_r:.2f}"
            )

    def test_balance_full_right(self, dsp, device_cfg, test_settings):
        """Full right balance attenuates left channel."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_sig_tone()
        # Clear all sig routes first (fw42: ch0 bleeds to all outputs)
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            dsp.clear_all_sig_routes()
        dsp.set_mixer(sig_ch, 0, 0)
        dsp.set_mixer(sig_ch, 1, 0)

        dsp.set_zone_balance(1, 500)  # Full right

        level_l = dsp.measure_output_level("A1L")
        level_r = dsp.measure_output_level("A1R", settle_time=0.5)

        if level_r > test_settings["mute_floor_db"]:
            assert level_l < level_r - 3.0, (
                f"Left not attenuated with full-right balance: L={level_l:.2f}, R={level_r:.2f}"
            )
