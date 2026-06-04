"""
Test: Media Streaming Playback
Category: Streaming
═══════════════════════════════════════════════════════════════

Signal path diagram – how audio flows from the test host to the
DSP measurement point.  Exact port counts and input indices
vary by device model:

  Device          Streaming inputs     Zones
  ──────────────  ──────────────────   ─────
  DM-NAX-4ZSA    Input05 … Input08    1-4
  DM-NAX-8ZSA    Input05 … Input12    1-8
  DM-NAX-4ZSP    Input05 … Input12    1-8

  TEST HOST                                   DM-NAX
  ┌────────────────────────┐                  ┌──────────────────────────────────────────┐
  │  generate_tones.py     │                  │                                          │
  │  ┌──────────────────┐  │                  │  MediaStreamerV2 (Node.js / Express)      │
  │  │ freq_-20dBFS.wav │  │  HTTP GET        │  ┌────────────────────────────────────┐   │
  │  │ (per-zone file)  │◀─┼──────────────────┼──│ Port 60001+ (one per zone)        │   │
  │  └──────────────────┘  │  WAV stream      │  └───────────┬────────────────────────┘   │
  │  ThreadingHTTPServer   │                  │              │ audio-player / GStreamer    │
  │  0.0.0.0:8088          │                  │              ▼                            │
  └────────────────────────┘                  │  ┌───────────────────────┐                │
                                              │  │ ALSA PCM output       │                │
  TEST HOST (pytest)                          │  │ per-zone ALSA device  │                │
  ┌────────────────────────┐                  │  └───────────┬──────────┘                │
  │ 1. CresNext API:       │  HTTP POST/PUT   │              │                            │
  │    Route Zone N →      │─────────────────▶│              ▼                            │
  │    streaming input     │                  │  ┌───────────────────────┐                │
  │                        │                  │  │ DSP FPGA              │                │
  │ 2. Streaming API:      │  HTTP POST/PUT   │  │                       │                │
  │    POST /services/     │─────────────────▶│  │ Mux inputs (pre-DSP): │                │
  │      generic           │                  │  │   M{n}L / M{n}R      │◀── measured    │
  │    PUT  /services/     │                  │  │   (one pair per zone) │    here        │
  │      generic/source    │                  │  │                       │                │
  │    PUT  /player/play   │                  │  │ Amp outputs (post-DSP)│                │
  │                        │                  │  │   A{n}L / A{n}R      │                │
  │ 3. DSP CRPC query:     │  TCP :41794      │  │   (one pair per zone) │                │
  │    measure_input_level │─────────────────▶│  └───────────────────────┘                │
  │    ("M{n}L")           │                  └──────────────────────────────────────────┘
  │                        │
  │ 4. Assert:             │
  │    -45 dB < level      │
  │          < -20 dB      │
  └────────────────────────┘

Why we measure at the DSP mux inputs (M{n}), not amp outputs (A{n}):
  Streaming audio enters the DSP board directly from ALSA — it does NOT
  pass through any physical connector (SPDIF, Toslink, Line-in).  The DSP
  FPGA exposes these internal sources at mux inputs M{n}L/M{n}R.
  A -20 dBFS WAV file arrives at ~-34 dB on these mux inputs due to the
  internal gain staging.  The amp outputs (A{n}) depend on crosspoint
  routing, volume, EQ, and other DSP blocks — making them unreliable for
  verifying that streaming audio is actually present.

Verification strategy:
  • Level check:    measure_input_level("M{n}L") must be between -45 and
                    -20 dB.  A -20 dBFS source typically reads ~-34 dB.
  • Isolation:      Each active zone has signal on its own M{n} pair;
                    left/right stereo balance is within 2 dB.
  • Silence check:  After stopping all players, M{n}L must drop below
                    -100 dB (confirming clean teardown).
═══════════════════════════════════════════════════════════════
"""
import pytest
import time
import logging

from lib.generate_tones import tone_filename
from lib.streaming_client import detect_mediaplayermode, MODE_MP1
from lib.test_trace import log_event

logger = logging.getLogger(__name__)

# Expected output level range — streaming at -20 dBFS through the DSP
# The spreadsheet uses -35 to -38 dB with Audio Precision measuring externally.
# Streaming audio from MediaStreamerV2 arrives at DSP mux inputs M1-M4
# at approximately -34 dB for -20 dBFS source material.
LEVEL_UPPER_DB = -15.0
LEVEL_LOWER_DB = -45.0
SILENCE_FLOOR_DB = -100.0
PLAY_SETTLE_S = 8.0        # Time for streaming to stabilise
STOP_SETTLE_S = 20.0       # Time for output to drop after stop.
# On fw42 (8ZSA) the ALSA loopback buffer drains over a few seconds after
# GStreamer stops.  Poll the amp outputs at this interval and wait up to the
# timeout before clearing AV matrix routes so dspaudioctl's OUTPUT_GAIN reset
# does not catch residual audio in the buffer (would create a ~-70 dB
# peak-hold artifact that persists indefinitely in the DSP).
_ALSA_DRAIN_THRESHOLD_DB = -60.0
_ALSA_DRAIN_TIMEOUT_S = 15.0
_ALSA_DRAIN_POLL_S = 0.5


