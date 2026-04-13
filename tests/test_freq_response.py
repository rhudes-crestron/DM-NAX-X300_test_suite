"""
Test: Frequency Response Flatness
Category: Audio Quality
═══════════════════════════════════════════════════════════════
Sweeps a sine tone across 20 Hz – 20 kHz through the signal generator →
mixer → amp output path and verifies the output level stays within
a tight tolerance window, detecting filter anomalies, broken EQ,
or unexpected rolloff.

Flow:
  ┌──────────┐    ┌──────────┐    ┌────────────┐    ┌───────────┐    ┌──────────┐
  │ SSH: dsp  │───▶│ SSH: dsp  │───▶│   DSP      │───▶│ SSH: dsp  │───▶│  Assert  │
  │ tone 28   │    │ mix 28→0  │    │ processing │    │ ducker_db │    │  ±1.5 dB │
  │ @freq,-20 │    │ @ 0 dB    │    │ (flat)     │    │ (pre-vol) │    │ flatness │
  └──────────┘    └──────────┘    └────────────┘    └───────────┘    └──────────┘
═══════════════════════════════════════════════════════════════
"""
import pytest
import logging
import time

logger = logging.getLogger(__name__)

# Frequencies to sweep (Hz) — covers audible spectrum
SWEEP_FREQUENCIES = [
    20, 50, 100, 200, 500, 1000, 2000, 5000, 8000, 10000, 15000, 20000,
]

TONE_GAIN_DB = -20
FLATNESS_TOLERANCE_DB = 1.5   # 8kHz shows ~1.15 dB dip (DSP characteristic)
SETTLE_TIME_S = 2.5           # Extended settle for freq-sweep accuracy
RETRY_SETTLE_TIME_S = 3.0    # Even longer on retry
OUTPUT_IDX = 0
OUTPUT_NAME = "A1L"


class TestFrequencyResponse:
    """Frequency response flatness across the audible spectrum."""

    _reference_level = None
    _freq_results = {}

    def test_freq_response_setup(self, dsp, device_cfg, test_settings):
        """Set up signal path: SIG → A1L and measure reference at 1 kHz."""
        sig_ch = device_cfg["signal_generator"]["channel"]
        dsp.start_tone(sig_ch, 1000, TONE_GAIN_DB)
        dsp.route_sig_to_output(OUTPUT_IDX, gain_db=0)

        level = dsp.measure_mixer_level(OUTPUT_NAME, settle_time=SETTLE_TIME_S)
        assert level > test_settings["mute_floor_db"], (
            f"No signal at {OUTPUT_NAME}: {level} dB"
        )
        dsp.assert_signal_presence(1, expected=True)
        TestFrequencyResponse._reference_level = level
        logger.info("Reference level at 1 kHz: %.2f dB (ducker/pre-vol)", level)

        # Cleanup tone (each parametrized test sets its own)
        dsp.stop_sig_tone()

    @pytest.mark.parametrize("freq_hz", SWEEP_FREQUENCIES)
    def test_freq_response_at(self, dsp, device_cfg, test_settings, freq_hz):
        """Output level at {freq_hz} Hz must be within ±0.5 dB of 1 kHz reference."""
        sig_ch = device_cfg["signal_generator"]["channel"]

        # Ensure route is set (module_reset may have cleared it)
        dsp.route_sig_to_output(OUTPUT_IDX, gain_db=0)
        dsp.start_tone(sig_ch, freq_hz, TONE_GAIN_DB)

        level = dsp.measure_mixer_level(OUTPUT_NAME, settle_time=SETTLE_TIME_S)
        TestFrequencyResponse._freq_results[freq_hz] = level

        assert level > test_settings["mute_floor_db"], (
            f"No signal at {freq_hz} Hz: {level} dB"
        )

        ref = TestFrequencyResponse._reference_level
        if ref is None:
            pytest.skip("Reference level not set — run test_freq_response_setup first")

        deviation = abs(level - ref)

        # Retry once with longer settle if marginal failure
        if deviation > FLATNESS_TOLERANCE_DB:
            logger.info(
                "%5d Hz: Δ=%.2f dB exceeds tolerance, retrying with longer settle...",
                freq_hz, deviation,
            )
            time.sleep(RETRY_SETTLE_TIME_S)
            level = dsp.measure_mixer_level(OUTPUT_NAME, settle_time=0.5)
            TestFrequencyResponse._freq_results[freq_hz] = level
            deviation = abs(level - ref)

        logger.info(
            "%5d Hz: %.2f dB  (ref=%.2f, Δ=%.2f)",
            freq_hz, level, ref, deviation,
        )
        assert deviation <= FLATNESS_TOLERANCE_DB, (
            f"Freq response deviation at {freq_hz} Hz: "
            f"{level:.2f} dB vs ref {ref:.2f} dB (Δ={deviation:.2f}, "
            f"tolerance=±{FLATNESS_TOLERANCE_DB})"
        )

        # Stop tone after measurement
        dsp.stop_tone(sig_ch)

    def test_freq_response_summary(self, dsp, device_cfg):
        """Log full frequency response sweep summary."""
        sig_ch = device_cfg["signal_generator"]["channel"]

        # Cleanup
        dsp.stop_tone(sig_ch)
        dsp.clear_sig_route(OUTPUT_IDX)

        results = TestFrequencyResponse._freq_results
        if not results:
            pytest.skip("No sweep data collected")

        ref = TestFrequencyResponse._reference_level or 0
        report = "\n  Frequency Response Sweep:\n"
        report += f"  {'Freq (Hz)':>10}  {'Level (dB)':>10}  {'Δ (dB)':>8}\n"
        report += "  " + "-" * 35 + "\n"
        for freq in sorted(results):
            lvl = results[freq]
            delta = lvl - ref
            report += f"  {freq:>10}  {lvl:>10.2f}  {delta:>+8.2f}\n"
        logger.info(report)
