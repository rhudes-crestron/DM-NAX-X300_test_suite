"""
SSH session manager for DM-NAX devices.
Handles connection lifecycle, command execution, and automatic reconnection.
"""
import time
import logging
import paramiko

logger = logging.getLogger(__name__)


class DeviceSSH:
    """Manages SSH connections to a DM-NAX device."""

    def __init__(self, ip, username, password, port=22, timeout=15):
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self._client = None

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

    def execute(self, command, timeout=15):
        """Execute a console command and return stdout as a string.

        Uses exec_command first.  Falls back to an interactive shell session
        when the device truncates output (common on fw42 4ZSP/8ZSA for the
        ``dsp`` command that produces wide, multi-block output).
        """
        self.connect()
        logger.debug("CMD [%s]: %s", self.ip, command)
        _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        output = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if err:
            logger.debug("STDERR [%s]: %s", self.ip, err.strip())

        # Heuristic: if the command is "dsp" (state dump) and the output
        # looks truncated (has header but few data rows), retry via shell.
        if command.strip() in ("dsp", "dsp mix") and output.count("\n") < 12:
            logger.debug("Output looks truncated (%d lines), retrying via shell", output.count("\n"))
            output = self._execute_shell(command, timeout=timeout)

        return output

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
