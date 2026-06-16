"""
Pytest configuration and shared fixtures for the DM-NAX DSP Test Suite.
"""
import os
import json
import time
import logging
import pytest
import yaml
from datetime import datetime

from lib.device_ssh import DeviceSSH
from lib.dsp_controller import DSPController
from lib.cresnext_client import CresNextClient
from lib.test_trace import set_current_test, clear_current_test, append_failure

logger = logging.getLogger(__name__)

SUITE_DIR = os.path.dirname(os.path.abspath(__file__))


def pytest_addoption(parser):
    parser.addoption("--device", default="DM-NAX-4ZSA", help="Device profile name from devices.yaml")
    parser.addoption("--config", default=os.path.join(SUITE_DIR, "config", "devices.yaml"), help="Config file path")
    parser.addoption("--results-dir", default=os.path.join(SUITE_DIR, "results"), help="Results output directory")
    parser.addoption("--category", default=None, help="Test category filter (dsp, streaming, firmware)")
    parser.addoption("--ip", default=None, help="Override device IP address")
    parser.addoption("--username", default=None, help="Override device SSH/API username")
    parser.addoption("--password", default=None, help="Override device SSH/API password")
    parser.addoption("--firmware-file", default=None, help="Path to firmware file (.puf or .zip) for upgrade tests")
    parser.addoption("--zone-mode", default="full", choices=["full", "quick"],
                     help="Zone execution mode: full=all zones, quick=profiled subset")
    parser.addoption("--zones", default=None,
                     help="Explicit comma-separated zone list override (e.g. 2,4,5,8)")
    parser.addoption(
        "--include-crosstalk",
        action="store_true",
        default=False,
        help="Include crosstalk tests in collection (excluded by default)",
    )


def _parse_zone_csv(zone_csv):
    if not zone_csv:
        return []
    vals = []
    for part in str(zone_csv).split(","):
        token = part.strip()
        if not token:
            continue
        vals.append(int(token))
    return vals


def _resolve_selected_zones(config_obj):
    cfg_path = config_obj.getoption("--config")
    device_name = config_obj.getoption("--device")
    mode = config_obj.getoption("--zone-mode")
    zone_override = config_obj.getoption("--zones")

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    dev = cfg["devices"][device_name]
    max_zones = int(dev.get("zones", 4))

    if zone_override:
        raw = _parse_zone_csv(zone_override)
    elif mode == "quick":
        raw = cfg.get("zone_profiles", {}).get("quick", {}).get(device_name, [])
    else:
        raw = list(range(1, max_zones + 1))

    selected = sorted({int(z) for z in raw if 1 <= int(z) <= max_zones})
    if not selected:
        selected = list(range(1, max_zones + 1))
    return selected


def pytest_configure(config):
    """Compute selected zones once and share across fixtures/hooks."""
    selected = _resolve_selected_zones(config)
    setattr(config, "_selected_zones", selected)


def pytest_collection_modifyitems(config, items):
    """Deselect zone-parametrized cases that are outside selected zones."""
    selected = set(getattr(config, "_selected_zones", []))
    include_crosstalk = bool(config.getoption("--include-crosstalk"))

    kept = []
    deselected = []
    for item in items:
        if (not include_crosstalk) and "tests/test_crosstalk.py" in item.nodeid:
            deselected.append(item)
            continue

        if not selected:
            kept.append(item)
            continue

        callspec = getattr(item, "callspec", None)
        if not callspec:
            kept.append(item)
            continue
        excluded = False
        for key in ("zone", "zone_num"):
            if key not in callspec.params:
                continue
            try:
                z = int(callspec.params[key])
            except Exception:
                continue
            if z not in selected:
                excluded = True
                break
        if excluded:
            deselected.append(item)
        else:
            kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


@pytest.fixture(scope="session")
def config(request):
    """Load the full configuration."""
    cfg_path = request.config.getoption("--config")
    with open(cfg_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def device_name(request):
    return request.config.getoption("--device")


@pytest.fixture(scope="session")
def device_cfg(config, device_name, request):
    """Return the device-specific config dict, with CLI overrides applied."""
    if device_name not in config["devices"]:
        pytest.exit(f"Device '{device_name}' not found in config. Available: {list(config['devices'].keys())}")
    cfg = config["devices"][device_name]
    # CLI overrides take precedence over devices.yaml
    ip = request.config.getoption("--ip")
    username = request.config.getoption("--username")
    password = request.config.getoption("--password")
    if ip:
        cfg["ip"] = ip
    if username:
        cfg["username"] = username
    if password:
        cfg["password"] = password
    cfg["selected_zones"] = list(getattr(request.config, "_selected_zones", []))
    logger.info(
        "Zone selection mode=%s selected=%s",
        request.config.getoption("--zone-mode"),
        cfg["selected_zones"],
    )
    return cfg


@pytest.fixture(scope="session")
def selected_zones(device_cfg):
    """Session-selected zones after mode/profile filtering."""
    return device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))


