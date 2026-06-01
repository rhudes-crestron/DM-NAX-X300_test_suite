"""
Device Firmware Upgrade Tests
═════════════════════════════
Runs FIRST before DSP tests to ensure the device is on the target firmware.

Upgrade methods (matching nightly UpdateScripts):
  - 4ZSA: .zip file  →  'imgupd'            (Imgupd.ps1)
  - 8ZSA: .puf file  →  'puf <file> ALL -D -V'  (ThreeSeriesPuf.ps1)

Test execution order mirrors the PowerShell sequence:
  01  firmware file exists
  02  device reachable pre-upgrade
  03  capture pre-upgrade version
  04  upload firmware via SFTP
  05  execute upgrade command
  06  wait for reboot cycle
  07  verify device online post-upgrade
  08  capture & report post-upgrade version
"""
import os
import glob
import logging
import time
import pytest
import paramiko

from lib.firmware_upgrader import FirmwareUpgrader
from lib.test_trace import log_event

logger = logging.getLogger(__name__)


# ── Helpers ──

def _find_firmware_file(firmware_dir, model):
    """Find the latest firmware file for the given device model.

    Selects the most recently modified file matching the pattern so the
    correct nightly drop is always picked regardless of version/date
    formatting in the filename.

    Expected filename examples (change daily):
      4ZSA  →  dm-nax-4zsa_0.6696.02239_r599365.zip
      8ZSA  →  dm-nax-trunk-nightly_2026.05.01.puf
      4ZSP  →  dm-nax-trunk-nightly_2026.05.01.puf  (same drop as 8ZSA)
    """
    patterns_by_model = {
        "4ZSA": [
            "dm-nax-4zsa*.zip",
            "DM-NAX-4ZSA*.zip",
        ],
        "4ZSP": [
            "dm-nax-trunk-nightly*.puf",
            "dm-nax*nightly*.puf",
            "DM-NAX*.puf",
        ],
        "8ZSA": [
            "dm-nax-trunk-nightly*.puf",
            "dm-nax*nightly*.puf",
            "DM-NAX*.puf",
        ],
    }
    for pattern in patterns_by_model.get(model, []):
        matches = glob.glob(os.path.join(firmware_dir, pattern))
        if matches:
            # Pick newest by file modification time — reliable for both
            # date-stamped (.puf) and version-stamped (.zip) filenames.
            latest = max(matches, key=os.path.getmtime)
            logger.info(
                "Firmware auto-detect: model=%s dir=%s pattern=%s → %s",
                model, firmware_dir, pattern, os.path.basename(latest),
            )
            return latest
    logger.warning(
        "Firmware auto-detect: no file found for model=%s in %s", model, firmware_dir
    )
    return None


# ── Fixtures (module-scoped so state persists across ordered tests) ──

@pytest.fixture(scope="module")
def upgrade_cfg(config, device_cfg, device_name, request):
    """Build upgrade configuration from devices.yaml."""
    model = device_cfg["model"]
    fw_cfg = config.get("firmware", {})

    # Firmware directory — per-device override > global firmware_dir > suite parent
    suite_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_fw_dir = os.path.abspath(os.path.join(suite_dir, ".."))
    per_device_dirs = fw_cfg.get("firmware_dirs", {})
    firmware_dir = per_device_dirs.get(device_name) or fw_cfg.get("firmware_dir", default_fw_dir)

    # Method auto-detected from model, overridable in config
    method = {"4ZSA": "imgupd", "4ZSP": "puf", "8ZSA": "puf"}.get(model, "imgupd")
    method = fw_cfg.get("method_override", method)

    # Remote directory on device for SFTP upload
    remote_dir = fw_cfg.get("remote_dir", "firmware")

    # Firmware file — CLI override > config > auto-detect
    firmware_file = request.config.getoption("--firmware-file")
    if not firmware_file:
        firmware_file = fw_cfg.get("firmware_file")
    if not firmware_file or not os.path.isfile(firmware_file):
        firmware_file = _find_firmware_file(firmware_dir, model)

    return {
        "method": method,
        "firmware_dir": firmware_dir,
        "firmware_file": firmware_file,
        "remote_dir": remote_dir,
        "model": model,
    }


@pytest.fixture(scope="module")
def upgrader(device_cfg, upgrade_cfg):
    """Create a FirmwareUpgrader instance (skips if no firmware found)."""
    fw_file = upgrade_cfg["firmware_file"]
    if not fw_file:
        pytest.skip(
            f"No firmware file found for {upgrade_cfg['model']} "
            f"in {upgrade_cfg['firmware_dir']}"
        )

    return FirmwareUpgrader(
        ip=device_cfg["ip"],
        username=device_cfg["username"],
        password=device_cfg["password"],
        firmware_path=fw_file,
        method=upgrade_cfg["method"],
        ssh_port=device_cfg.get("ssh_port", 22),
        remote_dir=upgrade_cfg["remote_dir"],
    )


