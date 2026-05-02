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
import pytest

from lib.firmware_upgrader import FirmwareUpgrader

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

    # ── 02 ──
    def test_02_device_reachable(self, upgrader):
        """Device must be reachable via SSH before upgrade."""
        assert upgrader.is_device_responsive(timeout=15), (
            f"Device {upgrader.ip} not reachable"
        )

    # ── 03 ──
    def test_03_pre_upgrade_version(self, upgrader):
        """Capture current firmware version."""
        ver = upgrader.get_version()
        assert ver, "Failed to read device version"
        TestDeviceUpgrade._pre_version = ver
        logger.info("Pre-upgrade version:\n%s", ver)

    # ── 04 ──
    def test_04_upload_firmware(self, upgrader):
        """Upload firmware file to device via SFTP."""
        remote = upgrader.upload_firmware()
        TestDeviceUpgrade._upload_path = remote
        assert upgrader._upload_success, "Upload failed"
        logger.info("Uploaded to %s:%s", upgrader.ip, remote)

    # ── 05 ──
    def test_05_execute_upgrade(self, upgrader):
        """Execute upgrade command (imgupd / puf)."""
        output = upgrader.execute_upgrade()
        TestDeviceUpgrade._upgrade_output = output
        assert upgrader._upgrade_started, "Upgrade command did not start"
        logger.info("Upgrade method=%s started", upgrader.method)

    # ── 06 ──
    def test_06_wait_for_reboot(self, upgrader):
        """Wait for device to reboot and return online."""
        ok = upgrader.wait_for_reboot()
        assert ok, f"Device {upgrader.ip} did not come back after reboot"

    # ── 07 ──
    def test_07_verify_device_online(self, upgrader):
        """Device must be fully responsive after upgrade."""
        ver = upgrader.verify_device_responsive(timeout=120)
        TestDeviceUpgrade._post_version = ver
        assert ver, "Device not responsive after upgrade"

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

        # Post-upgrade version must be non-empty
        assert post and post != "N/A", "Post-upgrade version missing"
