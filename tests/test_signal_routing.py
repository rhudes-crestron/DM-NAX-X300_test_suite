"""
Test: Signal Routing Verification
Category: DSP

Verifies that the DSP tone generator can be routed through the CresNext
AudioSource assignment AND the DSP mixer to each amplifier output, and that
CresNext reports the zone source correctly and detects signal.

Test sequence per output (matches AP_TestCases.xlsx AvMatrixRoutings /
StreamRoutings setup rows):
  1. POST CresNext zone AudioSource  → dsp_tone_input from devices.yaml
     (fw42 8ZSA/4ZSP: StreamRoutings batch POST; fw21 4ZSA: per-zone POST)
  2. GET CresNext zone AudioSource   → verify readback equals what was set
  3. POST CresNext ZoneAudio Volume=800 (0 dB reference), IsMuted=False
  4. SSH: start DSP tone generator (dsp tone <ch> <freq> <gain>)
  5. SSH: clear all mixer routes for the signal channel (isolation)
  6. SSH: set mixer crosspoint ch → output_idx at 0 dB
  7. Wait signal_settle_time_s
  8. SSH: read DSP state table; assert output_db > mute_floor_db
  9. GET CresNext IsSignalDetected on the zone; assert True
     (fw21: best-effort — ch28 tone gen may not trigger CresNext level detection)
"""
import pytest
import time