def _streaming_zones(device_cfg):
    """Return the streaming zone config dict from devices.yaml.

    Keys are normalised to int so lookups work regardless of
    whether YAML loaded them as int or str.
    """
    streaming = device_cfg.get("streaming")
    if not streaming:
        pytest.skip("No streaming config in device profile")
    zone_map = {int(k): v for k, v in streaming["zones"].items()}
    selected = set(device_cfg.get("selected_zones", zone_map.keys()))
    return {z: cfg for z, cfg in zone_map.items() if z in selected}


def _audio_url(host_ip, port, freq_hz):
    """Build the HTTP URL for a test tone WAV file."""
    return f"http://{host_ip}:{port}/{tone_filename(freq_hz)}"


def _streaming_inputs_for_zone(zone_num, device_cfg=None):
    """Return (left, right) DSP measurement point names for streaming zone.

    4ZSA (fw21): Streaming audio lands on M{n}L / M{n}R mux inputs.
    8ZSA (fw42): There are no M{n} mux inputs in the DSP table;
                 streaming audio is measured at the amp outputs A{n}L / A{n}R.
    """
    if device_cfg and device_cfg.get("dsp_fw_version", 21) >= 42:
        return f"A{zone_num}L", f"A{zone_num}R"
    return f"M{zone_num}L", f"M{zone_num}R"


def _wait_alsa_drain(dsp, zones, device_cfg):
    """Poll DSP amp outputs until all zones drain below _ALSA_DRAIN_THRESHOLD_DB.

    On fw42 (8ZSA) the ALSA loopback buffer takes a few seconds to drain after
    GStreamer transitions to NULL state.  Clearing the AV matrix route before
    the buffer empties resets OUTPUT_GAIN to defaultVolume (-50 dB) while audio
    is still present; the DSP peak-hold captures the resulting transient
    (~-70 dB) and does not self-clear.  Waiting here ensures the buffer is
    empty before the route-clear gain change occurs.

    No-ops on fw21 (4ZSA): streaming is measured at pre-DSP mux inputs and
    the route-clear gain race does not apply.
    """
    if device_cfg.get("dsp_fw_version", 21) < 42:
        return
    deadline = time.monotonic() + _ALSA_DRAIN_TIMEOUT_S
    pending = list(zones)
    while pending and time.monotonic() < deadline:
        still_draining = []
        for zone in pending:
            left, _ = _streaming_inputs_for_zone(zone, device_cfg)
            try:
                level = dsp.measure_output_level(left, settle_time=0.0)
            except Exception:
                continue  # can't measure; don't block on it
            if level < _ALSA_DRAIN_THRESHOLD_DB:  # also true for -inf
                logger.info("Zone %d: ALSA drained (%.2f dB)", zone, level)
            else:
                still_draining.append(zone)
        pending = still_draining
        if pending:
            time.sleep(_ALSA_DRAIN_POLL_S)
    if pending:
        logger.warning(
            "ALSA drain timeout (%.1fs) for zones %s — continuing with route clear",
            _ALSA_DRAIN_TIMEOUT_S, pending,
        )


def _measure_streaming_level(dsp, name, device_cfg, settle_time=1.0):
    """Measure streaming level at the appropriate DSP point.

    4ZSA: measure_input_level (M{n}L mux input, pre-DSP)
    8ZSA: measure_output_level (A{n}L amp output, post-DSP zone chain)
    """
    if device_cfg.get("dsp_fw_version", 21) >= 42:
        return dsp.measure_output_level(name, settle_time=settle_time)
    return dsp.measure_input_level(name, settle_time=settle_time)


def _resolve_stream_audio_source(device_cfg, zone_num, default_input, mode):
    """Resolve per-zone AudioSource for current media-player mode.

    On fw42 iMX8 devices (8ZSA, 4ZSP) in MP1 mode, physical inputs occupy
    Input01-08 and the eight MediaStreamer zone players are mapped at
    Input09-16.  Zone N player connects as Input{N+8}.

    On fw21 (4ZSA) the streaming inputs are Input05-08 (Input{N+4}), which
    matches the default_input values in the devices.yaml config.
    """
    model = str(device_cfg.get("model", "")).upper()
    if mode == MODE_MP1 and model in {"8ZSA", "4ZSP"}:
        return f"Input{zone_num + 8:02d}"
    return default_input


def _apply_stream_routes(cresnext, device_cfg, zones, mode):
    """Apply zone->AudioSource routing with MP1-specific source mapping."""
    model = str(device_cfg.get("model", "")).upper()
    if mode == MODE_MP1 and model in {"8ZSA", "4ZSP"}:
        for zone, zcfg in sorted(zones.items()):
            src = _resolve_stream_audio_source(device_cfg, zone, zcfg["input"], mode)
            cresnext.set_zone_source(zone, src)
            log_event("ROUTE", f"Zone{zone}: individual route -> {src} (mode={mode})")
            logger.info("Routed Zone %d -> %s (MP1 individual route)", zone, src)
        return

    for zone, zcfg in sorted(zones.items()):
        input_name = _resolve_stream_audio_source(device_cfg, zone, zcfg["input"], mode)
        cresnext.set_zone_source(zone, input_name)
        log_event("ROUTE", f"Zone{zone}: individual route -> {input_name} (mode={mode})")
        logger.info("Routed Zone %d -> %s", zone, input_name)


def _fmt_db(level):
    if level == float("-inf"):
        return "-inf"
    return f"{level:.2f}dB"


