"""
Firmware upgrade handler for DM-NAX devices.

Supports:
  - imgupd method (4ZSA .zip files)
  - puf method (8ZSA .puf files)

Follows the timing sequences from the nightly UpdateScripts
(ThreeSeriesPuf.ps1 and Imgupd.ps1).
"""
import os
import time
import socket
import logging
import paramiko

from lib.test_trace import log_event

logger = logging.getLogger(__name__)


class FirmwareUpgrader:
    """Handles firmware upload and upgrade for DM-NAX devices.

    Upgrade flow (matching PowerShell UpdateScripts):
      1. Connect SSH, capture pre-upgrade version ('ver')
      2. Upload firmware via SFTP to remote firmware/ directory
      3. Issue upgrade command:
         - 4ZSA: 'imgupd'  (picks up .zip from firmware/)
         - 8ZSA: 'puf <filename> ALL -D -V'  (processes .puf)
      4. Wait for device to go offline (port closes)
      5. Wait for device to come back online (port opens)
      6. Settle, then verify with 'ver'
    """

    # ── Timing constants (from UpdateScripts) ──
    IMGUPD_CMD_TIMEOUT = 120   # imgupd response timeout (Imgupd.ps1 line ~Prompt timeout)
    PUF_CMD_TIMEOUT = 300      # puf command can take a while for multi-component
    PORT_DOWN_TIMEOUT = 600    # max wait for port to close (reboot start)
    PORT_UP_TIMEOUT = 600      # max wait for port to re-open (reboot done)
    POST_DOWN_SLEEP = 10       # sleep after port goes down (Imgupd.ps1: Start-SleepLog 10)
    POST_UP_SETTLE = 30        # settle after port comes back (Imgupd.ps1: Start-SleepLog 20 + margin)
    PUF_REBOOT_GRACE = 120     # extra grace period for PUF — reboot can be delayed after cmd returns
    POLL_INTERVAL = 5          # connectivity poll interval

    def __init__(self, ip, username, password, firmware_path,
                 method="imgupd", ssh_port=22, remote_dir="firmware"):
        self.ip = ip
        self.username = username
        self.password = password
        self.firmware_path = firmware_path
        self.method = method.lower()
        self.ssh_port = ssh_port
        self.remote_dir = remote_dir
        self.firmware_filename = os.path.basename(firmware_path)
        self.pre_version = None
        self.post_version = None
        self._upload_success = False
        self._upgrade_started = False

    # ── SSH helpers ──

    def _ssh_connect(self, timeout=30):
        """Create a fresh SSH connection to the device."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.ip,
            port=self.ssh_port,
            username=self.username,
            password=self.password,
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        return client

    def _ssh_execute(self, client, command, timeout=30):
        """Execute a command on an open SSH client."""
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err

    # ── Connectivity probes ──

    def is_port_open(self, port=None, timeout=5):
        """Check if a TCP port is reachable on the device."""
        port = port or self.ssh_port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                return sock.connect_ex((self.ip, port)) == 0
        except Exception:
            return False

    def is_device_responsive(self, timeout=15):
        """True if the device responds to an SSH 'ver' command."""
        try:
            client = self._ssh_connect(timeout=timeout)
            out, _ = self._ssh_execute(client, "ver", timeout=10)
            client.close()
            return bool(out.strip())
        except Exception:
            return False

    # ── Core operations ──

    def get_version(self):
        """Return the firmware version string from the device."""
        client = self._ssh_connect()
        try:
            out, _ = self._ssh_execute(client, "ver", timeout=15)
            return out.strip()
        finally:
            client.close()

    def upload_firmware(self):
        """Upload firmware to the device via SFTP.

        Mirrors UpdateScripts behaviour:
          - Clears existing files in the remote firmware/ directory
          - Uploads the new firmware file
          - Verifies the size matches

        Returns:
            str: remote file path
        """
        if not os.path.isfile(self.firmware_path):
            raise FileNotFoundError(f"Firmware file not found: {self.firmware_path}")

        file_size = os.path.getsize(self.firmware_path)
        log_event("UPGRADE", f"SFTP upload: {self.firmware_filename} ({file_size} bytes) → {self.ip}:{self.remote_dir}/")
        logger.info(
            "Uploading '%s' (%d bytes) to %s:%s/",
            self.firmware_filename, file_size, self.ip, self.remote_dir,
        )

        client = self._ssh_connect(timeout=30)
        try:
            sftp = client.open_sftp()

            # Ensure remote directory exists
            try:
                sftp.stat(self.remote_dir)
            except IOError:
                logger.info("Creating remote directory: %s", self.remote_dir)
                sftp.mkdir(self.remote_dir)

            # Remove old firmware files  (ThreeSeriesPuf.ps1: Remove-FTPDirectory -ContentsOnly)
            try:
                for name in sftp.listdir(self.remote_dir):
                    remote_file = f"{self.remote_dir}/{name}"
                    logger.info("Removing old file: %s", remote_file)
                    try:
                        sftp.remove(remote_file)
                    except Exception as exc:
                        logger.warning("Could not remove %s: %s", remote_file, exc)
            except Exception as exc:
                logger.warning("Could not list %s: %s", self.remote_dir, exc)

            # Upload
            remote_path = f"{self.remote_dir}/{self.firmware_filename}"
            logger.info("SFTP PUT: %s -> %s", self.firmware_path, remote_path)
            sftp.put(self.firmware_path, remote_path)

            # Verify size
            remote_stat = sftp.stat(remote_path)
            if remote_stat.st_size != file_size:
                raise RuntimeError(
                    f"Upload size mismatch: local={file_size}, "
                    f"remote={remote_stat.st_size}"
                )
            logger.info("Upload verified: %d bytes", remote_stat.st_size)
            log_event("UPGRADE", f"upload verified: {remote_stat.st_size} bytes OK")

            sftp.close()
            self._upload_success = True
            return remote_path
        finally:
            client.close()

    def execute_upgrade(self):
        """Issue the upgrade command on the device.

        Returns:
            str: command output
        """
        if not self._upload_success:
            raise RuntimeError("Firmware must be uploaded before executing upgrade")

        client = self._ssh_connect(timeout=30)
        try:
            if self.method == "imgupd":
                return self._execute_imgupd(client)
            elif self.method == "puf":
                return self._execute_puf(client)
            else:
                raise ValueError(f"Unknown upgrade method: {self.method}")
        finally:
            try:
                client.close()
            except Exception:
                pass  # connection may already be dead

    def _execute_imgupd(self, client):
        """4ZSA: issue 'imgupd' — device picks up .zip from firmware/."""
        log_event("UPGRADE", f"SSH cmd: imgupd on {self.ip}")
        logger.info(
            "Executing 'imgupd' on %s (timeout=%ds) …",
            self.ip, self.IMGUPD_CMD_TIMEOUT,
        )
        out, _ = self._ssh_execute(client, "imgupd", timeout=self.IMGUPD_CMD_TIMEOUT)
        logger.info("imgupd response: %s", out.strip()[:500])
        if "error" in out.lower():
            raise RuntimeError(f"imgupd error: {out.strip()}")
        log_event("UPGRADE", f"imgupd accepted: {out.strip()[:80]}")
        self._upgrade_started = True
        return out

    def _execute_puf(self, client):
        """8ZSA: issue 'puf <filename> ALL -D -V'."""
        cmd = f"puf {self.firmware_filename} ALL -D -V"
        log_event("UPGRADE", f"SSH cmd: {cmd} on {self.ip}")
        logger.info(
            "Executing '%s' on %s (timeout=%ds) …",
            cmd, self.ip, self.PUF_CMD_TIMEOUT,
        )
        out, _ = self._ssh_execute(client, cmd, timeout=self.PUF_CMD_TIMEOUT)
        logger.info("PUF response: %s", out.strip()[:500])
        log_event("UPGRADE", f"puf response: {out.strip()[:80]}")
        self._upgrade_started = True
        return out

    # ── Reboot wait (Imgupd.ps1 timing sequence) ──

    def wait_for_reboot(self, check_port=None):
        """Wait for the device to reboot: go offline, then come back.

        Sequence (from Imgupd.ps1):
          1. Poll until port closes  (PORT_DOWN_TIMEOUT)
          2. Sleep POST_DOWN_SLEEP
          3. Poll until port opens   (PORT_UP_TIMEOUT)
          4. Sleep POST_UP_SETTLE

        For PUF upgrades, if the port never closes (delayed reboot), we
        wait an extra grace period then check if we lost connectivity,
        and finally wait for recovery.

        Returns:
            bool: True if device came back online
        """
        check_port = check_port or self.ssh_port

        # Phase 1 — wait for device to go offline
        logger.info(
            "Waiting for %s port %d to close (timeout=%ds) …",
            self.ip, check_port, self.PORT_DOWN_TIMEOUT,
        )
        log_event("UPGRADE", f"waiting for device to go offline (port {check_port})")
        t0 = time.time()
        went_offline = False
        while time.time() - t0 < self.PORT_DOWN_TIMEOUT:
            if not self.is_port_open(check_port, timeout=3):
                went_offline = True
                logger.info("Device offline after %.1fs", time.time() - t0)
                log_event("UPGRADE", f"device offline after {time.time() - t0:.1f}s")
                break
            time.sleep(self.POLL_INTERVAL)

        if not went_offline:
            # PUF can trigger a delayed reboot — the port may still be open
            # because the device hasn't started rebooting yet.  Wait a grace
            # period and re-check.
            if self.method == "puf":
                logger.info(
                    "Port stayed open — PUF delayed reboot grace %ds …",
                    self.PUF_REBOOT_GRACE,
                )
                grace_t0 = time.time()
                while time.time() - grace_t0 < self.PUF_REBOOT_GRACE:
                    if not self.is_port_open(check_port, timeout=3):
                        went_offline = True
                        logger.info(
                            "Device offline after grace period (%.1fs total)",
                            time.time() - t0,
                        )
                        break
                    time.sleep(self.POLL_INTERVAL)

            if not went_offline:
                logger.warning(
                    "Device did not go offline within %ds — may have rebooted quickly",
                    self.PORT_DOWN_TIMEOUT,
                )

        # Phase 2 — post-offline sleep
        logger.info("Post-offline sleep %ds …", self.POST_DOWN_SLEEP)
        time.sleep(self.POST_DOWN_SLEEP)

        # Phase 3 — wait for device to come back
        logger.info(
            "Waiting for %s port %d to open (timeout=%ds) …",
            self.ip, check_port, self.PORT_UP_TIMEOUT,
        )
        t0 = time.time()
        came_online = False
        while time.time() - t0 < self.PORT_UP_TIMEOUT:
            if self.is_port_open(check_port, timeout=3):
                came_online = True
                logger.info("Device online after %.1fs", time.time() - t0)
                log_event("UPGRADE", f"device back online after {time.time() - t0:.1f}s")
                break
            time.sleep(self.POLL_INTERVAL)

        if not came_online:
            raise TimeoutError(
                f"Device {self.ip} did not come back within {self.PORT_UP_TIMEOUT}s"
            )

        # Phase 4 — settling time
        logger.info("Post-reboot settling %ds …", self.POST_UP_SETTLE)
        time.sleep(self.POST_UP_SETTLE)

        return True

    def verify_device_responsive(self, timeout=120):
        """Poll SSH until device responds to 'ver'.

        Returns:
            str: version string
        """
        logger.info("Verifying device %s is responsive …", self.ip)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                version = self.get_version()
                if version:
                    logger.info("Device responsive — version: %s", version)
                    log_event("UPGRADE", f"post-upgrade version: {version.splitlines()[0][:80]}")
                    self.post_version = version
                    return version
            except Exception as exc:
                logger.debug("Not yet responsive: %s", exc)
            time.sleep(self.POLL_INTERVAL)

        raise TimeoutError(
            f"Device {self.ip} not responsive within {timeout}s after reboot"
        )

    # ── Convenience: full upgrade sequence ──

    def run_full_upgrade(self):
        """Run the complete upgrade end-to-end.

        Returns:
            dict with pre_version, post_version, success, details
        """
        result = {
            "pre_version": None,
            "post_version": None,
            "success": False,
            "method": self.method,
            "firmware_file": self.firmware_filename,
            "details": [],
        }
        try:
            result["pre_version"] = self.get_version()
            self.pre_version = result["pre_version"]
            result["details"].append(f"Pre-upgrade version: {result['pre_version']}")

            remote = self.upload_firmware()
            result["details"].append(f"Uploaded to: {remote}")

            output = self.execute_upgrade()
            result["details"].append(f"Upgrade output: {output[:200]}")

            self.wait_for_reboot()
            result["details"].append("Reboot complete")

            result["post_version"] = self.verify_device_responsive()
            self.post_version = result["post_version"]
            result["details"].append(f"Post-upgrade version: {result['post_version']}")

            result["success"] = True
        except Exception as exc:
            result["details"].append(f"Error: {exc}")
            logger.error("Upgrade failed: %s", exc)
            raise

        return result
