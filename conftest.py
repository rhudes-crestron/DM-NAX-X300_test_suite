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
    return cfg


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
def module_reset(dsp, device_cfg):
    """Reset device once before each test MODULE (feature group).

    Mirrors the 8ZSA nightly pattern where Reset_UC-DSPS_&_Zones runs once
    before each feature test group (Volume, Delay, Balance, etc.), NOT before
    every individual test case.  This cuts total resets from ~140 to ~12.
    """
    _do_reset(dsp, device_cfg)
    yield


def _do_reset(dsp, device_cfg):
    """Reset signal path and all zone properties to baseline defaults.

    Batches DSP commands into a single SSH call for speed, then resets zone
    audio properties via CresNext REST API (one request per zone).
    """
    sig_ch = device_cfg["signal_generator"]["channel"]
    num_outputs = device_cfg.get("mixer_outputs", 10)

    # 1. Build a single shell command that stops all tones, clears all mixer
    #    crosspoints, and resets input gains in one SSH round-trip.
    cmds = []
    # Stop tones on all physical channels + signal generator
    for ch in list(range(8)) + [sig_ch]:
        cmds.append(f"dsp tone {ch} 0 0")
    # Clear mixer crosspoints: physical channels + signal generator → all outputs
    for ch in list(range(8)) + [sig_ch]:
        for out in range(num_outputs):
            cmds.append(f"dsp mix {ch} {out} -200")
    # Reset input gains
    for ch in range(8):
        cmds.append(f"dsp gain {ch} set 0")

    try:
        dsp.ssh.execute(" ; ".join(cmds), timeout=30)
    except Exception:
        logger.warning("Batch DSP reset failed, continuing")

    # 2. Reset zone audio properties via CresNext REST API for every zone
    if dsp.cn:
        for zone in range(1, device_cfg.get("zones", 4) + 1):
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

        # Un-mute all input sources
        num_inputs = len(device_cfg.get("physical_inputs", {}))
        for inp in range(1, num_inputs + 1):
            try:
                dsp.cn.set_input_mute(inp, False)
            except Exception:
                pass

        # Reset EQ bypass and speaker protect for all zones
        for zone in range(1, device_cfg.get("zones", 4) + 1):
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
def streaming(device_cfg):
    """Session-scoped StreamingPlayerManager for all zones."""
    from lib.streaming_client import StreamingPlayerManager
    import socket

    # Quick TCP connectivity check on the first streaming port.
    # If the MediaStreamer service is not running, skip all streaming tests
    # instead of failing with ConnectionRefusedError.
    base_port = device_cfg.get("streaming", {}).get("base_port", 60001)
    ip = device_cfg["ip"]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect((ip, base_port))
        sock.close()
    except (ConnectionRefusedError, OSError, socket.timeout):
        pytest.skip(
            f"Streaming service not reachable at {ip}:{base_port} — "
            f"MediaStreamer may not be running on {device_cfg['model']}"
        )

    mgr = StreamingPlayerManager(
        device_ip=ip,
        num_zones=device_cfg["zones"],
    )
    yield mgr

    # Cleanup: stop all players at end of session
    try:
        mgr.stop_all()
    except Exception as e:
        logger.warning("Failed to stop streaming players: %s", e)