def _summarize_player_status(status):
    payload = status.get("payload", {}) if isinstance(status, dict) else {}
    player = payload.get("player", {}) if isinstance(payload, dict) else {}
    state = player.get("state", {}) if isinstance(player, dict) else {}
    status_info = player.get("status", {}) if isinstance(player, dict) else {}
    timer = player.get("timer", {}) if isinstance(player, dict) else {}
    return (
        f"state={state.get('name', 'UNKNOWN')}({state.get('value', 'n/a')}) "
        f"pid={player.get('pid', 'n/a')} elapsed={timer.get('elapsed', 'n/a')} "
        f"source={payload.get('source', 'n/a')} "
        f"code={status_info.get('code', 'n/a')} retry={status_info.get('retry', 'n/a')}"
    )


def _log_mixer_diagnostics(label, dsp, device_cfg):
    """Log active signal-generator mixer crosspoints for root-cause analysis."""
    try:
        nodes = dsp.read_mixer_state()
        sig_inputs = [int(device_cfg["signal_generator"]["channel"])]
        dsp1 = device_cfg.get("signal_generator_dsp1")
        if dsp1:
            sig_inputs.append(int(dsp1["channel"]))
        active = [
            f"in{n.input_idx}:{n.input_name}->out{n.output_idx}:{n.output_name}@{n.gain_db:.1f}"
            for n in nodes
            if n.input_idx in sig_inputs and n.gain_db > -190.0
        ]
        log_event("DIAG", f"{label}: active_sig_mixer_routes={active if active else 'none'}")
    except Exception as e:
        log_event("DIAG", f"{label}: mixer_diag_error={e}")


