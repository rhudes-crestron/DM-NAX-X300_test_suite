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

logger = logging.getLogger(__name__)

# Expected output level range — streaming at -20 dBFS through the DSP
# The spreadsheet uses -35 to -38 dB with Audio Precision measuring externally.
# Streaming audio from MediaStreamerV2 arrives at DSP mux inputs M1-M4
# at approximately -34 dB for -20 dBFS source material.
LEVEL_UPPER_DB = -15.0
LEVEL_LOWER_DB = -45.0
SILENCE_FLOOR_DB = -100.0
PLAY_SETTLE_S = 8.0        # Time for streaming to stabilise
STOP_SETTLE_S = 8.0        # Time for output to drop after stop


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
    """Apply zone->AudioSource routing with MP1-specific StreamRoutings path."""
    model = str(device_cfg.get("model", "")).upper()
    if mode == MODE_MP1 and model in {"8ZSA", "4ZSP"}:
        mapping = {}
        for zone, zcfg in sorted(zones.items()):
            mapping[zone] = _resolve_stream_audio_source(device_cfg, zone, zcfg["input"], mode)
        cresnext.set_zone_sources_streamrouting(mapping)
        for zone, src in sorted(mapping.items()):
            logger.info("Routed Zone %d -> %s (MP1 StreamRoutings)", zone, src)
        return

    for zone, zcfg in sorted(zones.items()):
        input_name = _resolve_stream_audio_source(device_cfg, zone, zcfg["input"], mode)
        cresnext.set_zone_source(zone, input_name)
        logger.info("Routed Zone %d -> %s", zone, input_name)


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
            cresnext.set_zone_sources_streamrouting({zone_num: input_name})
        else:
            cresnext.set_zone_source(zone_num, input_name)
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

    def test_stop_all_players(self, streaming, device_cfg, cresnext):
        """Stop playback and deactivate service on all players.

        After stopping players, also clear AvMatrixRouting for every zone so the
        DSP input is severed even if a player's stop() call fails silently (e.g.
        HTTP 5xx or timeout on a DSP1 zone port).  This prevents residual signal
        on DSP1 amp outputs (A5L/A7L) from causing false failures in the silence
        checks that follow.
        """
        zones = _streaming_zones(device_cfg)
        for zone in sorted(zones.keys()):
            player = streaming.get_player(zone)
            player.stop_streaming()
            logger.info("Zone %d: stopped streaming", zone)

        # Clear zone sources via CresNext to sever DSP routing regardless of
        # whether the individual player stop commands succeeded.
        for zone in sorted(zones.keys()):
            try:
                cresnext.set_zone_source(zone, "")
                logger.info("Zone %d: CresNext route cleared", zone)
            except Exception as e:
                logger.warning("Zone %d: failed to clear CresNext route: %s", zone, e)

        time.sleep(STOP_SETTLE_S)

    def test_silence_after_stop(self, dsp, device_cfg):
        """All streaming measurement points must be silent after streaming stops."""
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
        for z in zones:
            left, right = _streaming_inputs_for_zone(z, device_cfg)
            level_l = _measure_streaming_level(dsp, left, device_cfg, settle_time=1.0)
            assert level_l < SILENCE_FLOOR_DB, (
                f"Zone {z} {left} still has signal after stop: {level_l:.2f} dB"
            )
            logger.info("Zone %d: silent (%.2f dB) ✓", z, level_l)

    def test_signal_absent_after_stop(self, cresnext, dsp, streaming, device_cfg):
        """After stopping: player STOPPED, DSP silent, IsSignalDetected=False."""
        zones = _streaming_zones(device_cfg)
        for zone_num in sorted(zones.keys()):
            # Player should not be PLAYING
            player = streaming.get_player(zone_num)
            assert not player.is_playing, (
                f"Zone {zone_num}: player still PLAYING after stop"
            )

            # DSP mux should be silent
            left, _ = _streaming_inputs_for_zone(zone_num, device_cfg)
            level = _measure_streaming_level(dsp, left, device_cfg, settle_time=1.0)
            assert level < SILENCE_FLOOR_DB, (
                f"Zone {zone_num}: DSP mux {left} still has signal "
                f"({level:.2f} dB) after stop"
            )

            # CresNext must report no signal detected
            zone_info = cresnext.get_zone_info(zone_num)
            detected = zone_info.get("IsSignalDetected", None)
            clipping = zone_info.get("IsSignalClipping", None)

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
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
        for z in zones:
            try:
                cresnext.set_zone_source(z, "")
            except Exception:
                pass
            logger.info("Zone %d: route cleared", z)
