"""
Test: Signal-to-Noise Ratio
Category: Audio Quality
═══════════════════════════════════════════════════════════════
Measures the dynamic range between an active signal and the silent
noise floor on each amp output channel, verifying sufficient SNR and
that idle channels sit at the expected noise floor.

Flow:
  ┌──────────┐    ┌──────────┐    ┌────────────┐    ┌──────────┐    ┌───────────┐
  │ SSH: dsp  │───▶│ SSH: dsp  │───▶│   DSP      │───▶│ SSH: dsp │───▶│  Assert   │
  │ tone off  │    │ mixer off │    │ processing │    │ output_db│    │  floor    │
  │ (silent)  │    │ (no xpt)  │    │ (idle)     │    │ per chan  │    │  < -90 dB │
  └──────────┘    └──────────┘    └────────────┘    └──────────┘    └───────────┘
               then
  ┌──────────┐    ┌──────────┐    ┌────────────┐    ┌──────────┐    ┌───────────┐
  │ SSH: dsp  │───▶│ SSH: dsp  │───▶│   DSP      │───▶│ SSH: dsp │───▶│  Assert   │
  │ tone 28   │    │ mix 28→ch │    │ processing │    │ output_db│    │  SNR      │
  │ @1kHz,-20 │    │ @ 0 dB    │    │ (active)   │    │ per chan  │    │  > 70 dB  │
  └──────────┘    └──────────┘    └────────────┘    └──────────┘    └───────────┘
═══════════════════════════════════════════════════════════════
"""
import math
import pytest
import logging

logger = logging.getLogger(__name__)

NOISE_FLOOR_MAX_DB = -90.0   # idle channels must be below this
MIN_SNR_DB = 70.0            # signal - noise must exceed this
TONE_FREQ = 1000
TONE_GAIN = -20

# Amp output channels (index, name)
AMP_OUTPUTS = [
    (0, "A1L"), (1, "A1R"), (2, "A2L"), (3, "A2R"),
    (4, "A3L"), (5, "A3R"), (6, "A4L"), (7, "A4R"),
]


class TestSignalToNoise:
    """Signal-to-noise ratio and noise floor verification."""

    @pytest.mark.parametrize("out_idx,out_name", AMP_OUTPUTS)
    def test_noise_floor(self, dsp, device_cfg, out_idx, out_name):
        """Idle output {out_name} noise floor must be below -90 dB."""
        if out_name not in device_cfg["amp_outputs"]:
            pytest.skip(f"{out_name} not on {device_cfg['model']}")

        # Ensure signal generator is stopped and all its routes are cleared
        dsp.stop_sig_tone()
        dsp.clear_all_sig_routes()

        # No tone, no mixer route — pure silence
        level = dsp.measure_output_level(out_name, settle_time=0.5)
        logger.info("Noise floor %s: %.2f dB", out_name, level)

        assert level < NOISE_FLOOR_MAX_DB, (
            f"Noise floor too high on {out_name}: {level:.2f} dB "
            f"(max {NOISE_FLOOR_MAX_DB} dB)"
        )

    @pytest.mark.parametrize("out_idx,out_name", AMP_OUTPUTS)
    def test_snr(self, dsp, device_cfg, out_idx, out_name):
        """SNR on {out_name} must exceed 70 dB."""
        if out_name not in device_cfg["amp_outputs"]:
            pytest.skip(f"{out_name} not on {device_cfg['model']}")

        sig_ch = device_cfg["signal_generator"]["channel"]

        # 1. Measure noise floor (no signal)
        noise = dsp.measure_output_level(out_name, settle_time=0.5)

        # 2. Inject signal and measure
        dsp.start_tone(sig_ch, TONE_FREQ, TONE_GAIN)
        dsp.route_sig_to_output(out_idx, gain_db=0)

        # On fw42, route_sig_to_output triggers HandleNewRoute which resets
        # zone volume to ~30%.  Restore 0dB reference so SNR isn't penalised.
        zone = dsp.zone_for_output(out_idx)
        dsp.set_zone_volume(zone, 800)

        signal = dsp.measure_output_level(out_name)

        # Verify the signal is clearly above the noise floor (not -inf or -341 dB).
        # Do NOT use assert_signal_presence() (IsSignalDetected CresNext flag) here —
        # that flag has a firmware hardware threshold (~-50 dB) unrelated to SNR.
        assert signal > NOISE_FLOOR_MAX_DB, (
            f"No signal detected on {out_name} after routing tone: {signal:.2f} dB"
        )

        # 3. Cleanup
        dsp.stop_tone(sig_ch)
        dsp.clear_sig_route(out_idx)

        # 4. Calculate SNR
        if math.isinf(noise):
            noise = -130.0  # treat -inf as very low floor

        snr = signal - noise
        logger.info(
            "SNR %s: signal=%.2f noise=%.2f → SNR=%.1f dB",
            out_name, signal, noise, snr,
        )

        assert snr >= MIN_SNR_DB, (
            f"SNR too low on {out_name}: {snr:.1f} dB "
            f"(signal={signal:.2f}, noise={noise:.2f}, min={MIN_SNR_DB})"
        )