def _log_zone8_dsp_pipeline(label, dsp, device_cfg):
    """Capture the full DSP processing pipeline state for Zone 8.

    Zone 8 on 8ZSA = global channels 14 (left) / 15 (right), which map to
    DSP1 ch6/ch7 locally.  ALSA loopback substream = sub7.

    Logs every gain stage, ducker, limiter, AGC, route source, single-channel
    VU readouts and ALSA substream state to determine whether a residual
    signal after streaming stop originates from the DSP firmware/FPGA output
    chain or from a software source.

    NOTE — commands that are NOT valid subcommands for DSP_8ZSA fw47:
      - 'dsp inp'  : not implemented; only the FW version banner is printed.
      - 'dsp mix N': with a single integer arg reads crosspoint [N,0] only,
                     not the full crosspoint table.  Use dsp.read_mixer_state()
                     via Python instead, or 'dsp mix N out_ch' for specifics.
    """
    try:
        # Zone 8 on 8ZSA = global ch14 (left), ch15 (right) — DSP1 ch6/ch7.
        streaming_cfg = device_cfg.get("streaming", {})
        zone8_input = streaming_cfg.get("zones", {}).get(8, {}).get("input", "Input13")

        # 1. All gain types for Zone 8 left (ch14)
        gain_types = [
            (0, "input"), (1, "output"), (2, "extra"), (3, "rava"),
            (4, "lineout"), (5, "emergency"), (6, "balance"), (7, "outputTrim"),
        ]
        gain_results = []
        for gtype, gname in gain_types:
            try:
                out = dsp.ssh.execute(f"dsp gain 14 {gtype}", timeout=5)
                gain_results.append(f"{gname}={out.strip().split('gain')[-1].strip() if 'gain' in out else out.strip()}")
            except Exception:
                gain_results.append(f"{gname}=err")
        log_event("DIAG", f"{label}: zone8_gains ch14: {' | '.join(gain_results)}")

        # 2. Route source for Zone 8 left (ch14)
        try:
            route_out = dsp.ssh.execute("dsp route 14", timeout=5)
            log_event("DIAG", f"{label}: zone8_route ch14: {route_out.strip()}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_route_err: {e}")

        # 3. Ducker VU level — signal entering the output chain for Zone 8
        try:
            duc_out = dsp.ssh.execute("dsp duc 14", timeout=5)
            for line in duc_out.splitlines():
                if "vu_level" in line:
                    log_event("DIAG", f"{label}: zone8_ducker_vu: {line.strip()}")
                    break
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_duc_err: {e}")

        # 4. Limiter VU level for Zone 8
        try:
            lim_out = dsp.ssh.execute("dsp lim 14", timeout=5)
            for line in lim_out.splitlines():
                if "vu_level" in line:
                    log_event("DIAG", f"{label}: zone8_limiter_vu: {line.strip()}")
                    break
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_lim_err: {e}")

        # 5. ALSA Loopback card1 substream status — Zone 8 = sub7
        #    Commands 5+6 MUST use execute_bash (port 6022), NOT execute (CresNEXT CLI).
        try:
            sub_out = dsp.ssh.execute_bash(
                'out=""; '
                'for f in $(find /proc/asound/card1 -name "status" | sort); do '
                '  st=$(cat "$f" 2>/dev/null); '
                '  [ "$st" != "closed" ] && out="$out $f:$st"; '
                'done; '
                'echo "${out:-all_closed}"',
                timeout=15,
            )
            log_event("DIAG", f"{label}: zone8_alsa_loopback_open: {sub_out.strip()[:400]}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_alsa_loopback_err: {e}")

        # 6. Zone 8 specific substream (sub7) and Zone 1 (sub0) for comparison
        try:
            sub8 = dsp.ssh.execute_bash('cat /proc/asound/card1/pcm0p/sub7/status 2>/dev/null || echo missing', timeout=5)
            sub1 = dsp.ssh.execute_bash('cat /proc/asound/card1/pcm0p/sub0/status 2>/dev/null || echo missing', timeout=5)
            log_event("DIAG", f"{label}: zone8_alsa_sub7_status: {sub8.strip()}")
            log_event("DIAG", f"{label}: zone1_alsa_sub0_status: {sub1.strip()}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_alsa_sub_err: {e}")

        # 7. PIDs holding /dev/snd open (stuck GStreamer pipelines)
        try:
            snd_pids = dsp.ssh.execute_bash(
                'for pid in $(ls /proc/ | grep "^[0-9]"); do '
                '  fds=$(ls -la /proc/$pid/fd 2>/dev/null | grep "/dev/snd"); '
                '  [ -n "$fds" ] && echo "pid=$pid cmd=$(cat /proc/$pid/comm 2>/dev/null): $fds"; '
                'done || echo "none"',
                timeout=15,
            )
            log_event("DIAG", f"{label}: zone8_snd_open_pids: {snd_pids.strip()[:400] if snd_pids.strip() else 'none'}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_snd_pids_err: {e}")

        # 8. ALL active (non-silent) DSP inputs from state table.
        try:
            state = dsp.read_dsp_state()
            SILENCE_THRESH = -100.0
            active_inputs = [
                f"{name}={_fmt_db(inp.level_db)}"
                for name, inp in state.inputs.items()
                if inp.level_db is not None and inp.level_db > SILENCE_THRESH
            ]
            if active_inputs:
                log_event("DIAG", f"{label}: zone8_active_inputs (non-silent): {' | '.join(active_inputs)}")
            else:
                log_event("DIAG", f"{label}: zone8_active_inputs: all_silent")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_active_inputs_err: {e}")

        # 9. Single-channel VU readout for Zone 8 left (ch14).
        #    'dsp vu <chan> [type]' is valid for 8ZSA:
        #      type 0 = output_vu (amp output), type 3 = output_ducker_vu, type 5 = output_limiter_vu
        #    This directly interrogates the firmware register for ch14 without
        #    relying on the full dsp-state parse which can be truncated.
        try:
            vu_out = dsp.ssh.execute("dsp vu 14 0", timeout=5)   # amp output
            log_event("DIAG", f"{label}: zone8_vu_amp_ch14: {vu_out.strip()}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_vu_amp_err: {e}")
        try:
            vu_duc = dsp.ssh.execute("dsp vu 14 3", timeout=5)   # ducker
            log_event("DIAG", f"{label}: zone8_vu_ducker_ch14: {vu_duc.strip()}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_vu_ducker_err: {e}")
        try:
            vu_lim = dsp.ssh.execute("dsp vu 14 5", timeout=5)   # limiter
            log_event("DIAG", f"{label}: zone8_vu_limiter_ch14: {vu_lim.strip()}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_vu_limiter_err: {e}")

        # 10. AGC state for Zone 8 (ch14)
        try:
            agc_out = dsp.ssh.execute("dsp agc 14", timeout=5)
            for line in agc_out.splitlines():
                if "vu_level" in line or "gain" in line.lower():
                    log_event("DIAG", f"{label}: zone8_agc: {line.strip()}")
        except Exception as e:
            log_event("DIAG", f"{label}: zone8_agc_err: {e}")

        # 11. Full DSP output channel list — detects truncated state returns.
        #     On a healthy device dsp returns 16 output rows for 8ZSA.
        #     Fewer rows indicate the FPGA/driver is in a degraded state.
        try:
            full_dsp = dsp.ssh.execute("dsp", timeout=15)
            lines = full_dsp.strip().splitlines()
            log_event("DIAG", f"{label}: dsp_output_channel_count: {len(lines)} lines")
            # Log the raw rows — the last 16 are the output channel rows for 8ZSA
            row_lines = [l for l in lines if '|' in l]
            log_event("DIAG", f"{label}: dsp_output_rows: {len(row_lines)} rows | last={row_lines[-1].strip() if row_lines else 'none'}")
        except Exception as e:
            log_event("DIAG", f"{label}: dsp_all_outputs_err: {e}")

    except Exception as e:
        log_event("DIAG", f"{label}: zone8_pipeline_error: {e}")


