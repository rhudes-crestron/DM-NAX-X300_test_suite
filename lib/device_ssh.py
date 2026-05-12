"""
SSH session manager for DM-NAX devices.
Handles connection lifecycle, command execution, and automatic reconnection.
"""
import time
import logging
import socket
import shlex
import os
import glob
import tempfile
import subprocess
import shutil
from datetime import datetime
import paramiko
from .test_trace import log_event

logger = logging.getLogger(__name__)

ENG_DEBUG_NETWORK_ROOT = r"\\nj22l-fw-01\shares\NightlyBuild\AM335x_dinap3\eng_dbg"
ENG_DEBUG_LINUX_MOUNT_ROOT = "/mnt/nightly/AM335x_dinap3/eng_dbg"


class DeviceSSH:
    """Manages SSH connections to a DM-NAX device."""

    def __init__(self, ip, username, password, port=22, timeout=15):
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self._client = None
        self._eng_debug_tmpdir = None

    def connect(self):
        """Establish SSH connection to the device."""
        if self._client and self._client.get_transport() and self._client.get_transport().is_active():
            return
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=self.ip,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        logger.info("Connected to %s@%s:%d", self.username, self.ip, self.port)

    def disconnect(self):
        """Close the SSH connection."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Disconnected from %s", self.ip)

    def execute(self, command, timeout=15, trace_source="SSH"):
        """Execute a console command and return stdout as a string.

        Uses exec_command first.  Falls back to an interactive shell session
        when the device truncates output (common on fw42 4ZSP/8ZSA for the
        ``dsp`` command that produces wide, multi-block output).
        """
        attempts = 2
        last_err = None
        for attempt in range(1, attempts + 1):
            try:
                self.connect()
                logger.debug("CMD [%s]: %s", self.ip, command)
                log_event(trace_source, f"exec timeout={timeout}s cmd={command}")
                _, stdout, stderr = self._client.exec_command(command, timeout=timeout)

                # stdout.read() blocks indefinitely if the SSH channel never
                # sends EOF (seen with 'ampctrl FaultSt' on 4ZSP/8ZSA fw42).
                # Use the channel's exit-status event with an explicit deadline
                # instead of relying on the paramiko exec_command timeout alone.
                stdout.channel.settimeout(timeout)
                if not stdout.channel.exit_status_ready():
                    import select as _select
                    ready, _, _ = _select.select([stdout.channel], [], [], timeout)
                    if not ready:
                        stdout.channel.close()
                        raise TimeoutError(
                            f"SSH command timed out after {timeout}s: {command!r}"
                        )

                output = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                out_lines = [ln for ln in output.splitlines() if ln.strip()]
                if self._is_trace_summarized_command(command):
                    log_event(trace_source, "resp OK")
                elif self._is_dsp_state_command(command):
                    # For the DSP state dump the first line is always the version
                    # header which has no diagnostic value.  Log lines count only;
                    # dsp_controller.read_dsp_state() logs the parsed channel levels.
                    log_event(trace_source, f"resp lines={len(out_lines)}")
                else:
                    preview = out_lines[0][:220] if out_lines else "<empty>"
                    log_event(
                        trace_source,
                        f"resp lines={len(out_lines)} preview={preview}",
                    )
                if err:
                    logger.debug("STDERR [%s]: %s", self.ip, err.strip())
                    log_event(trace_source, f"stderr={err.strip()[:300]}")

                # Heuristic: if the command is "dsp" (state dump) and the output
                # looks truncated (has header but few data rows), retry via shell.
                if command.strip() in ("dsp", "dsp mix") and output.count("\n") < 12:
                    logger.debug("Output looks truncated (%d lines), retrying via shell", output.count("\n"))
                    output = self._execute_shell(command, timeout=timeout)

                return output
            except (TimeoutError, socket.timeout, paramiko.SSHException, EOFError) as e:
                last_err = e
                logger.warning(
                    "CMD timeout/transport error on %s attempt %d/%d for '%s': %s",
                    self.ip,
                    attempt,
                    attempts,
                    command,
                    e,
                )
                log_event(trace_source, f"retry {attempt}/{attempts} error={e}")
                self.disconnect()
                if attempt < attempts:
                    time.sleep(0.5)
                    continue
                raise

        raise ConnectionError(f"Command failed after retries: {last_err}")

    @staticmethod
    def _is_trace_summarized_command(command):
        """Return True when trace output should be summarized as OK.

        Tone/mixer commands usually echo the DSP table header as first line,
        which adds noise to per-test trace logs without diagnostic value.
        """
        cmd = command.strip().lower()
        return cmd.startswith("dsp tone") or cmd.startswith("dsp mix")

    @staticmethod
    def _is_dsp_state_command(command):
        """Return True for the bare 'dsp' state-dump command.

        The first output line is always the version header, not the channel
        data.  read_dsp_state() logs parsed channel levels separately.
        """
        return command.strip().lower() == "dsp"

    def _execute_shell(self, command, timeout=15):
        """Execute a command via an interactive shell session.

        Used as a fallback when exec_command truncates output on certain
        firmware versions.
        """
        self.connect()
        shell = self._client.invoke_shell(width=400, height=200)
        import time as _time
        _time.sleep(0.5)
        # Drain login banner
        if shell.recv_ready():
            shell.recv(65536)

        shell.send(command + "\n")
        _time.sleep(1.5)

        output = b""
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            if shell.recv_ready():
                output += shell.recv(65536)
                _time.sleep(0.2)
            else:
                _time.sleep(0.3)
                if not shell.recv_ready():
                    break

        shell.close()
        text = output.decode("utf-8", errors="replace")
        # Strip the echoed command and the trailing prompt
        lines = text.split("\n")
        # Remove first line (echoed command) and last line (prompt)
        if lines and command in lines[0]:
            lines = lines[1:]
        if lines and lines[-1].strip().endswith(">"):
            lines = lines[:-1]
        return "\n".join(lines)

    def _read_shell_until(self, shell, prompt, timeout):
        """Read from an interactive shell until prompt text is seen or timeout expires."""
        import time as _time

        output = b""
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            if shell.recv_ready():
                output += shell.recv(65536)
                text = output.decode("utf-8", errors="replace")
                if prompt in text:
                    return text
                _time.sleep(0.1)
            else:
                _time.sleep(0.1)

        raise TimeoutError(f"Timed out waiting for prompt '{prompt}'")

    def _execute_bash_via_console(self, command, timeout=20):
        """Enter linux shell from console prompt and execute one bash command."""
        import time as _time

        self.connect()
        shell = self._client.invoke_shell(width=400, height=200)
        try:
            _time.sleep(0.3)
            if shell.recv_ready():
                shell.recv(65536)

            shell.send("linux\n")
            linux_resp = self._read_shell_until(shell, "#", timeout=min(timeout, 8))
            if "Invalid" in linux_resp or "denied" in linux_resp.lower():
                raise PermissionError(f"linux shell rejected: {linux_resp.strip()[:240]}")

            shell.send(command + "\n")
            cmd_resp = self._read_shell_until(shell, "#", timeout=timeout)

            shell.send("exit\n")
            try:
                self._read_shell_until(shell, ">", timeout=3)
            except Exception:
                pass

            lines = cmd_resp.splitlines()
            if lines and lines[0].strip() == command.strip():
                lines = lines[1:]
            if lines and lines[-1].strip().endswith("#"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
        finally:
            shell.close()

    def _execute_via_debug_ssh(self, command, timeout=20, debug_port=6022):
        """Run a command directly over the debug SSH port if available."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.ip,
                port=debug_port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            output = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if err and not output:
                raise RuntimeError(err)
            return output
        finally:
            client.close()

    def execute_bash(self, command, timeout=20):
        """Execute a command from unit-side bash, preferring debug SSH then linux shell."""
        last_err = None
        for runner in (self._execute_via_debug_ssh, self._execute_bash_via_console):
            try:
                out = runner(command, timeout=timeout)
                log_event("BASH", f"cmd={command}")
                preview = out.splitlines()[0][:220] if out else "<empty>"
                log_event("BASH", f"resp preview={preview}")
                return out
            except Exception as e:
                last_err = e
        raise ConnectionError(f"Failed to execute bash command on {self.ip}: {last_err}")

    def curl_bash(self, url, method="GET", body=None, timeout=10):
        """Run curl on the unit and return (status_code, response_text).

        The -H value is passed as a single shell-quoted argument so that the
        space in "Content-Type: application/json" does not cause bash to split
        it into two tokens, which would make curl treat "application/json" as a
        second URL (producing a spurious HTTP 000 entry in -w output that
        corrupts the response payload parsed below).
        """
        cmd = [
            "curl",
            "-sS",
            "-m", str(max(3, int(timeout))),
            "-X", method.upper(),
            "-H", shlex.quote("Content-Type: application/json"),
        ]
        if body is not None:
            cmd.extend(["--data", shlex.quote(body)])
        cmd.extend([shlex.quote(url), "-w", shlex.quote("\\nHTTP_STATUS:%{http_code}")])
        raw = self.execute_bash(" ".join(cmd), timeout=timeout + 5)
        marker = "HTTP_STATUS:"
        if marker not in raw:
            return 0, raw.strip()
        payload, status_part = raw.rsplit(marker, 1)
        try:
            code = int(status_part.strip().splitlines()[0])
        except Exception:
            code = 0
        return code, payload.strip()

    def can_open_bash(self):
        """Return True if the unit accepts bash commands via debug/console path."""
        try:
            probe = self.execute_bash("echo BASH_OK", timeout=8)
            return "BASH_OK" in probe
        except Exception:
            return False

    def is_engineering_debug_enabled(self):
        """Check whether engineering debug mode is enabled on the unit."""
        try:
            ver = self.execute("ver -v", timeout=20)
        except Exception:
            return False
        upper = ver.upper()
        return ("ENG DEBUG MODE: TRUE" in upper) or ("ENG_DEBUG_MODE: TRUE" in upper)

    def _find_engineering_debug_zip(
        self,
        zip_file=None,
        search_roots=None,
        smb_username=None,
        smb_password=None,
        smb_domain=None,
    ):
        """Locate latest engineering debug zip from the nightly share location."""

        def _pick_latest(root_path):
            candidates = glob.glob(os.path.join(root_path, "engineering_debug.zip.2*"))
            candidates = [p for p in candidates if os.path.isfile(p) and os.path.getsize(p) > 0]
            if candidates:
                candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                return candidates[0]

            fallback = os.path.join(root_path, "engineering_debug.zip")
            if os.path.isfile(fallback) and os.path.getsize(fallback) > 0:
                return fallback
            return None

        # Windows build servers can access UNC directly; Linux workers need SMB client access.
        if os.name == "nt":
            root = ENG_DEBUG_NETWORK_ROOT
            if not os.path.isdir(root):
                raise FileNotFoundError(
                    "Unable to access engineering debug share root: "
                    f"{root}. Nightly buildserver must have access to this UNC path."
                )
            chosen = _pick_latest(root)
            if chosen:
                return chosen

            raise FileNotFoundError(
                "Unable to locate engineering_debug.zip on share root: "
                f"{root}"
            )

        # Linux build servers use the mounted nightly path directly.
        local_root = ENG_DEBUG_LINUX_MOUNT_ROOT
        if os.path.isdir(local_root):
            chosen = _pick_latest(local_root)
            if chosen:
                return chosen
            raise FileNotFoundError(
                "Mounted nightly path is accessible but no engineering_debug.zip found at: "
                f"{local_root}"
            )

        # Fallback: pull from UNC via smbclient when local mount is unavailable.
        root = ENG_DEBUG_NETWORK_ROOT
        return self._fetch_from_unc_share_linux(
            root,
            smb_username=smb_username,
            smb_password=smb_password,
            smb_domain=smb_domain,
        )

    def _fetch_from_unc_share_linux(self, unc_root, smb_username=None, smb_password=None, smb_domain=None):
        """Fetch latest engineering_debug zip from UNC share using smbclient."""
        if not unc_root.startswith("\\\\"):
            raise FileNotFoundError(f"Expected UNC share path, got: {unc_root}")

        if not shutil.which("smbclient"):
            raise FileNotFoundError(
                "smbclient is required to access UNC share on Linux. "
                f"Install smbclient to fetch from {unc_root}"
            )

        parts = [p for p in unc_root.lstrip("\\").split("\\") if p]
        if len(parts) < 3:
            raise FileNotFoundError(f"Invalid UNC root path: {unc_root}")

        server = parts[0]
        share = parts[1]
        subdir = "/".join(parts[2:])
        service = f"//{server}/{share}"

        tmpdir = tempfile.mkdtemp(prefix="engdbg_")
        self._eng_debug_tmpdir = tmpdir

        user = smb_username or os.getenv("ENG_DEBUG_SMB_USERNAME")
        pw = smb_password or os.getenv("ENG_DEBUG_SMB_PASSWORD")
        dom = smb_domain or os.getenv("ENG_DEBUG_SMB_DOMAIN")

        def _run_get(pattern):
            cmd = (
                f'cd "{subdir}"; prompt OFF; recurse OFF; mget "{pattern}"'
            )
            smb_cmd = ["smbclient", service]
            if user:
                auth_user = f"{dom}\\{user}" if dom else user
                smb_cmd.extend(["-U", f"{auth_user}%{pw or ''}"])
            else:
                smb_cmd.append("-N")
            smb_cmd.extend(["-c", cmd])
            return subprocess.run(
                smb_cmd,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

        r1 = _run_get("engineering_debug.zip.2*")
        r2 = _run_get("engineering_debug.zip")

        candidates = glob.glob(os.path.join(tmpdir, "engineering_debug.zip.2*"))
        candidates = [p for p in candidates if os.path.isfile(p) and os.path.getsize(p) > 0]
        if candidates:
            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return candidates[0]

        fallback = os.path.join(tmpdir, "engineering_debug.zip")
        if os.path.isfile(fallback) and os.path.getsize(fallback) > 0:
            return fallback

        detail = (r1.stderr or r1.stdout or "") + "\n" + (r2.stderr or r2.stdout or "")
        raise FileNotFoundError(
            "Unable to locate engineering_debug.zip from UNC share via smbclient: "
            f"{unc_root}. smbclient output: {detail.strip()[:500]}"
        )

    def _upload_file_sftp(self, local_path, remote_path):
        """Upload a file to the DUT via SFTP using current SSH credentials."""
        self.connect()
        sftp = self._client.open_sftp()
        try:
            # Ensure firmware folder path exists if remote path is nested.
            remote_dir = os.path.dirname(remote_path)
            if remote_dir:
                try:
                    sftp.stat(remote_dir)
                except Exception:
                    # Device usually has firmware path already; best-effort mkdir.
                    try:
                        sftp.mkdir(remote_dir)
                    except Exception:
                        pass
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def enable_engineering_debug(
        self,
        zip_file=None,
        search_roots=None,
        set_current_datetime=False,
        remote_zip_path="firmware/engineering_debug.zip",
        smb_username=None,
        smb_password=None,
        smb_domain=None,
    ):
        """Enable engineering debug mode (VETest-style) and verify it."""
        if self.is_engineering_debug_enabled():
            logger.info("Engineering debug already enabled on %s", self.ip)
            return True

        if set_current_datetime:
            now = datetime.now()
            self.execute(
                "TIMEdate {hh:02d}:{mm:02d}:{ss:02d} {mo:02d}-{dd:02d}-{yy:04d}".format(
                    hh=now.hour,
                    mm=now.minute,
                    ss=now.second,
                    mo=now.month,
                    dd=now.day,
                    yy=now.year,
                ),
                timeout=15,
            )

        local_zip = self._find_engineering_debug_zip(
            zip_file=zip_file,
            search_roots=search_roots,
            smb_username=smb_username,
            smb_password=smb_password,
            smb_domain=smb_domain,
        )
        logger.info("Uploading engineering debug payload from %s", local_zip)
        self._upload_file_sftp(local_zip, remote_zip_path)

        # Mirror VETest flow: apply eng debug image update and verify ver -v.
        self.execute("imgupd engdbg", timeout=120)

        if not self.is_engineering_debug_enabled():
            ver = self.execute("ver -v", timeout=20)
            raise RuntimeError(f"Failed to enable engineering debug on {self.ip}. ver -v: {ver}")

        logger.info("Engineering debug enabled on %s", self.ip)
        return True

    def execute_retry(self, command, retries=2, delay=2.0, timeout=15):
        """Execute with automatic retry on failure."""
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                return self.execute(command, timeout=timeout)
            except Exception as e:
                last_err = e
                logger.warning("Attempt %d/%d failed for '%s': %s", attempt, retries, command, e)
                self.disconnect()
                if attempt < retries:
                    time.sleep(delay)
        raise ConnectionError(f"Command failed after {retries} attempts: {last_err}")

    def is_reachable(self):
        """Check if the device responds to a basic command."""
        try:
            output = self.execute("ver", timeout=10)
            return bool(output.strip())
        except Exception:
            return False

    def get_version(self):
        """Return device firmware version string."""
        output = self.execute("ver")
        return output.strip()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