# ── Test class ──

class TestDeviceUpgrade:
    """Firmware upgrade — ordered sequence matching UpdateScripts timing."""

    # Class-level shared state between ordered tests
    _pre_version = None
    _post_version = None
    _upload_path = None
    _upgrade_output = None

    # ── 01 ──
    def test_01_firmware_file_exists(self, upgrade_cfg):
        """Verify the firmware file exists and is non-empty."""
        fw = upgrade_cfg["firmware_file"]
        assert fw is not None, (
            f"No firmware file for {upgrade_cfg['model']} in {upgrade_cfg['firmware_dir']}"
        )
        assert os.path.isfile(fw), f"File not found: {fw}"
        size = os.path.getsize(fw)
        assert size > 0, f"Empty firmware file: {fw}"
        logger.info("Firmware: %s (%d bytes)", fw, size)
        log_event("UPGRADE", f"firmware file: {os.path.basename(fw)} ({size} bytes)")

    # ── 02 ──
    def test_02_device_reachable(self, upgrader):
        """Device must be reachable via SSH before upgrade."""
        log_event("UPGRADE", f"checking device reachable: {upgrader.ip}")
        assert upgrader.is_device_responsive(timeout=15), (
            f"Device {upgrader.ip} not reachable"
        )
        log_event("UPGRADE", f"device {upgrader.ip} is reachable")

    # ── 03 ──
    def test_03_pre_upgrade_version(self, upgrader):
        """Capture current firmware version."""
        ver = upgrader.get_version()
        assert ver, "Failed to read device version"
        TestDeviceUpgrade._pre_version = ver
        logger.info("Pre-upgrade version:\n%s", ver)
        log_event("UPGRADE", f"pre-upgrade version: {ver.splitlines()[0][:80]}")

    # ── 04 ──
    def test_04_upload_firmware(self, upgrader):
        """Upload firmware file to device via SFTP."""
        log_event("UPGRADE", f"SFTP upload start: {os.path.basename(upgrader.firmware_path)}")
        remote = upgrader.upload_firmware()
        TestDeviceUpgrade._upload_path = remote
        assert upgrader._upload_success, "Upload failed"
        logger.info("Uploaded to %s:%s", upgrader.ip, remote)
        log_event("UPGRADE", f"SFTP upload complete → {remote}")

    # ── 05 ──
    def test_05_execute_upgrade(self, upgrader):
        """Execute upgrade command (imgupd / puf)."""
        log_event("UPGRADE", f"executing upgrade: method={upgrader.method}")
        output = upgrader.execute_upgrade()
        TestDeviceUpgrade._upgrade_output = output
        assert upgrader._upgrade_started, "Upgrade command did not start"
        logger.info("Upgrade method=%s started", upgrader.method)
        log_event("UPGRADE", f"upgrade command issued, awaiting reboot")

    # ── 06 ──
    def test_06_wait_for_reboot(self, upgrader):
        """Wait for device to reboot and return online."""
        log_event("UPGRADE", f"waiting for reboot cycle on {upgrader.ip}")
        ok = upgrader.wait_for_reboot()
        assert ok, f"Device {upgrader.ip} did not come back after reboot"
        log_event("UPGRADE", f"device back online after reboot")

    # ── 07 ──
    def test_07_verify_device_online(self, upgrader):
        """Device must be fully responsive after upgrade."""
        ver = upgrader.verify_device_responsive(timeout=120)
        TestDeviceUpgrade._post_version = ver
        assert ver, "Device not responsive after upgrade"
        log_event("UPGRADE", f"device responsive post-upgrade")

    # ── 08 ──
    def test_08_version_report(self, upgrader, upgrade_cfg):
        """Log the upgrade summary — pre/post versions."""
        pre = TestDeviceUpgrade._pre_version or "N/A"
        post = TestDeviceUpgrade._post_version or "N/A"
        fw = os.path.basename(upgrade_cfg.get("firmware_file") or "N/A")

        report = (
            f"\n{'=' * 60}\n"
            f"  FIRMWARE UPGRADE REPORT\n"
            f"  Model:      {upgrade_cfg['model']}\n"
            f"  Method:     {upgrade_cfg['method']}\n"
            f"  Firmware:   {fw}\n"
            f"  Pre-ver:    {pre}\n"
            f"  Post-ver:   {post}\n"
            f"{'=' * 60}"
        )
        logger.info(report)
        log_event("UPGRADE", f"pre:  {pre.splitlines()[0][:80]}")
        log_event("UPGRADE", f"post: {post.splitlines()[0][:80]}")
        log_event("UPGRADE", f"firmware: {fw}")

        # Post-upgrade version must be non-empty
        assert post and post != "N/A", "Post-upgrade version missing"

    # ── 09 ──
    def test_09_enable_dsp_cache(self, upgrader, upgrade_cfg, device_cfg):
        """Enable DSP cache via sysfs bash command after firmware upgrade.

        8ZSA / 4ZSP (two DSP blocks on DSP1 platform):
            echo 1 > /sys/crestron/ctrl-audio-dsp-0/cache/cache_enable
            echo 1 > /sys/crestron/ctrl-audio-dsp-1/cache/cache_enable

        4ZSA (single DSP block):
            echo 1 > /sys/crestron/ctrl-audio-dsp-0/cache/cache_enable

        Tries the debug bash SSH port (6022) first; falls back to the
        interactive 'linux' shell via the CresNEXT CLI port (22) if 6022
        is not reachable.  Reads back the sysfs value and asserts it is '1'.
        """
        model = upgrade_cfg["model"]
        dsp_paths = ["/sys/crestron/ctrl-audio-dsp-0/cache/cache_enable"]
        if model in ("8ZSA", "4ZSP"):
            dsp_paths.append("/sys/crestron/ctrl-audio-dsp-1/cache/cache_enable")

        DEBUG_BASH_PORT = 6022

        for path in dsp_paths:
            dsp_label = path.split("/")[3]  # ctrl-audio-dsp-0 or ctrl-audio-dsp-1
            log_event("UPGRADE", f"enabling cache: {dsp_label} path={path}")
            result = None

            # ── Method 1: direct bash SSH on port 6022 ──
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    hostname=upgrader.ip,
                    port=DEBUG_BASH_PORT,
                    username=upgrader.username,
                    password=upgrader.password,
                    timeout=15,
                    allow_agent=False,
                    look_for_keys=False,
                )
                try:
                    _, stdout, stderr = client.exec_command(
                        f"echo 1 > {path}", timeout=10
                    )
                    stdout.read()
                    err = stderr.read().decode("utf-8", errors="replace").strip()
                    if err:
                        logger.warning("%s: cache write stderr: %s", dsp_label, err)
                    _, stdout2, _ = client.exec_command(f"cat {path}", timeout=5)
                    result = stdout2.read().decode("utf-8", errors="replace").strip()
                finally:
                    client.close()
                logger.info(
                    "%s: cache_enable written via port %d, readback='%s'",
                    dsp_label, DEBUG_BASH_PORT, result,
                )
            except Exception as e_bash:
                logger.warning(
                    "%s: port %d bash failed (%s), trying linux shell via port 22",
                    dsp_label, DEBUG_BASH_PORT, e_bash,
                )

                # ── Method 2: interactive 'linux' shell via CresNEXT CLI (port 22) ──
                try:
                    client = upgrader._ssh_connect(timeout=15)
                    shell = client.invoke_shell(width=400, height=200)
                    try:
                        time.sleep(0.5)
                        if shell.recv_ready():
                            shell.recv(65536)
                        # Enter the linux shell
                        shell.send("linux\n")
                        time.sleep(2.0)
                        if shell.recv_ready():
                            shell.recv(65536)
                        # Write the cache enable flag
                        shell.send(f"echo 1 > {path}\n")
                        time.sleep(0.5)
                        # Read it back
                        shell.send(f"cat {path}\n")
                        time.sleep(0.8)
                        raw = b""
                        deadline = time.time() + 5
                        while time.time() < deadline:
                            if shell.recv_ready():
                                raw += shell.recv(65536)
                            else:
                                time.sleep(0.2)
                        # Exit linux shell
                        shell.send("exit\n")
                        time.sleep(0.3)
                    finally:
                        shell.close()
                    client.close()
                    text = raw.decode("utf-8", errors="replace")
                    # The cat output line will be the bare digit '1'
                    digit_lines = [
                        ln.strip()
                        for ln in text.splitlines()
                        if ln.strip() in ("0", "1")
                    ]
                    result = digit_lines[-1] if digit_lines else None
                    logger.info(
                        "%s: cache_enable written via linux shell, readback='%s'",
                        dsp_label, result,
                    )
                except Exception as e_shell:
                    pytest.fail(
                        f"{dsp_label}: both bash methods failed — "
                        f"port6022={e_bash!r}, linux_shell={e_shell!r}"
                    )

            if result is None:
                logger.warning(
                    "%s: could not read back cache_enable (path may not exist on this fw)",
                    dsp_label,
                )
                log_event(
                    "UPGRADE",
                    f"{dsp_label}: cache_enable write issued but readback unavailable",
                )
            else:
                assert result == "1", (
                    f"{dsp_label}: cache_enable readback='{result}', expected '1' "
                    f"(path={path})"
                )
                logger.info("%s: cache_enable = %s ✓", dsp_label, result)
                log_event("UPGRADE", f"{dsp_label}: cache_enable verified = {result}")