def deep_zone8_diagnostics(dsp, device_cfg, streaming=None, cresnext=None, poll_secs=30, interval=2):
    """Poll and log Zone 8 and Zone 1 DSP/ALSA state every interval seconds for poll_secs after STOP.

    Zone 8 is on DSP1 ch6/ch7 (global ch14/ch15), ALSA sub7.
    Zone 1 is used as the reference (expected-silent) zone for comparison.
    """
    import time
    n_polls = poll_secs // interval
    logger = globals().get("logger", None)
    for i in range(n_polls):
        label = f"deep_diag_zone8_poll{i+1:02d}"
        # Full pipeline diagnostic for Zone 8
        _log_zone8_dsp_pipeline(label + "_zone8", dsp, device_cfg)
        # Zone 1 reference (ch0, sub0) — should be fully silent
        try:
            gain_types = [(0, "input"), (1, "output"), (2, "extra"), (3, "rava"),
                          (4, "lineout"), (5, "emergency"), (6, "balance"), (7, "outputTrim")]
            gain_results = []
            for gtype, gname in gain_types:
                try:
                    out = dsp.ssh.execute(f"dsp gain 0 {gtype}", timeout=5)
                    gain_results.append(f"{gname}={out.strip().split('gain')[-1].strip() if 'gain' in out else out.strip()}")
                except Exception:
                    gain_results.append(f"{gname}=err")
            log_event("DIAG", f"{label}_zone1: zone1_gains ch0: {' | '.join(gain_results)}")
            route_out = dsp.ssh.execute("dsp route 0", timeout=5)
            log_event("DIAG", f"{label}_zone1: zone1_route ch0: {route_out.strip()}")
            duc_out = dsp.ssh.execute("dsp duc 0", timeout=5)
            for line in duc_out.splitlines():
                if "vu_level" in line:
                    log_event("DIAG", f"{label}_zone1: zone1_ducker_vu: {line.strip()}")
                    break
            lim_out = dsp.ssh.execute("dsp lim 0", timeout=5)
            for line in lim_out.splitlines():
                if "vu_level" in line:
                    log_event("DIAG", f"{label}_zone1: zone1_limiter_vu: {line.strip()}")
                    break
        except Exception as e:
            log_event("DIAG", f"{label}_zone1: zone1_diag_error: {e}")
        # Log open /dev/snd PIDs
        try:
            snd_pids = dsp.ssh.execute_bash(
                'for pid in $(ls /proc/ | grep "^[0-9]"); do '
                '  fds=$(ls -la /proc/$pid/fd 2>/dev/null | grep "/dev/snd"); '
                '  [ -n "$fds" ] && echo "pid=$pid cmd=$(cat /proc/$pid/comm 2>/dev/null): $fds"; '
                'done || echo "none"',
                timeout=10,
            )
            log_event("DIAG", f"{label}: snd_open_pids: {snd_pids.strip()[:400] if snd_pids.strip() else 'none'}")
        except Exception as e:
            log_event("DIAG", f"{label}: snd_pids_diag_error: {e}")
        if logger:
            logger.info(f"Deep diag poll {i+1}/{n_polls} complete.")
        time.sleep(interval)


def _log_streaming_cleanup_diagnostics(label, streaming, cresnext, dsp, device_cfg, zones):
    """Capture player/route/DSP/mixer state around cleanup and on failures.

    This is intentionally verbose for fw42 Zone8 failures.  If A8L remains
    around -70 dB, these lines show whether the cause is a still-running
    player, stale AvMatrixRouting route, or stale DSP signal-generator mixer
    crosspoint from earlier test files.
    """
    selected = sorted(int(z) for z in device_cfg.get("selected_zones", []))
    log_event(
        "DIAG",
        f"{label}: mode={getattr(streaming, 'mode', 'unknown')} "
        f"selected_zones={selected} diag_zones={zones}",
    )

    for zone in zones:
        player = streaming.get_player(zone)
        try:
            status = player.status()
            player_summary = _summarize_player_status(status)
        except Exception as e:
            player_summary = f"status_error={e}"
        try:
            route = cresnext.get_zone_source(zone)
        except Exception as e:
            route = f"route_error={e}"
        log_event(
            "DIAG",
            f"{label}: Zone{zone} port={player.port} route={route} {player_summary}",
        )

    try:
        names = []
        for zone in zones:
            left, right = _streaming_inputs_for_zone(zone, device_cfg)
            names.extend([left, right])
        state = dsp.read_dsp_state()
        levels = []
        for name in names:
            if name in state.outputs:
                levels.append(f"{name}={_fmt_db(state.outputs[name].output_db)}")
            elif name in state.inputs:
                levels.append(f"{name}={_fmt_db(state.inputs[name].level_db)}")
            else:
                levels.append(f"{name}=missing")
        log_event("DIAG", f"{label}: dsp_levels {' | '.join(levels)}")
    except Exception as e:
        log_event("DIAG", f"{label}: dsp_diag_error={e}")

    _log_mixer_diagnostics(label, dsp, device_cfg)


class TestStreamingRouting:
    """Phase 1: Establish stream routing — zone → streaming input."""

    def test_route_zones_to_streaming(self, cresnext, device_cfg, ssh):
        """Route each zone to its streaming input via AvMatrixRouting."""
        zones = _streaming_zones(device_cfg)
        mode = detect_mediaplayermode(ssh)
        _apply_stream_routes(cresnext, device_cfg, zones, mode)

    def test_volumes_at_0db(self, cresnext, device_cfg):
        """Set all zone volumes to 0 dB (800) — baseline for level checks."""
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
        for zone in zones:
            cresnext.set_zone_audio(zone, Volume=800, IsMuted=False)
            logger.info("Zone %d volume set to 800 (0 dB)", zone)


class TestStreamingPlayback:
    """Phase 2: Start playback and verify audio output per zone."""

    def test_start_all_players(self, streaming, device_cfg, audio_file_server):
        """Start generic service, set source, and play on all streaming zones."""
        host_ip, srv_port = audio_file_server
        zones = _streaming_zones(device_cfg)

        # Phase A: Create sessions and set sources for all zones first.
        # Each setSource triggers a HEAD request on the device to resolve
        # redirects.  We do this before playing to avoid bandwidth contention.
        players_to_play = []
        for zone, zcfg in sorted(zones.items()):
            freq = zcfg["tone_hz"]
            url = _audio_url(host_ip, srv_port, freq)

            player = streaming.get_player(zone)
            player.start_service("generic")
            player.set_source(url)
            players_to_play.append((zone, freq, player))
            logger.info("Zone %d: source set to %d Hz (%s)", zone, freq, url)

        # Phase B: Play all zones
        for zone, freq, player in players_to_play:
            player.play()
            logger.info("Zone %d: play started", zone)

        # Let all streams settle
        logger.info("Waiting %.1fs for streams to settle...", PLAY_SETTLE_S)
        time.sleep(PLAY_SETTLE_S)

    def test_all_players_playing(self, streaming, device_cfg):
        """Verify all streaming players reached PLAYING state."""
        zones = _streaming_zones(device_cfg)
        for zone in sorted(zones.keys()):
            player = streaming.get_player(zone)
            # Retry a few times — player may still be buffering
            for attempt in range(3):
                if player.is_playing:
                    break
                time.sleep(3)
            assert player.is_playing, (
                f"Zone {zone} player not in PLAYING state "
                f"(state={player.state_name})"
            )
            logger.info("Zone %d: confirmed PLAYING", zone)

    @pytest.fixture(params="dynamic")
    def zone_param(self, request, device_cfg):
        """Dynamic parametrize based on device zones."""
        return request.param

    # We use a class-level approach with explicit parametrize via the
    # streaming zone config instead of fixture params.


