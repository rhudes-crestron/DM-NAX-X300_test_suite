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

        sig_ch     = dsp.sig_ch_for_output(output_idx)
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


