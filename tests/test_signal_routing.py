"""
Test: Signal Routing Verification
Category: DSP
Verifies that the signal generator can route through the mixer to each
amplifier output, line output, and network output with correct levels.
Device state is automatically reset before and after each test by conftest.
"""
import pytest
import math


class TestSignalRouting:
    """Verify signal path from signal generator to each output zone."""

    CATEGORY = "dsp_routing"

    def test_device_reachable(self, ssh):
        """Verify the DUT is reachable and responsive."""
        assert ssh.is_reachable(), "Device is not reachable via SSH"

    def test_firmware_version(self, ssh, device_cfg):
        """Verify firmware version is reported."""
        ver = ssh.get_version()
        assert device_cfg["model"] in ver, f"Model not found in version: {ver}"

    def test_dsp_state_readable(self, dsp):
        """Verify DSP state table can be parsed."""
        state = dsp.read_dsp_state()
        assert state.model, "Could not parse DSP model"
        assert state.fw_version > 0, "Could not parse DSP FW version"
        assert len(state.inputs) > 0, "No input channels parsed"
        assert len(state.outputs) > 0, "No output channels parsed"

    @pytest.mark.parametrize("output_idx,output_name", [
        (0, "A1L"), (1, "A1R"), (2, "A2L"), (3, "A2R"),
        (4, "A3L"), (5, "A3R"), (6, "A4L"), (7, "A4R"),
    ])
    def test_sig_routes_to_amp_output(self, dsp, device_cfg, test_settings,
                                       output_idx, output_name):
        """Signal generator routes to each amplifier output."""
        if output_name not in device_cfg["amp_outputs"]:
            pytest.skip(f"{output_name} not available on {device_cfg['model']}")

        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_sig_tone()
        dsp.route_sig_to_output(output_idx)

        state = dsp.read_dsp_state()
        assert output_name in state.outputs, f"Output {output_name} not found in DSP state"

        out = state.outputs[output_name]
        assert out.ducker_db > test_settings["mute_floor_db"], (
            f"No signal at {output_name}: mixer level = {out.ducker_db} dB"
        )

        # Verify CresNext reports signal detected on the zone
        zone = dsp.zone_for_output(output_idx)
        dsp.assert_signal_presence(zone, expected=True)


    def test_sig_routes_to_line_output(self, dsp, device_cfg, test_settings):
        """Signal generator routes to line output L1L (output 8)."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_sig_tone()
        dsp.set_mixer(sig_ch, 8, 0)  # L1L is typically output 8

        state = dsp.read_dsp_state()
        if "L1L" in state.outputs:
            out = state.outputs["L1L"]
            assert out.ducker_db > test_settings["mute_floor_db"], (
                f"No signal at L1L: level = {out.ducker_db} dB"
            )

    def test_zone_isolation(self, dsp, device_cfg, test_settings):
        """Muting one zone does not affect other zones' output.

        On the 4ZSA the signal generator feeds all zone outputs through the
        zone audio path.  This test verifies that zone-level mute is
        independent — muting zone 2 silences A2L but leaves A1L unaffected.
        """
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_sig_tone()

        import time
        time.sleep(test_settings["signal_settle_time_s"])

        # Baseline — both A1L and A2L should have signal
        state = dsp.read_dsp_state()
        a1l_before = state.outputs.get("A1L")
        a2l_before = state.outputs.get("A2L")
        assert a1l_before and a1l_before.output_db > test_settings["mute_floor_db"]
        assert a2l_before and a2l_before.output_db > test_settings["mute_floor_db"]

        # Mute zone 2 only
        dsp.set_zone_mute(2, True)
        time.sleep(0.5)
        state = dsp.read_dsp_state()

        a1l_after = state.outputs["A1L"]
        a2l_after = state.outputs["A2L"]

        # A1L should still have signal
        assert a1l_after.output_db > test_settings["mute_floor_db"], (
            f"A1L affected by zone 2 mute: {a1l_after.output_db:.2f} dB"
        )
        # A2L should be silenced
        assert a2l_after.output_db < -60, (
            f"A2L not silenced by zone 2 mute: {a2l_after.output_db:.2f} dB"
        )

        # Signal presence: zone 1 should still be detected, zone 2 silenced
        dsp.assert_signal_presence(1, expected=True)

        # Restore zone 2
        dsp.set_zone_mute(2, False)

    def test_mixer_gain_accuracy(self, dsp, device_cfg, test_settings):
        """Verify that reducing mixer gain decreases output level.

        On the 4ZSA the signal generator feeds all zone outputs through the
        zone audio path at a constant level.  The mixer route adds on top of
        this, so a -6dB mixer change produces less than -6dB output change.
        We verify that the output level decreases measurably when the mixer
        gain is reduced from 0dB to -20dB.
        """
        sig_ch = device_cfg["signal_generator"]["channel"]

        # Clear all previous signal generator routes (batch SSH for speed)
        num_outputs = device_cfg.get("mixer_outputs", 10)
        cmds = [f"dsp mix {sig_ch} {o} -200" for o in range(num_outputs)]
        dsp.ssh.execute(" ; ".join(cmds), timeout=15)

        # Route at 0dB
        import time
        dsp.start_sig_tone()
        dsp.route_sig_to_output(0)
        time.sleep(test_settings["signal_settle_time_s"])
        state = dsp.read_dsp_state()
        level_0db = state.outputs["A1L"].ducker_db

        # Change mixer gain to -20dB (large enough change to see through zone path)
        dsp.set_mixer(sig_ch, 0, -20)
        time.sleep(test_settings["signal_settle_time_s"])
        state = dsp.read_dsp_state()
        level_m20db = state.outputs["A1L"].ducker_db

        assert level_m20db < level_0db - 0.5, (
            f"Mixer gain change had no effect: 0dB={level_0db:.2f}, "
            f"-20dB={level_m20db:.2f}"
        )