def _make_zone_ids(device_cfg):
    """Build pytest param list from streaming config."""
    streaming = device_cfg.get("streaming", {})
    zones = streaming.get("zones", {})
    return [
        pytest.param(int(z), zcfg, id=f"Zone{z}-{zcfg['tone_hz']}Hz")
        for z, zcfg in sorted(zones.items(), key=lambda x: int(x[0]))
    ]


class TestStreamingLevels:
    """Phase 3: Measure output levels at each zone's amp outputs."""

    @pytest.mark.parametrize(
        "zone_num",
        list(range(1, 9)),  # conftest deselects zones outside --zone-mode
    )
    def test_zone_output_level(self, dsp, device_cfg, streaming,
                               audio_file_server, cresnext, zone_num):
        """Zone {zone_num} amp output must show signal within expected range."""
        zones = _streaming_zones(device_cfg)
        if zone_num not in zones:
            pytest.skip(f"Zone {zone_num} not in streaming config")

        zcfg = zones[zone_num]
        freq = zcfg["tone_hz"]
        left, right = _streaming_inputs_for_zone(zone_num, device_cfg)

        # Ensure route and volume are set
        input_name = _resolve_stream_audio_source(device_cfg, zone_num, zcfg["input"], streaming.mode)
        if streaming.mode == MODE_MP1 and str(device_cfg.get("model", "")).upper() in {"8ZSA", "4ZSP"}:
            cresnext.set_zone_source(zone_num, input_name)
            log_event("ROUTE", f"Zone{zone_num}: individual route -> {input_name} (level check)")
        else:
            cresnext.set_zone_source(zone_num, input_name)
            log_event("ROUTE", f"Zone{zone_num}: individual route -> {input_name} (level check)")
        cresnext.set_zone_audio(zone_num, Volume=800, IsMuted=False)

        # Ensure player is playing
        host_ip, srv_port = audio_file_server
        player = streaming.get_player(zone_num)
        if not player.is_playing:
            url = _audio_url(host_ip, srv_port, freq)
            player.start_streaming(url, settle_s=PLAY_SETTLE_S)

        # Measure L and R from a single DSP state snapshot so both channels
        # are sampled at the same instant.  Separate calls can produce false
        # failures when MediaStreamer has a brief level transient between reads.
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            levels = dsp.measure_output_levels_batch([left, right], settle_time=2.0)
        else:
            levels = dsp.measure_input_levels_batch([left, right], settle_time=2.0)
        level_l = levels[left]
        level_r = levels[right]

        logger.info(
            "Zone %d (%d Hz): L=%.2f dB, R=%.2f dB (expected %.1f to %.1f)",
            zone_num, freq, level_l, level_r, LEVEL_LOWER_DB, LEVEL_UPPER_DB,
        )

        assert LEVEL_LOWER_DB <= level_l <= LEVEL_UPPER_DB, (
            f"Zone {zone_num} {left} level {level_l:.2f} dB outside "
            f"[{LEVEL_LOWER_DB}, {LEVEL_UPPER_DB}]"
        )
        assert LEVEL_LOWER_DB <= level_r <= LEVEL_UPPER_DB, (
            f"Zone {zone_num} {right} level {level_r:.2f} dB outside "
            f"[{LEVEL_LOWER_DB}, {LEVEL_UPPER_DB}]"
        )