class TestSignalRouting:
    """Verify signal path from signal generator to each output zone."""

    CATEGORY = "dsp_routing"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _set_zone_source(cresnext, device_cfg, zone, tone_input):
        """Set zone AudioSource via the fw-appropriate CresNext REST path.

        fw42 8ZSA/4ZSP: uses the batch StreamRoutings POST
          POST /Device/AvMatrixRouting/Routes/Zone1,..,ZoneN/
               { AudioSource: "Input01,...,InputN" }
        fw21 4ZSA and others: per-zone AvMatrixRouting POST
          POST /Device/AvMatrixRouting/Routes/Zone{N}/
               { AudioSource: "Input01" }
        """
        model = str(device_cfg.get("model", "")).upper()
        fw    = device_cfg.get("dsp_fw_version", 21)
        if fw >= 42 and model in {"8ZSA", "4ZSP"}:
            cresnext.set_zone_sources_streamrouting({zone: tone_input})
        else:
            cresnext.set_zone_source(zone, tone_input)

    @staticmethod
    def _verify_zone_source(cresnext, zone, expected_input):
        """GET and assert the zone's AudioSource readback."""
        actual = cresnext.get_zone_source(zone)
        assert actual == expected_input, (
            f"Zone {zone} AudioSource readback: expected={expected_input!r}, "
            f"got={actual!r}"
        )

    # ------------------------------------------------------------------
    # Sanity checks
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Main amp-output routing test
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("output_idx,output_name", [
        (0, "A1L"), (1, "A1R"), (2, "A2L"), (3, "A2R"),
        (4, "A3L"), (5, "A3R"), (6, "A4L"), (7, "A4R"),
    ])
    def test_sig_routes_to_amp_output(self, dsp, cresnext, device_cfg,
                                       test_settings, output_idx, output_name):
        """Signal generator routes to each amplifier output via CresNext zone
        source assignment + DSP mixer, with CresNext readback verification.

        - Sets CresNext AudioSource to dsp_tone_input (AvMatrixRouting /
          StreamRoutings) and verifies readback before starting audio.
        - Sets Volume=800 (0 dB) and IsMuted=False so zone chain is open.
        - Routes tone via DSP mixer to the specific amp output.
        - Asserts output_db > mute_floor_db (DSP measured level).
        - Asserts CresNext IsSignalDetected=True on the zone (fw42 only;
          fw21 ch28 tone gen is not tracked by CresNext level detection).
        """
        if output_name not in device_cfg["amp_outputs"]:
            pytest.skip(f"{output_name} not available on {device_cfg['model']}")

        sig_ch     = device_cfg["signal_generator"]["channel"]
        tone_input = device_cfg.get("dsp_tone_input", "Input01")
        zone       = dsp.zone_for_output(output_idx)
        fw         = device_cfg.get("dsp_fw_version", 21)

        # ── Step 1: Set CresNext zone source ───────────────────────────
        self._set_zone_source(cresnext, device_cfg, zone, tone_input)

        # ── Step 2: Verify AudioSource readback ────────────────────────
        self._verify_zone_source(cresnext, zone, tone_input)

        # ── Step 3: Ensure zone audio chain is open ────────────────────
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)

        # ── Step 4: Start DSP tone generator ───────────────────────────
        dsp.start_tone(
            sig_ch,
            test_settings["default_tone_freq_hz"],
            test_settings["default_tone_gain_db"],
        )

        # ── Step 5: Clear old mixer routes, set new crosspoint ─────────
        # Clear all routes on this channel first to avoid bleed from a
        # prior test; required on fw42 where ch0 may already be routed.
        dsp.clear_all_sig_routes()
        dsp.set_mixer(sig_ch, output_idx, 0)
        time.sleep(test_settings["signal_settle_time_s"])

        # ── Step 6: Verify DSP output level ────────────────────────────
        state = dsp.read_dsp_state()
        assert output_name in state.outputs, (
            f"Output {output_name} not found in DSP state"
        )
        out = state.outputs[output_name]
        assert out.output_db > test_settings["mute_floor_db"], (
            f"No signal at {output_name}: output_db={out.output_db:.2f} dB "
            f"(zone={zone}, source={tone_input}, "
            f"mixer ch{sig_ch}→out{output_idx})"
        )

        # ── Step 7: Verify CresNext IsSignalDetected ───────────────────
        # On fw42, DSP ch0 = physical Input01 — CresNext tracks its level.
        # On fw21, ch28 is an internal hardware SIG gen not exposed to the
        # CresNext level-detection path; skip the presence check.
        if fw >= 42:
            dsp.assert_signal_presence(zone, expected=True)

    # ------------------------------------------------------------------
    # Line output routing test
    # ------------------------------------------------------------------

    def test_sig_routes_to_line_output(self, dsp, cresnext, device_cfg,
                                        test_settings):
        """Signal generator routes to line output L1L.

        Line outputs share Zone 1's audio chain on all current devices.
        Sets CresNext Zone 1 source + Volume before routing.
        """
        if "L1L" not in device_cfg.get("line_outputs", []):
            pytest.skip(f"L1L not available on {device_cfg['model']}")

        sig_ch     = device_cfg["signal_generator"]["channel"]
        tone_input = device_cfg.get("dsp_tone_input", "Input01")
        zone       = 1  # L1L is part of Zone 1 audio chain on all DM-NAX devices

        # Set CresNext zone source and verify readback
        self._set_zone_source(cresnext, device_cfg, zone, tone_input)
        self._verify_zone_source(cresnext, zone, tone_input)
        cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)

        dsp.start_tone(
            sig_ch,
            test_settings["default_tone_freq_hz"],
            test_settings["default_tone_gain_db"],
        )
        dsp.clear_all_sig_routes()
        # L1L is DSP output channel 8 on 4ZSA/8ZSA
        line_out_ch = 8
        dsp.set_mixer(sig_ch, line_out_ch, 0)
        time.sleep(test_settings["signal_settle_time_s"])

        state = dsp.read_dsp_state()
        assert "L1L" in state.outputs, "L1L not found in DSP state"
        out = state.outputs["L1L"]
        # L1L level may appear in ducker_db (pre-zone-chain) or output_db
        level = out.output_db if out.output_db > test_settings["mute_floor_db"] \
                else out.ducker_db
        assert level > test_settings["mute_floor_db"], (
            f"No signal at L1L: output_db={out.output_db:.2f} "
            f"ducker_db={out.ducker_db:.2f} dB"
        )

    # ------------------------------------------------------------------
    # Zone isolation
    # ------------------------------------------------------------------

    def test_zone_isolation(self, dsp, cresnext, device_cfg, test_settings):
        """Muting zone 2 silences A2L without affecting A1L.

        Both zones are explicitly configured via CresNext before the test
        so the result is not dependent on prior state.
        """
        if device_cfg.get("zones", 4) < 2:
            pytest.skip("Requires at least 2 zones")

        sig_ch     = device_cfg["signal_generator"]["channel"]
        tone_input = device_cfg.get("dsp_tone_input", "Input01")

        # Set source + volume for both zones under test
        for z in (1, 2):
            self._set_zone_source(cresnext, device_cfg, z, tone_input)
            cresnext.set_zone_audio(z, Volume=800, IsMuted=False)

        dsp.start_tone(
            sig_ch,
            test_settings["default_tone_freq_hz"],
            test_settings["default_tone_gain_db"],
        )
        dsp.clear_all_sig_routes()
        # Route to both Zone 1 (A1L=out0) and Zone 2 (A2L=out2)
        dsp.set_mixer(sig_ch, 0, 0)
        dsp.set_mixer(sig_ch, 2, 0)
        time.sleep(test_settings["signal_settle_time_s"])

        # Baseline — both A1L and A2L should have signal
        state = dsp.read_dsp_state()
        a1l_before = state.outputs.get("A1L")
        a2l_before = state.outputs.get("A2L")
        assert a1l_before and a1l_before.output_db > test_settings["mute_floor_db"], (
            f"A1L baseline: output_db={getattr(a1l_before, 'output_db', 'N/A'):.2f}"
        )
        assert a2l_before and a2l_before.output_db > test_settings["mute_floor_db"], (
            f"A2L baseline: output_db={getattr(a2l_before, 'output_db', 'N/A'):.2f}"
        )

        # Mute zone 2 only via CresNext
        cresnext.set_zone_audio(2, IsMuted=True)
        time.sleep(test_settings["signal_settle_time_s"])
        state = dsp.read_dsp_state()

        a1l_after = state.outputs["A1L"]
        a2l_after = state.outputs["A2L"]

        assert a1l_after.output_db > test_settings["mute_floor_db"], (
            f"A1L affected by zone 2 mute: {a1l_after.output_db:.2f} dB"
        )
        assert a2l_after.output_db < -60, (
            f"A2L not silenced by zone 2 mute: {a2l_after.output_db:.2f} dB"
        )

        # Restore
        cresnext.set_zone_audio(2, IsMuted=False)

    # ------------------------------------------------------------------
    # Mixer gain accuracy (fw21 only)
    # ------------------------------------------------------------------

    def test_mixer_gain_accuracy(self, dsp, cresnext, device_cfg, test_settings):
        """Reducing mixer gain from 0 dB to -20 dB decreases output level.

        Only relevant on fw21 where the SIG gen bypasses the zone audio chain;
        on fw42 the zone chain contribution dominates the level change effect.
        """
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            pytest.skip(
                "Mixer gain delta assertion is not stable on fw42 zone-output path"
            )

        sig_ch     = device_cfg["signal_generator"]["channel"]
        tone_input = device_cfg.get("dsp_tone_input", "Input01")

        self._set_zone_source(cresnext, device_cfg, 1, tone_input)
        self._verify_zone_source(cresnext, 1, tone_input)
        cresnext.set_zone_audio(1, Volume=800, IsMuted=False)

        dsp.clear_all_sig_routes()
        dsp.start_tone(
            sig_ch,
            test_settings["default_tone_freq_hz"],
            test_settings["default_tone_gain_db"],
        )
        dsp.set_mixer(sig_ch, 0, 0)
        time.sleep(test_settings["signal_settle_time_s"])
        state = dsp.read_dsp_state()
        level_0db = state.outputs["A1L"].ducker_db

        dsp.set_mixer(sig_ch, 0, -20)
        time.sleep(test_settings["signal_settle_time_s"])
        state = dsp.read_dsp_state()
        level_m20db = state.outputs["A1L"].ducker_db

        assert level_m20db < level_0db - 0.5, (
            f"Mixer gain change had no effect: "
            f"0dB={level_0db:.2f}, -20dB={level_m20db:.2f}"
        )


