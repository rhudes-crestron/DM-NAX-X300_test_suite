"""
DSP Controller - high-level interface for injecting signals, setting DSP
parameters, and reading measured levels from the DM-NAX SHARC DSP.

Zone properties are set via the CresNext REST API (not joins).
DSP signal injection and measurement use SSH console commands.
"""
import time
import math
import logging
from .dsp_parser import parse_dsp_output, parse_mixer_output

logger = logging.getLogger(__name__)


class DSPController:
    """Controls the DSP on a DM-NAX device via SSH console and CresNext REST API."""

    def __init__(self, ssh, device_cfg, test_settings, cresnext=None):
        self.ssh = ssh
        self.cfg = device_cfg
        self.settings = test_settings
        self.sig_ch = device_cfg["signal_generator"]["channel"]
        self.cn = cresnext  # CresNextClient for zone property control

    # ------------------------------------------------------------------
    # Signal generator
    # ------------------------------------------------------------------
    def start_tone(self, channel, freq_hz, gain_db):
        """Start a test tone on a DSP input channel."""
        cmd = f"dsp tone {channel} {freq_hz} {gain_db}"
        out = self.ssh.execute(cmd)
        logger.info("Tone started: ch=%d freq=%d gain=%s", channel, freq_hz, gain_db)
        return out

    def stop_tone(self, channel):
        """Stop the test tone on a channel (freq=0)."""
        return self.ssh.execute(f"dsp tone {channel} 0 0")

    def start_sig_tone(self, freq_hz=None, gain_db=None):
        """Start a tone on the built-in signal generator channel."""
        freq = freq_hz or self.settings["default_tone_freq_hz"]
        gain = gain_db or self.settings["default_tone_gain_db"]
        return self.start_tone(self.sig_ch, freq, gain)

    def stop_sig_tone(self):
        return self.stop_tone(self.sig_ch)

    def start_white_noise(self, gain_db=-20):
        return self.ssh.execute(f"dsp wnoise {gain_db}")

    def start_pink_noise(self, gain_db=-20):
        return self.ssh.execute(f"dsp pnoise {gain_db}")

    # ------------------------------------------------------------------
    # Mixer routing
    # ------------------------------------------------------------------
    def set_mixer(self, input_ch, output_ch, gain_db=0):
        """Set a mixer crosspoint: route input_ch to output_ch at gain_db."""
        cmd = f"dsp mix {input_ch} {output_ch} {gain_db}"
        out = self.ssh.execute(cmd)
        logger.info("Mixer: in=%d -> out=%d @ %s dB", input_ch, output_ch, gain_db)
        return out

    def clear_mixer(self, input_ch, output_ch):
        """Clear a mixer crosspoint by setting to -inf."""
        return self.set_mixer(input_ch, output_ch, -200)

    def clear_all_sig_routes(self):
        """Clear the signal generator from ALL mixer outputs.

        On fw42 devices (4ZSP/8ZSA), the signal generator channel is a
        physical input (ch 0 = T1L) that can bleed to all outputs through
        default routing.  Clearing every crosspoint for this channel
        guarantees isolation before routing to a single target.
        """
        num_outputs = self.cfg.get("mixer_outputs", 10)
        cmds = [f"dsp mix {self.sig_ch} {out} -200" for out in range(num_outputs)]
        self.ssh.execute(" ; ".join(cmds), timeout=10)
        logger.info("Cleared all %d sig routes for ch %d", num_outputs, self.sig_ch)

    def route_sig_to_output(self, output_ch, gain_db=0):
        """Route signal generator to a specific output channel.

        On fw42 devices, clears all other routes first to guarantee
        that signal appears only on the target output.
        """
        if self.cfg.get("dsp_fw_version", 21) >= 42:
            self.clear_all_sig_routes()
        return self.set_mixer(self.sig_ch, output_ch, gain_db)

    def clear_sig_route(self, output_ch):
        return self.clear_mixer(self.sig_ch, output_ch)

    # ------------------------------------------------------------------
    # Input compensation / gain
    # ------------------------------------------------------------------
    def set_input_gain(self, channel, gain_db):
        """Set input compensation (gain offset in dB) on a physical input channel."""
        out = self.ssh.execute(f"dsp gain {channel} set {gain_db}")
        logger.info("Input gain: ch=%d gain=%s dB", channel, gain_db)
        return out

    def get_input_gain(self, channel):
        """Read current input gain on a channel."""
        out = self.ssh.execute(f"dsp gain {channel}")
        return out

    # ------------------------------------------------------------------
    # Zone properties via CresNext REST API
    # ------------------------------------------------------------------
    # Value ranges (from AP_TestCases.xlsx):
    #   Volume:      0-1000  (800 = 0dB)
    #   Balance:     -500 to 500  (0.1% steps; 0=center, -500=full left, 500=full right)
    #   Bass:        -120 to 120  (0.1dB steps; 0=flat)
    #   Treble:      -120 to 120  (0.1dB steps; 0=flat)
    #   DelayInms:   0-200  (milliseconds)
    #   IsMuted:     True/False
    #   IsLoudnessEnabled: True/False
    #   ToneProfile: "Off","Classical","Jazz","Pop","Rock","SpokenWord"
    #   NightMode:   "Off","Low","Medium","High"

    def set_zone_volume(self, zone, value):
        """Set zone volume (0-1000, where 800 = 0dB reference)."""
        return self.cn.set_zone_audio(zone, Volume=value)

    def set_zone_mute(self, zone, muted):
        """Mute or unmute a zone."""
        return self.cn.set_zone_audio(zone, IsMuted=bool(muted))

    def set_zone_bass(self, zone, value):
        """Set bass level (-120 to +120, in 0.1dB steps)."""
        return self.cn.set_zone_audio(zone, Bass=value)

    def set_zone_treble(self, zone, value):
        """Set treble level (-120 to +120, in 0.1dB steps)."""
        return self.cn.set_zone_audio(zone, Treble=value)

    def set_zone_balance(self, zone, value):
        """Set balance (-500=full left, 0=center, 500=full right)."""
        return self.cn.set_zone_audio(zone, Balance=value)

    def set_zone_loudness(self, zone, enabled):
        """Enable/disable loudness compensation."""
        return self.cn.set_zone_audio(zone, IsLoudnessEnabled=bool(enabled))

    def set_zone_tone_profile(self, zone, profile_name):
        """Set tone profile by name: Off, Classical, Jazz, Pop, Rock, SpokenWord."""
        return self.cn.set_zone_audio(zone, ToneProfile=str(profile_name))

    def set_zone_night_mode(self, zone, mode_name):
        """Set night mode by name: Off, Low, Medium, High."""
        return self.cn.set_zone_audio(zone, NightMode=str(mode_name))

    def set_zone_delay(self, zone, delay_ms):
        """Set output delay in milliseconds (0-200)."""
        return self.cn.set_zone_audio(zone, DelayInms=delay_ms)

    def get_zone_audio(self, zone):
        """Read all ZoneAudio properties via CresNext."""
        return self.cn.get_zone_audio(zone)

    # ------------------------------------------------------------------
    # Signal presence detection via CresNext
    # ------------------------------------------------------------------
    @staticmethod
    def zone_for_output(output_idx):
        """Map output index to zone number (0,1→1  2,3→2  4,5→3  6,7→4)."""
        return (output_idx // 2) + 1

    def is_signal_detected(self, zone):
        """Return CresNext IsSignalDetected flag for a zone."""
        if self.cn is None:
            return None
        zone_info = self.cn.get_zone_info(zone)
        return zone_info.get("IsSignalDetected", None)

    def assert_signal_presence(self, zone, expected=True):
        """Assert CresNext IsSignalDetected matches expected value for a zone."""
        if self.cn is None:
            return
        detected = self.is_signal_detected(zone)
        label = "present" if expected else "absent"
        assert detected is expected, (
            f"Zone {zone}: IsSignalDetected={detected}, expected {expected} "
            f"(signal should be {label})"
        )
        logger.info("Zone %d: IsSignalDetected=%s ✓", zone, detected)

    def set_input_mute_cresnext(self, input_num, muted):
        """Mute/unmute an input source via CresNext (1-indexed)."""
        return self.cn.set_input_mute(input_num, muted)

    # ------------------------------------------------------------------
    # Ducker / Limiter / AGC
    # ------------------------------------------------------------------
    def get_ducker(self, channel):
        return self.ssh.execute(f"dsp duc {channel}")

    def get_limiter(self, channel, lim_type=0):
        return self.ssh.execute(f"dsp lim {channel} {lim_type}")

    def get_agc(self, channel):
        return self.ssh.execute(f"dsp agc {channel}")

    # ------------------------------------------------------------------
    # Amplifier control
    # ------------------------------------------------------------------
    def get_amp_status(self):
        return self.ssh.execute("ampctrl")

    def get_amp_faults(self):
        return self.ssh.execute("ampctrl FaultSt")

    def get_dac_status(self):
        return self.ssh.execute("ampctrl DacIceStatus")

    # ------------------------------------------------------------------
    # State reading and measurement
    # ------------------------------------------------------------------
    def read_dsp_state(self):
        """Read and parse the full DSP state table."""
        raw = self.ssh.execute("dsp")
        return parse_dsp_output(raw)

    def read_mixer_state(self):
        """Read and parse the mixer matrix."""
        raw = self.ssh.execute("dsp mix")
        return parse_mixer_output(raw)

    def measure_output_level(self, output_name, settle_time=None):
        """Read the output level for a named output (e.g. 'A1L')."""
        if settle_time is None:
            settle_time = self.settings["signal_settle_time_s"]
        time.sleep(settle_time)
        state = self.read_dsp_state()
        if output_name in state.outputs:
            return state.outputs[output_name].output_db
        return float("-inf")

    def measure_mixer_level(self, output_name, settle_time=None):
        """Read the mixer (pre-processing) output level."""
        if settle_time is None:
            settle_time = self.settings["signal_settle_time_s"]
        time.sleep(settle_time)
        state = self.read_dsp_state()
        if output_name in state.outputs:
            return state.outputs[output_name].ducker_db
        return float("-inf")

    def measure_input_level(self, input_name, settle_time=None):
        """Read the measured level at an input channel."""
        if settle_time is None:
            settle_time = self.settings["signal_settle_time_s"]
        time.sleep(settle_time)
        state = self.read_dsp_state()
        if input_name in state.inputs:
            return state.inputs[input_name].level_db
        return float("-inf")

    # ------------------------------------------------------------------
    # Convenience: full signal path test
    # ------------------------------------------------------------------
    def inject_and_measure(self, input_ch, output_ch, output_name,
                           freq_hz=None, tone_gain_db=None, settle_time=None):
        """
        Inject a tone on input_ch, route to output_ch, measure the output level.
        Returns (state, output_level_db).
        """
        freq = freq_hz or self.settings["default_tone_freq_hz"]
        gain = tone_gain_db or self.settings["default_tone_gain_db"]

        self.start_tone(input_ch, freq, gain)
        self.set_mixer(input_ch, output_ch, 0)

        if settle_time is None:
            settle_time = self.settings["signal_settle_time_s"]
        time.sleep(settle_time)

        state = self.read_dsp_state()
        level = float("-inf")
        if output_name in state.outputs:
            level = state.outputs[output_name].output_db

        return state, level

    def cleanup_signal(self, input_ch, output_ch):
        """Stop tone and clear mixer route."""
        self.stop_tone(input_ch)
        self.clear_mixer(input_ch, output_ch)

    # ------------------------------------------------------------------
    # Device state management
    # ------------------------------------------------------------------
    def restore_defaults(self):
        """Restore DSP to a known default state."""
        # Stop any active tones
        for ch in range(29):
            try:
                self.stop_tone(ch)
            except Exception:
                pass
        # Reset input gain on physical channels
        for ch in range(8):
            try:
                self.set_input_gain(ch, 0)
            except Exception:
                pass
        # Reset zone audio properties via CresNext
        if self.cn:
            for zone in range(1, self.cfg.get("zones", 4) + 1):
                try:
                    self.cn.set_zone_audio(
                        zone,
                        Volume=800,
                        IsMuted=False,
                        Balance=0,
                        Bass=0,
                        Treble=0,
                        DelayInms=0,
                        IsLoudnessEnabled=False,
                        ToneProfile="Off",
                        NightMode="Off",
                    )
                except Exception:
                    pass
        logger.info("DSP defaults restored")

    def get_device_version(self):
        return self.ssh.get_version()

    @staticmethod
    def level_within_tolerance(actual, expected, tolerance=1.0):
        """Check if a measured level is within tolerance of expected."""
        if math.isinf(expected) and math.isinf(actual):
            return True
        if math.isinf(expected) or math.isinf(actual):
            return False
        return abs(actual - expected) <= tolerance
