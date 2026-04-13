"""
Test: Cross-Channel Bleed (Crosstalk)
Category: Audio Quality
═══════════════════════════════════════════════════════════════
Injects a tone on a single output channel and verifies that all other
amp output channels remain at the noise floor, detecting any unwanted
signal leakage between channels.

Flow:
  ┌──────────┐    ┌──────────┐    ┌────────────┐    ┌──────────┐    ┌───────────┐
  │ SSH: dsp  │───▶│ SSH: dsp  │───▶│   DSP      │───▶│ SSH: dsp │───▶│  Assert   │
  │ tone 28   │    │ mix 28→N  │    │ processing │    │ read ALL │    │  active   │
  │ @1kHz,-20 │    │ ONE only  │    │            │    │ output_db│    │  ch hot,  │
  └──────────┘    └──────────┘    └────────────┘    └──────────┘    │  others   │
                                                                     │  silent   │
                                                                     └───────────┘
═══════════════════════════════════════════════════════════════
"""
import math
import pytest
import logging

logger = logging.getLogger(__name__)

TONE_FREQ = 1000
TONE_GAIN = -20
CROSSTALK_MAX_DB = -80.0   # other channels must stay below this

# Amp output pairs to test crosstalk isolation
AMP_OUTPUTS = [
    (0, "A1L"), (1, "A1R"), (2, "A2L"), (3, "A2R"),
    (4, "A3L"), (5, "A3R"), (6, "A4L"), (7, "A4R"),
]


class TestCrosstalk:
    """Cross-channel isolation — signal on one output must not bleed to others."""

    @pytest.mark.parametrize("active_idx,active_name", AMP_OUTPUTS)
    def test_crosstalk_isolation(self, dsp, device_cfg, test_settings,
                                 active_idx, active_name):
        """Signal on {active_name} must not bleed to other amp outputs."""
        if active_name not in device_cfg["amp_outputs"]:
            pytest.skip(f"{active_name} not on {device_cfg['model']}")

        sig_ch = device_cfg["signal_generator"]["channel"]

        # Route signal to ONLY the active channel
        dsp.start_tone(sig_ch, TONE_FREQ, TONE_GAIN)
        dsp.route_sig_to_output(active_idx, gain_db=0)

        # Wait for settle
        import time
        time.sleep(test_settings["signal_settle_time_s"])

        # Read full DSP state once
        state = dsp.read_dsp_state()

        # Verify CresNext signal presence on the active zone (before cleanup)
        active_zone = dsp.zone_for_output(active_idx)
        dsp.assert_signal_presence(active_zone, expected=True)

        # Cleanup
        dsp.stop_tone(sig_ch)
        dsp.clear_sig_route(active_idx)

        # Verify active channel has signal
        if active_name in state.outputs:
            active_level = state.outputs[active_name].output_db
            assert active_level > test_settings["mute_floor_db"], (
                f"Active channel {active_name} has no signal: {active_level:.2f} dB"
            )
        else:
            pytest.fail(f"{active_name} not found in DSP state")

        # Verify ALL OTHER amp channels are silent
        bleed_channels = []
        for other_idx, other_name in AMP_OUTPUTS:
            if other_idx == active_idx:
                continue
            if other_name not in device_cfg["amp_outputs"]:
                continue
            if other_name not in state.outputs:
                continue

            other_level = state.outputs[other_name].output_db
            if math.isinf(other_level):
                continue  # -inf is fine

            if other_level > CROSSTALK_MAX_DB:
                bleed_channels.append((other_name, other_level))

        if bleed_channels:
            details = ", ".join(
                f"{name}={level:.2f} dB" for name, level in bleed_channels
            )
            pytest.fail(
                f"Crosstalk detected with signal on {active_name}: "
                f"{details} (max allowed: {CROSSTALK_MAX_DB} dB)"
            )

        logger.info(
            "Crosstalk OK: %s active at %.2f dB, all others silent",
            active_name, active_level,
        )