@pytest.fixture(scope="session")
def test_settings(config):
    return config["test_settings"]


@pytest.fixture(scope="session")
def ssh(device_cfg):
    """Session-scoped SSH connection to the DUT."""
    conn = DeviceSSH(
        ip=device_cfg["ip"],
        username=device_cfg["username"],
        password=device_cfg["password"],
        port=device_cfg.get("ssh_port", 22),
    )
    conn.connect()
    yield conn
    conn.disconnect()


@pytest.fixture(scope="session")
def cresnext(device_cfg):
    """Session-scoped CresNext REST API client."""
    client = CresNextClient(
        ip=device_cfg["ip"],
        username=device_cfg["username"],
        password=device_cfg["password"],
    )
    client.connect()
    yield client
    client.disconnect()


@pytest.fixture(scope="session")
def dsp(ssh, device_cfg, test_settings, cresnext):
    """Session-scoped DSP controller."""
    ctrl = DSPController(ssh, device_cfg, test_settings, cresnext=cresnext)
    yield ctrl
    # Restore defaults at the end of the session
    try:
        ctrl.restore_defaults()
    except Exception as e:
        logger.warning("Failed to restore defaults: %s", e)


@pytest.fixture(autouse=True, scope="module")
def module_reset(dsp, device_cfg, request):
    """Reset device once before each test MODULE (feature group).

    Mirrors the 8ZSA nightly pattern where Reset_UC-DSPS_&_Zones runs once
    before each feature test group (Volume, Delay, Balance, etc.), NOT before
    every individual test case.  This cuts total resets from ~140 to ~12.

    Reset SSH commands are written to a dedicated per-module trace file
    (_module_reset_<module>.log) so they do NOT appear in any test's own
    trace log.
    """
    import lib.test_trace as _tt

    results_base = request.config.getoption("--results-dir")
    module_name = getattr(request.module, "__name__", "unknown")

    # Save the current trace log pointer (already set by pytest_runtest_setup
    # for the first test in this module) and redirect to a dedicated reset log.
    with _tt._LOCK:
        _saved_log = _tt._CURRENT_LOG

    set_current_test(f"_module_reset_{module_name}", results_base)
    _do_reset(dsp, device_cfg)

    # Restore the saved pointer so the first test body's SSH commands land in
    # the correct per-test trace file.
    with _tt._LOCK:
        _tt._CURRENT_LOG = _saved_log

    yield