class TestStreamingSignalPresence:
    """Phase 4: Verify signal presence for each zone while streaming.

    With zones routed to the correct streaming inputs (Input05-08 on 4ZSA,
    mapping to MediaStream1-4 / ports 60001-60004), CresNext reports
    IsSignalDetected=True when audio is flowing.

    We verify:
      1. MediaStreamerV2 player state (must be PLAYING)
      2. DSP mux input level on M{n}L (must be above silence floor)
      3. CresNext IsSignalDetected (must be True)
      4. CresNext IsSignalClipping (must NOT be True)
    """

    @pytest.mark.parametrize("zone_num", list(range(1, 9)))
    def test_signal_present_while_playing(self, cresnext, dsp, device_cfg,
                                          streaming, audio_file_server,
                                          zone_num):
        """Zone must show signal: player PLAYING, DSP level OK, IsSignalDetected=True."""
        zones = _streaming_zones(device_cfg)
        if zone_num not in zones:
            pytest.skip(f"Zone {zone_num} not in streaming config")

        # 1. Player must report PLAYING
        player = streaming.get_player(zone_num)
        assert player.is_playing, (
            f"Zone {zone_num}: player not in PLAYING state"
        )

        # 2. DSP mux input must show signal
        left, _ = _streaming_inputs_for_zone(zone_num, device_cfg)
        level = _measure_streaming_level(dsp, left, device_cfg, settle_time=1.0)
        assert level > SILENCE_FLOOR_DB, (
            f"Zone {zone_num}: DSP mux {left} level {level:.2f} dB "
            f"below silence floor ({SILENCE_FLOOR_DB} dB)"
        )

        # 3. CresNext must report signal detected on the zone
        zone_info = cresnext.get_zone_info(zone_num)
        detected = zone_info.get("IsSignalDetected", None)
        clipping = zone_info.get("IsSignalClipping", None)

        logger.info(
            "Zone %d: player=PLAYING, DSP M%dL=%.2f dB, "
            "IsSignalDetected=%s, IsSignalClipping=%s",
            zone_num, zone_num, level, detected, clipping,
        )

        assert detected is True, (
            f"Zone {zone_num}: IsSignalDetected is {detected}, expected True"
        )
        assert clipping is not True, (
            f"Zone {zone_num}: IsSignalClipping is True — signal is clipping!"
        )


