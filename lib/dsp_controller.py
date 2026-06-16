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
from .test_trace import log_event

logger = logging.getLogger(__name__)


class DSPController:
    """Controls the DSP on a DM-NAX device via SSH console and CresNext REST API."""

    # Models that use the fw42 dual-SHARC platform with separate 8x8 mixer
    # blocks and require MIXER_CFG_CH_OUT to activate zone-chain processing.
    _FW42_MODELS = {"8ZSA", "4ZSP"}

    def __init__(self, ssh, device_cfg, test_settings, cresnext=None):
        self.ssh = ssh
        self.cfg = device_cfg
        self.settings = test_settings
        self.sig_ch = device_cfg["signal_generator"]["channel"]
        self.cn = cresnext  # CresNextClient for zone property control
        self._model = str(device_cfg.get("model", "")).upper()

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
        """Start a tone on all signal generator channels for the device.

        On dual-DSP-block devices (8ZSA), starts the tone on both the DSP0
        channel and the DSP1 channel so that outputs on either block can
        receive the signal.
        """
        freq = freq_hz or self.settings["default_tone_freq_hz"]
        gain = gain_db or self.settings["default_tone_gain_db"]
        log_event("SETUP", f"start_sig_tone freq={freq}Hz gain={gain}dB")
        self.start_tone(self.sig_ch, freq, gain)
        dsp1 = self.cfg.get("signal_generator_dsp1")
        if dsp1:
            self.start_tone(dsp1["channel"], freq, gain)

    def stop_sig_tone(self):
        log_event("CLEANUP", "stop_sig_tone")
        self.stop_tone(self.sig_ch)
        dsp1 = self.cfg.get("signal_generator_dsp1")
        if dsp1:
            self.stop_tone(dsp1["channel"])
        self.clear_all_sig_routes()

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

    def set_mixer_output(self, output_ch, active_input, gain_db=0):
        """Program a full output channel via MIXER_CFG_CH_OUT (dsp mixout).

        This sends AUDIO_DSP_CMD_MIXER_CFG_CH_OUT which activates the entire
        output processing chain (PEQ, Bass/Treble, Volume, Limiter) on fw42.
        Unlike 'dsp mix' (MIXER_CFG_NODE) which only sets a single crosspoint,
        this command programs all input gains for the output and enables
        zone-chain processing.

        active_input is the input channel index *within the DSP block* (0-7).
        For dual-block devices, dsp_test handles block selection automatically
        based on output_ch (0-7 = block 0, 8-15 = block 1).
        """
        num_inputs = 8  # MAXIMUM_CHANNEL_COUNT per DSP block
        # Build gain list: active_input gets gain_db, all others muted
        gains = ["-200"] * num_inputs
        # active_input may be >=8 for block-1 (e.g. ch8 = T2L); remap to block-local index
        local_input = active_input % num_inputs
        gains[local_input] = str(gain_db)
        gains_str = " ".join(gains)
        cmd = f"dsp mixout {output_ch} {gains_str}"
        out = self.ssh.execute(cmd, timeout=15)
        logger.info("MixerOutput: out=%d active_in=%d (local=%d) @ %s dB",
                    output_ch, active_input, local_input, gain_db)
        return out

    def mute_mixer_output(self, output_ch):
        """Mute all inputs to a single output via MIXER_CFG_CH_OUT."""
        num_inputs = 8
        gains_str = " ".join(["-200"] * num_inputs)
        cmd = f"dsp mixout {output_ch} {gains_str}"
        return self.ssh.execute(cmd, timeout=15)

    def clear_all_sig_routes(self):
        """Clear signal generator from ALL mixer outputs.

        On fw42 dual-block devices (8ZSA/4ZSP), uses per-node 'dsp mix'
        (MIXER_CFG_NODE) to clear only same-block crosspoints for each
        signal generator.  Cross-block clears (e.g. dsp mix 8 2 -200) are
        invalid and can hang the SPI bus.

        IMPORTANT: Do NOT use 'dsp mixout' (MIXER_CFG_CH_OUT) here — it
        resets the output channel's processing state on the SHARC firmware,
        wiping zone-chain (EQ/Bass/Treble) configuration.

        On fw21 devices, uses per-node 'dsp mix' which is safe (single block).
        """
        num_outputs = self.cfg.get("mixer_outputs", 10)

        if self._model in self._FW42_MODELS:
            # Block 0: sig_ch routes to outputs 0-7 only
            block_size = 8
            for out in range(min(block_size, num_outputs)):
                self.ssh.execute(f"dsp mix {self.sig_ch} {out} -200", timeout=10)
            logger.info("Cleared sig_ch %d -> outputs 0-%d (block 0)",
                        self.sig_ch, min(block_size, num_outputs) - 1)
            # Block 1: if dual-block, clear dsp1 sig_ch to outputs 8-15
            dsp1 = self.cfg.get("signal_generator_dsp1")
            if dsp1 and num_outputs > block_size:
                sig_ch1 = dsp1["channel"]
                for out in range(block_size, num_outputs):
                    self.ssh.execute(f"dsp mix {sig_ch1} {out} -200", timeout=10)
                logger.info("Cleared sig_ch %d -> outputs %d-%d (block 1)",
                            sig_ch1, block_size, num_outputs - 1)
        else:
            # fw21: single block, per-node clear is fine
            for out in range(num_outputs):
                self.ssh.execute(f"dsp mix {self.sig_ch} {out} -200", timeout=10)
            logger.info("Cleared all %d sig routes for ch %d", num_outputs, self.sig_ch)

    def _set_tone_source_for_zone(self, zone):
        """Route a zone to tone input using the best CresNext path for platform mode.

        8ZSA/4ZSP fw42 devices require AvMatrixRouting to activate zone-chain
        processing (PEQ, Bass/Treble).  To force DspAudioCtl to actually
        re-program (even if already set to the same source), we first route
        to a different valid source then back to the desired input.

        IMPORTANT: Setting AvMatrixRouting triggers HandleNewRoute which resets
        the zone volume to default (~30%).  Callers MUST set Volume=800 AFTER
        this method returns.  A brief settle delay is included so the async
        volume reset completes before the caller can override it.
        """
        if self.cn is None:
            return

        tone_input = self.cfg.get("dsp_tone_input", "Input01")
        route_settle = self.settings.get("route_settle_time_s", 0.5)

        if self._model in self._FW42_MODELS:
            # Force a genuine route change by toggling to a different valid
            # source first.  "None" is ignored by DspAudioCtl; we need a real
            # input like "Input02" (physically silent if nothing connected).
            toggle_input = "Input02" if tone_input != "Input02" else "Input03"
            try:
                self.cn.set_zone_source(zone, toggle_input)
            except Exception:
                pass
            time.sleep(0.2)
            try:
                self.cn.set_zone_sources_streamrouting({int(zone): tone_input})
            except Exception as e:
                logger.warning(
                    "StreamRoutings path failed for Zone%d -> %s (%s); falling back",
                    zone,
                    tone_input,
                    e,
                )
                self.cn.set_zone_source(zone, tone_input)
            time.sleep(route_settle)
            return

        self.cn.set_zone_source(zone, tone_input)
        time.sleep(route_settle)

    def route_sig_to_output(self, output_ch, gain_db=0):
        """Route signal generator to a specific output channel.

        On fw42 devices, first sets CresNext AvMatrixRouting so the zone
        chain (EQ, Bass/Treble, Volume, etc.) is active for the tone input,
        then clears stale mixer routes and sets the one crosspoint needed
        to deliver the tone to the output measurement point.

        On fw21 devices, routes via the DSP mixer crosspoint which feeds
        into the zone chain on that firmware architecture.
        """
        log_event("SETUP", f"route_sig_to_output ch={output_ch} gain={gain_db}dB")
        if self._model in self._FW42_MODELS:
            if self.cn is not None:
                zone = self.zone_for_output(output_ch)
                max_zone = self.cfg.get("zones", 4)
                if 1 <= zone <= max_zone:
                    self._set_tone_source_for_zone(zone)
            # Use MIXER_CFG_NODE (dsp mix) — NOT MIXER_CFG_CH_OUT (dsp mixout).
            # MIXER_CFG_CH_OUT resets the output processing state on the SHARC,
            # wiping zone-chain (EQ/Bass/Treble) configuration.
            # MIXER_CFG_NODE sets a single crosspoint without disturbing output
            # processing — AvMatrixRouting activates zone-chain separately.
            self.clear_all_sig_routes()
            sig_ch = self.sig_ch_for_output(output_ch)
            return self.set_mixer(sig_ch, output_ch, gain_db)
        sig_ch = self.sig_ch_for_output(output_ch)
        return self.set_mixer(sig_ch, output_ch, gain_db)

    def route_sig_to_outputs(self, output_chs, gain_db=0):
        """Route signal generator to multiple output channels simultaneously.

        Unlike route_sig_to_output() which clears all crosspoints before
        setting one, this method clears once then sets ALL requested
        crosspoints — avoiding the second call wiping the first.
        """
        log_event("SETUP", f"route_sig_to_outputs chs={output_chs} gain={gain_db}dB")
        if self._model in self._FW42_MODELS:
            if self.cn is not None:
                zones_done = set()
                max_zone = self.cfg.get("zones", 4)
                for out in output_chs:
                    zone = self.zone_for_output(out)
                    if 1 <= zone <= max_zone and zone not in zones_done:
                        self._set_tone_source_for_zone(zone)
                        zones_done.add(zone)
            self.clear_all_sig_routes()
            for out in output_chs:
                sig_ch = self.sig_ch_for_output(out)
                self.set_mixer(sig_ch, out, gain_db)
            return
        for out in output_chs:
            sig_ch = self.sig_ch_for_output(out)
            self.set_mixer(sig_ch, out, gain_db)

    def clear_sig_route(self, output_ch):
        log_event("CLEANUP", f"clear_sig_route output_ch={output_ch}")
        sig_ch = self.sig_ch_for_output(output_ch)
        return self.clear_mixer(sig_ch, output_ch)

    def sig_ch_for_output(self, output_idx):
        """Return the correct signal generator channel for a given output index.

        On dual-DSP-block devices (8ZSA), outputs 0-7 live on block 0
        (use signal_generator.channel) and outputs 8-15 live on block 1
        (use signal_generator_dsp1.channel).  A tone started on block 0
        cannot be routed to block 1 outputs and vice versa.
        """
        if output_idx >= 8:
            dsp1 = self.cfg.get("signal_generator_dsp1")
            if dsp1:
                return dsp1["channel"]
        return self.sig_ch

    # ------------------------------------------------------------------
    # Input compensation / gain
    # ------------------------------------------------------------------
    def set_input_gain(self, channel, gain_db, trace_source="SSH"):
        """Set input compensation (gain offset in dB) on a physical input channel.

        Some images reject one syntax variant regardless of reported fw.
        Try the predicted command first, then fallback to the alternate form.
        """
        fw = self.cfg.get("dsp_fw_version", 21)
        primary = f"dsp gain {channel} {gain_db}" if fw >= 42 else f"dsp gain {channel} set {gain_db}"
        fallback = f"dsp gain {channel} set {gain_db}" if fw >= 42 else f"dsp gain {channel} {gain_db}"

        out = self.ssh.execute(primary, trace_source=trace_source)
        low = out.lower()
        if "invalid num format" in low or "invalid command" in low:
            out = self.ssh.execute(fallback, trace_source=trace_source)
            low = out.lower()
            if "invalid num format" in low or "invalid command" in low:
                raise RuntimeError(
                    f"Input gain rejected for ch={channel} gain={gain_db}; "
                    f"tried '{primary}' and '{fallback}'"
                )

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

    def is_signal_clipping(self, zone):
        """Return CresNext IsSignalClipping flag for a zone."""
        if self.cn is None:
            return None
        zone_info = self.cn.get_zone_info(zone)
        return zone_info.get("IsSignalClipping", None)

    def assert_signal_presence(self, zone, expected=True):
        """Assert CresNext IsSignalDetected matches expected value for a zone."""
        if self.cn is None:
            return
        label = "present" if expected else "absent"
        log_event("VALIDATE", f"check IsSignalDetected: zone={zone} expected={expected}")

        # Poll briefly for status convergence after route/level changes.
        deadline = time.time() + 3.0
        detected = None
        while time.time() < deadline:
            detected = self.is_signal_detected(zone)
            if detected is expected:
                logger.info("Zone %d: IsSignalDetected=%s ✓", zone, detected)
                log_event(
                    "VALIDATE",
                    f"check IsSignalDetected: zone={zone} actual={detected} result=PASS",
                )
                return
            time.sleep(0.25)

        # Include DSP level for diagnosis but do not bypass status correctness.
        out_name = f"A{zone}L"
        level = self.measure_output_level(out_name, settle_time=0.1)
        log_event(
            "VALIDATE",
            (
                f"check IsSignalDetected: zone={zone} actual={detected} "
                f"expected={expected} result=FAIL {out_name}={level:.2f}dB"
            ),
        )

        assert detected is expected, (
            f"Zone {zone}: IsSignalDetected={detected}, expected {expected} "
            f"(signal should be {label}); {out_name}={level:.2f} dB"
        )

    def assert_signal_not_clipping(self, zone):
        """Assert CresNext IsSignalClipping is not True for a zone."""
        if self.cn is None:
            return

        log_event("VALIDATE", f"check IsSignalClipping: zone={zone} expected=False")

        # Poll briefly so transient status updates can settle.
        deadline = time.time() + 3.0
        clipping = None
        while time.time() < deadline:
            clipping = self.is_signal_clipping(zone)
            if clipping is not True:
                log_event(
                    "VALIDATE",
                    f"check IsSignalClipping: zone={zone} actual={clipping} result=PASS",
                )
                return
            time.sleep(0.25)

        out_name = f"A{zone}L"
        level = self.measure_output_level(out_name, settle_time=0.1)
        log_event(
            "VALIDATE",
            (
                f"check IsSignalClipping: zone={zone} actual={clipping} "
                f"expected=False result=FAIL {out_name}={level:.2f}dB"
            ),
        )
        assert clipping is not True, (
            f"Zone {zone}: IsSignalClipping={clipping}, expected not True; "
            f"{out_name}={level:.2f} dB"
        )

    def set_input_mute_cresnext(self, input_num, muted):
        """Mute/unmute an input source via CresNext (1-indexed)."""
        return self.cn.set_input_mute(input_num, muted)

    def set_input_compensation_cresnext(self, input_num, compensation):
        """Set input SourceAudio Compensation via CresNext (1-indexed input)."""
        return self.cn.set_input_compensation(input_num, compensation)

    def get_input_source_audio(self, input_num):
        """Read input SourceAudio via CresNext (1-indexed input)."""
        return self.cn.get_input_source_audio(input_num)

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
        state = parse_dsp_output(raw)
        # Log a compact single-line summary of all output levels.
        if state.outputs:
            parts = []
            for name, out in sorted(state.outputs.items()):
                if name.startswith("Z"):   # skip fw42 zone-name aliases (Z1L…)
                    continue
                o_db = f"{out.output_db:.1f}" if out.output_db > float('-inf') else "-inf"
                parts.append(f"{name}={o_db}")
            log_event("SSH", " | ".join(parts))
        return state

    def read_mixer_state(self):
        """Read and parse the mixer matrix."""
        raw = self.ssh.execute("dsp mix")
        return parse_mixer_output(raw)

    def measure_output_level(self, output_name, settle_time=None, retries=2):
        """Read the output level for a named output (e.g. 'A1L').

        On 8ZSA, DSP block 1 (zones 5-8) intermittently omits output rows
        from the ``dsp`` state table.  When the output is missing, retry
        up to *retries* times with a short delay before giving up.
        """
        if settle_time is None:
            settle_time = self.settings["signal_settle_time_s"]
        time.sleep(settle_time)
        for attempt in range(1 + retries):
            state = self.read_dsp_state()
            if output_name in state.outputs:
                level = state.outputs[output_name].output_db
                log_event(
                    "VALIDATE",
                    f"check output level: output={output_name} measured={level:.2f}dB",
                )
                return level
            if attempt < retries:
                log_event(
                    "VALIDATE",
                    f"output {output_name} missing in DSP state, retry {attempt + 1}/{retries}",
                )
                time.sleep(1.0)
        log_event(
            "VALIDATE",
            f"check output level: output={output_name} missing_in_dsp_state after "
            f"{retries} retries -> measured=-inf",
        )
        return float("-inf")

    def measure_output_levels_batch(self, output_names, settle_time=None, retries=2):
        """Read levels for multiple outputs from a single DSP state snapshot.

        Use this instead of calling measure_output_level() repeatedly when
        all channels must be sampled at the same instant (e.g. stereo L+R).
        Returns a dict mapping output_name -> level_db.

        On 8ZSA, DSP block 1 intermittently omits output rows.  When any
        requested output is missing, retry up to *retries* times.
        """
        if settle_time is None:
            settle_time = self.settings["signal_settle_time_s"]
        time.sleep(settle_time)
        for attempt in range(1 + retries):
            state = self.read_dsp_state()
            missing = [n for n in output_names if n not in state.outputs]
            if not missing:
                break
            if attempt < retries:
                log_event(
                    "VALIDATE",
                    f"batch: {missing} missing in DSP state, retry {attempt + 1}/{retries}",
                )
                time.sleep(1.0)
        result = {}
        for name in output_names:
            if name in state.outputs:
                level = state.outputs[name].output_db
                log_event("VALIDATE", f"check output level: output={name} measured={level:.2f}dB")
                result[name] = level
            else:
                log_event("VALIDATE", f"check output level: output={name} missing_in_dsp_state -> measured=-inf")
                result[name] = float("-inf")
        return result

    def measure_input_levels_batch(self, input_names, settle_time=None):
        """Read levels for multiple inputs from a single DSP state snapshot.

        Stereo companion to measure_output_levels_batch for fw21 devices.
        Returns a dict mapping input_name -> level_db.
        """
        if settle_time is None:
            settle_time = self.settings["signal_settle_time_s"]
        time.sleep(settle_time)
        state = self.read_dsp_state()
        result = {}
        for name in input_names:
            if name in state.inputs:
                level = state.inputs[name].level_db
                log_event("VALIDATE", f"check input level: input={name} measured={level:.2f}dB")
                result[name] = level
            else:
                log_event("VALIDATE", f"check input level: input={name} missing_in_dsp_state -> measured=-inf")
                result[name] = float("-inf")
        return result

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