def _do_reset(dsp, device_cfg):
    """Reset signal path and all zone properties to baseline defaults.

    On fw21 (4ZSA): sends DSP console commands to stop tones and clear mixer
    crosspoints, then resets zone audio properties via CresNext REST API.

    On fw42 (8ZSA/4ZSP): does NOT use console mixer commands because they
    destroy DspAudioCtl's internal mixer state.  Instead, relies on
    AvMatrixRouting REST to (re-)program mixer and zone-chain processing.
    To force DspAudioCtl to re-program (even if already set to the same
    source), first clears the route to "None" then sets the desired input.
    """
    sig_ch = device_cfg["signal_generator"]["channel"]
    num_outputs = device_cfg.get("mixer_outputs", 10)
    model = str(device_cfg.get("model", "")).upper()

    # 1. Stop tones on all physical channels + signal generator
    for ch in list(range(8)) + [sig_ch]:
        try:
            dsp.ssh.execute(f"dsp tone {ch} 0 0", timeout=30, trace_source="RESET")
        except Exception as e:
            logger.warning("DSP tone stop failed ch=%d: %s", ch, e)

    # 2. Restore DSP mixer crosspoints.
    #
    # fw21 (4ZSA): clear all non-identity crosspoints then let DSP tests
    # re-establish their own routes via set_mixer().
    #
    # fw42 (8ZSA/4ZSP): restore the identity matrix (In[N]→Out[N]@0dB)
    # within each 8-channel block.  This is required because DSP tests
    # (test_signal_to_noise, test_delay, etc.) modify the crosspoints via
    # 'dsp mix' and leave them set.  Without resetting to identity, a
    # subsequent streaming test inherits a broken mixer (e.g. In[0]→-inf,
    # In[1]→Z1R only) causing the left amp output to be silent.
    #
    # IMPORTANT for fw42: only issue same-block 'dsp mix' commands.
    # Cross-block routing (e.g. dsp mix 0 8) is architecturally invalid on
    # the dual-SHARC platform and can hang the SPI bus.  Block 0: ch 0-7 →
    # out 0-7.  Block 1: ch 8-15 → out 8-15.
    if model in {"8ZSA", "4ZSP"}:
        # First zero every crosspoint within each block (clear stale routes)
        block_size = 8
        for blk_start in (0, 8):
            for ch in range(blk_start, blk_start + block_size):
                for out in range(blk_start, blk_start + block_size):
                    if ch != out:
                        try:
                            dsp.ssh.execute(
                                f"dsp mix {ch} {out} -200",
                                timeout=15, trace_source="RESET",
                            )
                        except Exception as e:
                            logger.warning("fw42 mixer clear ch%d→out%d: %s", ch, out, e)
        # Then restore identity: In[N]→Out[N]@0dB so both L and R channels
        # of each zone are driven by their natural input pair.
        for blk_start in (0, 8):
            for n in range(blk_start, blk_start + block_size):
                try:
                    dsp.ssh.execute(
                        f"dsp mix {n} {n} 0",
                        timeout=15, trace_source="RESET",
                    )
                except Exception as e:
                    logger.warning("fw42 mixer identity ch%d→out%d: %s", n, n, e)
        logger.info("fw42 mixer restored to identity matrix")
    else:
        # fw21: clear all crosspoints (single block, no risk)
        cmds = []
        for ch in list(range(8)) + [sig_ch]:
            for out in range(num_outputs):
                cmds.append(f"dsp mix {ch} {out} -200")
        for idx, cmd in enumerate(cmds):
            try:
                dsp.ssh.execute(cmd, timeout=30, trace_source="RESET")
            except Exception as e:
                logger.warning("DSP reset command failed at index %d cmd='%s': %s", idx, cmd, e)

    # Reset input gains through syntax-fallback helper to avoid fw/report mismatches.
    for ch in range(8):
        try:
            dsp.set_input_gain(ch, 0, trace_source="RESET")
        except Exception as e:
            logger.warning("DSP input gain reset failed on ch %d: %s", ch, e)

    # 2. Reset zone audio properties via CresNext REST API for every zone
    if dsp.cn:
        zones = device_cfg.get("selected_zones", list(range(1, device_cfg.get("zones", 4) + 1)))
        for zone in zones:
            try:
                dsp.cn.set_zone_audio(
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

        # fw42 devices require explicit zone-source mapping for the internal
        # signal generator to reach zone amplifier outputs.  Route every zone
        # to dsp_tone_input (a physical input like Input01/S1 that is
        # physically silent), so the tone generator is the sole audio source.
        # Streaming tests override this in their own setup phase
        # (test_route_zones_to_streaming).
        if device_cfg.get("dsp_fw_version", 21) >= 42:
            tone_input = device_cfg.get("dsp_tone_input", "Input01")
            for zone in zones:
                try:
                    if model in {"8ZSA", "4ZSP"}:
                        # Force DspAudioCtl to re-program the mixer by first
                        # routing to a different valid source then back.
                        # "None" is ignored by the device; we need a real input
                        # to trigger a genuine route change.
                        toggle_input = "Input02" if tone_input != "Input02" else "Input03"
                        try:
                            dsp.cn.set_zone_source(zone, toggle_input)
                        except Exception:
                            pass
                        import time as _time
                        _time.sleep(0.2)
                        try:
                            dsp.cn.set_zone_sources_streamrouting({int(zone): tone_input})
                        except Exception:
                            dsp.cn.set_zone_source(zone, tone_input)
                    else:
                        dsp.cn.set_zone_source(zone, tone_input)
                except Exception:
                    pass

        # Un-mute all input sources
        num_inputs = len(device_cfg.get("physical_inputs", {}))
        for inp in range(1, num_inputs + 1):
            try:
                dsp.cn.set_input_mute(inp, False)
            except Exception:
                pass
            try:
                dsp.cn.set_input_compensation(inp, 0)
            except Exception:
                pass

        # Reset EQ bypass and speaker protect for all zones
        for zone in zones:
            try:
                dsp.cn.set_zone_audio(zone, IsEqBypassEnabled=False)
            except Exception:
                pass
            try:
                dsp.cn.set_speaker_protect(zone, IsSpeakerProtectEnabled=False)
            except Exception:
                pass

    # 3. Small settle time
    import time
    time.sleep(0.5)


@pytest.fixture(scope="session")
def device_version(ssh):
    """Firmware version of the DUT."""
    return ssh.get_version()


@pytest.fixture(scope="session")
def results_dir(request):
    """Create timestamped results directory."""
    base = request.config.getoption("--results-dir")
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join(base, ts)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


# ------------------------------------------------------------------
# Test metadata collection for reporting
# ------------------------------------------------------------------
class TestResultCollector:
    """Collects test results for custom HTML reporting."""

    def __init__(self):
        self.results = []
        self.start_time = datetime.now()
        self.device_info = {}

    def add(self, test_name, category, status, message="", duration=0, details=None):
        self.results.append({
            "test_name": test_name,
            "category": category,
            "status": status,  # "pass", "fail", "skip", "error"
            "message": message,
            "duration_s": round(duration, 2),
            "timestamp": datetime.now().isoformat(),
            "details": details or {},
        })


@pytest.fixture(scope="session")
def collector():
    return TestResultCollector()


def pytest_terminal_summary(terminalreporter, config):
    """Generate summary after all tests complete."""
    results_base = config.getoption("--results-dir")
    if results_base:
        os.makedirs(results_base, exist_ok=True)


def pytest_runtest_setup(item):
    """Start per-test developer trace before fixture setup/test execution."""
    results_base = item.config.getoption("--results-dir")
    set_current_test(item.nodeid, results_base)


def pytest_runtest_teardown(item, nextitem):
    """Close per-test developer trace after test teardown."""
    clear_current_test(item.nodeid)


def pytest_runtest_logreport(report):
    """Write failure traceback and captured log into the per-test trace file."""
    if report.failed:
        longrepr = report.longreprtext if hasattr(report, "longreprtext") else str(report.longrepr)
        captured_log = report.caplog if hasattr(report, "caplog") else ""
        # sections contains ("Captured log call", text) and similar tuples
        for title, content in getattr(report, "sections", []):
            if "log" in title.lower():
                captured_log = content
                break
        append_failure(report.nodeid, report.when, longrepr, captured_log)


# ------------------------------------------------------------------
# Streaming test fixtures
# ------------------------------------------------------------------

def _get_host_ip_for_device(device_ip):
    """Discover this machine's IP address on the same subnet as the device."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect (UDP, no actual packets) to the device to discover our
        # outgoing interface IP.
        s.connect((device_ip, 80))
        return s.getsockname()[0]
    finally:
        s.close()


@pytest.fixture(scope="session")
def audio_file_server(device_cfg):
    """Start a local HTTP server that serves WAV test tones.

    The server runs on the test machine and provides audio files
    to the DM-NAX streaming players.  Returns (host_ip, port).
    """
    import http.server
    import threading

    audio_dir = os.path.join(SUITE_DIR, "audiofiles")

    # Generate tones if they don't exist
    from lib.generate_tones import generate_all
    generate_all(audio_dir)

    host_ip = _get_host_ip_for_device(device_cfg["ip"])
    port = device_cfg.get("streaming", {}).get("audio_server_port", 8088)

    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=audio_dir, **kwargs)
        def log_message(self, fmt, *args):
            logger.debug("AudioFileServer: " + fmt, *args)

    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), _QuietHandler)
    httpd.socket.setsockopt(__import__('socket').SOL_SOCKET,
                            __import__('socket').SO_REUSEADDR, 1)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    logger.info("Audio file server started at http://%s:%d/ (serving %s)", host_ip, port, audio_dir)

    yield host_ip, port

    httpd.shutdown()
    logger.info("Audio file server stopped")


@pytest.fixture(scope="session")
def streaming(device_cfg, ssh):
    """Session-scoped StreamingPlayerManager for all zones."""
    from lib.streaming_client import StreamingPlayerManager, detect_mediaplayermode, MODE_MP1

    # Detect whether device is in MP1 (MediaStreamer) or MP2 (MediaStreamerV2) mode.
    # Always checked via SSH port 22 (Crestron CLI) — no bash needed for this step.
    # Streaming tests are written for MP1 (MediaStreamer) only; skip if the device
    # reports a different mode.
    mode = detect_mediaplayermode(ssh)
    if mode != MODE_MP1:
        pytest.skip(
            f"{device_cfg['model']} ({device_cfg['ip']}) is in {mode} mode; "
            f"streaming tests require MP1 (MediaStreamer)"
        )

    # Resolve streaming connection parameters up front — needed for both the
    # engineering-debug path and the tunnel probe below.
    streaming_cfg = device_cfg.get("streaming", {})
    base_port = streaming_cfg.get("base_port", 60001)
    ip = device_cfg["ip"]
    local_ip = streaming_cfg.get("local_ip", ip)

    # Streaming commands are issued via on-device bash (port 6022).
    # Three-step bash setup:
    #   1. If bash already available → nothing to do.
    #   2. Else if engineering debug is already enabled (persists across reboots)
    #      → just open port 6022 via "sudo ... telnetport debug" on port 22.
    #   3. Else → upload zip + imgupd engdbg + open port 6022 (auto_enable path).
    eng_cfg = device_cfg.get("engineering_debug", {})
    auto_enable = eng_cfg.get("auto_enable_for_streaming", True)
    enable_err = None

    if not ssh.can_open_bash():
        if ssh.is_engineering_debug_enabled():
            # Eng debug is on but port 6022 is closed (normal after reboot).
            logger.info(
                "%s: eng debug already enabled — opening bash port via telnetport debug",
                device_cfg["ip"],
            )
            sudo_pass = eng_cfg.get("sudo_pass", "NHPchCdpeGFdRbtf")
            ssh.open_debug_bash_port(sudo_pass=sudo_pass)
        elif auto_enable:
            try:
                ssh.enable_engineering_debug(
                    zip_file=eng_cfg.get("zip_file"),
                    search_roots=eng_cfg.get("search_roots", []),
                    set_current_datetime=bool(eng_cfg.get("set_current_datetime", False)),
                    remote_zip_path=eng_cfg.get("remote_zip_path", "firmware/engineering_debug.zip"),
                    smb_username=eng_cfg.get("smb_username"),
                    smb_password=eng_cfg.get("smb_password"),
                    smb_domain=eng_cfg.get("smb_domain"),
                    sudo_pass=eng_cfg.get("sudo_pass"),
                )
            except Exception as e:
                enable_err = str(e)
                logger.warning("Engineering debug auto-enable failed on %s: %s",
                               device_cfg["ip"], e)

    if not ssh.can_open_bash():
        detail = f"; reason: {enable_err}" if enable_err else ""
        pytest.skip(
            f"Bash access unavailable on {device_cfg['model']} ({device_cfg['ip']}); "
            f"could not open debug port 6022{detail}"
        )

    # Validate streaming API reachability from the unit using on-device curl.
    try:
        status, payload = ssh.curl_bash(
            url=f"http://{local_ip}:{base_port}/api/v1/player/status",
            method="GET",
            body=None,
            timeout=6,
        )
    except Exception as e:
        pytest.skip(
            f"Streaming curl probe failed on {device_cfg['model']} at {local_ip}:{base_port}: {e}"
        )
    if status == 0 or status >= 400:
        pytest.skip(
            f"Streaming service not reachable at {local_ip}:{base_port} "
            f"(HTTP {status}) — MediaStreamer ({mode}) may not be running on {device_cfg['model']}"
        )

    logger.info("Streaming curl probe success on %s:%s (HTTP %s)", local_ip, base_port, status)
    logger.debug("Streaming curl probe payload preview: %s", str(payload)[:220])

    mgr = StreamingPlayerManager(
        device_ip=ip,
        num_zones=device_cfg["zones"],
        mode=mode,
        ssh=ssh,
        local_ip=local_ip if local_ip != ip else None,
    )
    logger.info("Streaming manager created: mode=%s, zones=%d", mode, device_cfg["zones"])
    yield mgr

    # Cleanup: stop all players at end of session
    try:
        mgr.stop_all()
    except Exception as e:
        logger.warning("Failed to stop streaming players: %s", e)