class TestStreamingCleanup:
    """Phase 6: Stop all streaming and verify silence."""

    def test_stop_all_players(self, streaming, device_cfg, cresnext, dsp):
        """Stop playback and deactivate service on all players.

        Iterates ALL zones in the streaming config (not just selected_zones) so
        that players started by parametrized tests (TestStreamingLevels,
        TestStreamingSignalPresence) on non-selected zones are also stopped.
        For example, in quick mode selected_zones=[1,3,5] but zone 7 may have
        been started by a parametrized test — without this fix zone 7's player
        stays running and A7L remains at -70 dB causing false failures.

        After stopping players, also clear AvMatrixRouting for every zone so the
        DSP input is severed even if a player's stop() call fails silently
        (e.g. HTTP 5xx or timeout on a DSP1 zone port).

        Finally, scrub DSP mixer crosspoints from the signal generator to all
        amp outputs.  Prior test files (test_signal_routing, test_bridging,
        test_speaker_protect) call set_mixer / route_sig_to_output but do not
        always clear the crosspoint at the end of every parametrized case.
        A leftover ``dsp mix 8 14 0`` (sig_ch DSP1 -> A8L) combined with a
        residual streaming source on Zone8 keeps A8L at ~-70 dB across the
        silence checks below — this fails only in the full nightly run, never
        when TestStreamingCleanup runs alone.
        """
        # Use the full streaming zone map — not filtered by selected_zones.
        streaming_cfg = device_cfg.get("streaming", {})
        all_zones = sorted(int(z) for z in streaming_cfg.get("zones", {}).keys())
        selected_zones = sorted(int(z) for z in device_cfg.get("selected_zones", all_zones))
        diag_zones = sorted(set(selected_zones) | {8}) if 8 in all_zones else selected_zones

        _log_streaming_cleanup_diagnostics(
            "before_stop_all_players", streaming, cresnext, dsp, device_cfg, diag_zones
        )

        for zone in all_zones:
            player = streaming.get_player(zone)
            player.stop_streaming()
            logger.info("Zone %d: stopped streaming", zone)

        # Wait for ALSA loopback buffers to fully drain before clearing routes.
        # On fw42 (8ZSA), clearing a zone route resets OUTPUT_GAIN to
        # defaultVolume while the ALSA buffer still holds audio, causing the DSP
        # peak-hold to latch a ~-70 dB residual.  See _wait_alsa_drain.
        _wait_alsa_drain(dsp, all_zones, device_cfg)

        _log_streaming_cleanup_diagnostics(
            "after_player_stop_before_route_clear", streaming, cresnext, dsp, device_cfg, diag_zones
        )

        # Clear zone sources via CresNext individually (one Zone{N} POST per
        # zone).  Sending an empty-object body removes the Zone{N} entry from
        # Routes; merely setting AudioSource="" keeps the binding alive on
        # fw42 and the MediaStreamer source continues feeding ~-70 dB noise
        # into the amp output.
        for zone in all_zones:
            try:
                cresnext.clear_zone_route(zone)
                logger.info("Zone %d: CresNext route cleared", zone)
            except Exception as e:
                logger.warning("Zone %d: failed to clear CresNext route: %s", zone, e)

        _log_streaming_cleanup_diagnostics(
            "after_route_clear_before_mixer_scrub", streaming, cresnext, dsp, device_cfg, diag_zones
        )

        # Scrub DSP signal-generator mixer crosspoints left behind by earlier
        # test files (test_signal_routing, test_bridging, test_speaker_protect).
        try:
            dsp.clear_all_sig_routes()
            logger.info("DSP signal-generator mixer crosspoints cleared")
        except Exception as e:
            logger.warning("Failed to clear DSP sig-gen mixer crosspoints: %s", e)

        _log_streaming_cleanup_diagnostics(
            "after_mixer_scrub_before_settle", streaming, cresnext, dsp, device_cfg, diag_zones
        )

        time.sleep(STOP_SETTLE_S)

        _log_streaming_cleanup_diagnostics(
            "after_stop_settle", streaming, cresnext, dsp, device_cfg, diag_zones
        )

    def test_silence_after_stop(self, dsp, device_cfg, streaming, cresnext):
        """All streaming measurement points must be silent after streaming stops."""
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
        for z in zones:
            left, right = _streaming_inputs_for_zone(z, device_cfg)
            level_l = _measure_streaming_level(dsp, left, device_cfg, settle_time=1.0)
            logger.info("Zone %d: level after stop settle: %.2f dB", z, level_l)
            if z in (7, 8):
                # Zones 7 and 8 are on DSP1 and exhibit a firmware residual
                # signal (~-70 dB) at the ducker output after streaming stops.
                # Allow an extra 10s for the DSP output chain to fully decay.
                logger.info("Zone %d: waiting extra 10s for DSP1 decay...", z)
                import time
                time.sleep(10)
                level_l_post = _measure_streaming_level(dsp, left, device_cfg, settle_time=1.0)
                logger.info("Zone %d: level after extra wait: %.2f dB", z, level_l_post)
                if level_l_post >= SILENCE_FLOOR_DB:
                    logger.info("Zone %d: triggering deep diagnostics after STOP residual detected...", z)
                    deep_zone8_diagnostics(dsp, device_cfg, streaming=streaming, cresnext=cresnext, poll_secs=30, interval=2)
                    _log_zone8_dsp_pipeline(
                        f"silence_failure_zone{z}_pipeline", dsp, device_cfg
                    )
                    _log_streaming_cleanup_diagnostics(
                        f"silence_failure_zone{z}_after_extra_wait", streaming, cresnext, dsp,
                        device_cfg=device_cfg, zones=[z]
                    )
                assert level_l_post < SILENCE_FLOOR_DB, (
                    f"Zone {z} {left} still has signal after extra wait: {level_l_post:.2f} dB"
                )
            else:
                if level_l >= SILENCE_FLOOR_DB:
                    _log_streaming_cleanup_diagnostics(
                        f"silence_failure_zone{z}", streaming, cresnext, dsp,
                        device_cfg=device_cfg, zones=[z]
                    )
                assert level_l < SILENCE_FLOOR_DB, (
                    f"Zone {z} {left} still has signal after stop: {level_l:.2f} dB"
                )
            logger.info("Zone %d: silent (%.2f dB) ✓", z, level_l if z not in (7, 8) else level_l_post)

    def test_signal_absent_after_stop(self, cresnext, dsp, streaming, device_cfg):
        """After stopping: player STOPPED, DSP silent, IsSignalDetected=False."""
        zones = _streaming_zones(device_cfg)
        for zone_num in sorted(zones.keys()):
            # Player should not be PLAYING
            player = streaming.get_player(zone_num)
            if player.is_playing:
                _log_streaming_cleanup_diagnostics(
                    f"player_still_playing_zone{zone_num}", streaming, cresnext, dsp,
                    device_cfg=device_cfg, zones=[zone_num]
                )
            assert not player.is_playing, (
                f"Zone {zone_num}: player still PLAYING after stop"
            )

            # DSP mux should be silent
            left, _ = _streaming_inputs_for_zone(zone_num, device_cfg)
            level = _measure_streaming_level(dsp, left, device_cfg, settle_time=1.0)
            if level >= SILENCE_FLOOR_DB:
                _log_streaming_cleanup_diagnostics(
                    f"signal_absent_level_failure_zone{zone_num}", streaming, cresnext, dsp,
                    device_cfg=device_cfg, zones=[zone_num]
                )
            assert level < SILENCE_FLOOR_DB, (
                f"Zone {zone_num}: DSP mux {left} still has signal "
                f"({level:.2f} dB) after stop"
            )

            # CresNext must report no signal detected
            zone_info = cresnext.get_zone_info(zone_num)
            detected = zone_info.get("IsSignalDetected", None)
            clipping = zone_info.get("IsSignalClipping", None)

            if zone_num == 5 and detected is not False:
                # Zone 5 IsSignalDetected has an API debounce lag — poll for up
                # to 10 s in 2 s increments before failing.
                for _retry in range(5):
                    logger.info(
                        "Zone 5: IsSignalDetected=%s after stop, retry %d/5 in 2s",
                        detected, _retry + 1,
                    )
                    time.sleep(2)
                    zone_info = cresnext.get_zone_info(zone_num)
                    detected = zone_info.get("IsSignalDetected", None)
                    clipping = zone_info.get("IsSignalClipping", None)
                    logger.info(
                        "Zone 5: IsSignalDetected after retry %d=%s, IsSignalClipping=%s",
                        _retry + 1, detected, clipping,
                    )
                    if detected is False:
                        break

            if detected is not False:
                _log_streaming_cleanup_diagnostics(
                    f"signal_detected_failure_zone{zone_num}", streaming, cresnext, dsp,
                    device_cfg=device_cfg, zones=[zone_num]
                )
            assert detected is False, (
                f"Zone {zone_num}: IsSignalDetected is {detected} after stop, "
                "expected False"
            )

            logger.info(
                "Zone %d after stop: player=STOPPED, DSP M%dL=%.2f dB, "
                "IsSignalDetected=%s, IsSignalClipping=%s ✓",
                zone_num, zone_num, level, detected, clipping,
            )

    def test_clear_routes(self, cresnext, device_cfg):
        """Remove all zone audio source routes (cleanup)."""
        streaming_cfg = device_cfg.get("streaming", {})
        all_zones = sorted(int(z) for z in streaming_cfg.get("zones", {}).keys())
        for z in all_zones:
            try:
                cresnext.clear_zone_route(z)
            except Exception:
                pass
            logger.info("Zone %d: route cleared", z)
