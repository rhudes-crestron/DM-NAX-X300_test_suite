"""
Streaming Player Client — HTTP API wrapper for DM-NAX MediaStreamer.

Each DM-NAX zone has a media player accessible via HTTP.
Port 60000 is the system port; zone players start at 60001.

Port mapping:
    System  → port 60000
    Zone 1  → port 60001  (playerId = 1)
    Zone 2  → port 60002  (playerId = 2)
    Zone N  → port 60000 + N

The device can run in MP1 (MediaStreamer) or MP2 (MediaStreamerV2) mode:
  - MP2 API requires profileId, service, and playerId in request bodies.
  - MP1 API derives session from the HTTP port; bodies carry only command data.

The mode is detected at runtime via the SSH command ``mediaplayer``
which returns "MediaplayerMode MP1" or "MediaplayerMode MP2".
"""
import logging
import time
import json

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_PORT = 60001     # Zone 1 starts at 60001
PLAY_SETTLE_S = 5.0           # Time to let playback stabilise after play
SERVICE_TIMEOUT_S = 10        # HTTP timeout for service calls
PLAYER_TIMEOUT_S = 120        # HTTP timeout for player calls (device does HEAD redirect check)
PROFILE_ID = "dsp_test_suite" # Session profile identifier

# Media player mode constants
MODE_MP1 = "MP1"
MODE_MP2 = "MP2"


def detect_mediaplayermode(ssh):
    """Detect the MediaPlayer mode (MP1/MP2) via SSH.

    Runs the ``mediaplayer`` console command and parses the output.
    Returns MODE_MP1 or MODE_MP2 (defaults to MP2 if detection fails).
    """
    try:
        output = ssh.execute("mediaplayer", timeout=5)
        # Output format: "MediaplayerMode MP1" or "MediaplayerMode MP2"
        for line in output.splitlines():
            line = line.strip()
            if "MP2" in line.upper():
                logger.info("Detected MediaPlayer mode: MP2")
                return MODE_MP2
            if "MP1" in line.upper():
                logger.info("Detected MediaPlayer mode: MP1")
                return MODE_MP1
        logger.warning("Could not parse mediaplayer output: %r, defaulting to MP2", output)
        return MODE_MP2
    except Exception as e:
        logger.warning("Failed to detect mediaplayermode via SSH: %s, defaulting to MP2", e)
        return MODE_MP2


class StreamingPlayerClient:
    """Control a single media-player instance on a DM-NAX device."""

    def __init__(self, device_ip, port, profile_id=PROFILE_ID, mode=MODE_MP2, ssh=None):
        self.device_ip = device_ip
        self.port = port
        self.base_url = f"http://{device_ip}:{port}/api/v1"
        self.profile_id = profile_id
        self.mode = mode
        self.ssh = ssh
        # playerId = port - 60001 + 1  (V2 formula from common-utils.js)
        self.player_id = port - 60000
        self._service_active = False

    def _request(self, method, endpoint, body=None, timeout=PLAYER_TIMEOUT_S):
        """Execute a player API call via on-unit curl when bash is available."""
        if self.ssh:
            status, text = self.ssh.curl_bash(
                url=endpoint,
                method=method,
                body=None if body is None else json.dumps(body),
                timeout=timeout,
            )
            if status == 0 or status >= 400:
                raise requests.HTTPError(
                    f"HTTP {status} for {method} {endpoint}: {text[:300]}"
                )
            if not text:
                return {}
            try:
                    return json.loads(text)
            except Exception:
                return {"raw": text}

        r = requests.request(method, endpoint, json=body, timeout=timeout)
        r.raise_for_status()
        if not r.text:
            return {}
        return r.json()

    def _session_body(self, **extra):
        """Build the common session fields for V2 API calls."""
        body = {
            "profileId": self.profile_id,
            "service": "generic",
            "playerId": self.player_id,
        }
        body.update(extra)
        return body

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------
    def start_service(self, service_id="generic"):
        """Create a generic service session (idempotent — 409 if exists)."""
        url = f"{self.base_url}/services/{service_id}"
        body = {"profileId": self.profile_id} if self.mode == MODE_MP2 else {}
        if self.ssh:
            status, text = self.ssh.curl_bash(
                url=url,
                method="POST",
                body=json.dumps(body),
                timeout=SERVICE_TIMEOUT_S,
            )
            if status == 409:
                logger.debug("Player %d: session already active", self.port)
                self._service_active = True
                return json.loads(text) if text else {}
            if status >= 400 or status == 0:
                raise requests.HTTPError(f"HTTP {status} for POST {url}: {text[:300]}")
            payload = json.loads(text) if text else {}
            self._service_active = True
            logger.info("Player %d: started service '%s' (mode=%s, via=curl)", self.port, service_id, self.mode)
            return payload

        r = requests.post(url, json=body, timeout=SERVICE_TIMEOUT_S)
        if r.status_code == 409:
            logger.debug("Player %d: session already active", self.port)
            self._service_active = True
            return r.json() if r.text else {}
        r.raise_for_status()
        self._service_active = True
        logger.info("Player %d: started service '%s' (mode=%s)", self.port, service_id, self.mode)
        return r.json()

    def stop_service(self, service_id="generic"):
        """Delete the service session."""
        if self.mode == MODE_MP2:
            url = f"{self.base_url}/services/{service_id}"
            body = self._session_body()
        else:
            url = f"{self.base_url}/services/{service_id}"
            body = {}
        try:
            self._request("DELETE", url, body=body, timeout=SERVICE_TIMEOUT_S)
        except Exception as e:
            logger.warning("Player %d: stop_service failed: %s", self.port, e)
        self._service_active = False
        logger.info("Player %d: stopped service '%s'", self.port, service_id)

    # ------------------------------------------------------------------
    # Source and playback
    # ------------------------------------------------------------------
    def set_source(self, url, source_type="remote"):
        """Set audio source URL on the player."""
        if self.mode == MODE_MP2:
            # V2: PUT /services/generic/source with session body
            endpoint = f"{self.base_url}/services/generic/source"
            body = self._session_body(type=source_type, source=url)
            payload = self._request("PUT", endpoint, body=body, timeout=PLAYER_TIMEOUT_S)
        else:
            # V1: POST /player/setSource — session derived from port
            endpoint = f"{self.base_url}/player/setSource"
            body = {"type": source_type, "source": url}
            payload = self._request("POST", endpoint, body=body, timeout=PLAYER_TIMEOUT_S)
        logger.info("Player %d: setSource → %s (mode=%s)", self.port, url, self.mode)
        return payload

    def play(self):
        """Start playback."""
        body = self._session_body() if self.mode == MODE_MP2 else {}
        payload = self._request("PUT", f"{self.base_url}/player/play", body=body, timeout=PLAYER_TIMEOUT_S)
        logger.info("Player %d: play", self.port)
        return payload

    def stop(self):
        """Stop playback."""
        try:
            body = self._session_body() if self.mode == MODE_MP2 else {}
            payload = self._request("PUT", f"{self.base_url}/player/stop", body=body, timeout=PLAYER_TIMEOUT_S)
            logger.info("Player %d: stop", self.port)
            return payload
        except Exception as e:
            logger.warning("Player %d: stop failed (may already be stopped): %s",
                           self.port, e)
            return {}

    def status(self):
        """Get player status (no session needed)."""
        return self._request("GET", f"{self.base_url}/player/status", body=None, timeout=PLAYER_TIMEOUT_S)

    @property
    def state_name(self):
        """Current player state name (READY, PLAYING, STOPPED, etc.)."""
        try:
            st = self.status()
            return (st.get("payload", {})
                      .get("player", {})
                      .get("state", {})
                      .get("name", "UNKNOWN"))
        except Exception:
            return "ERROR"

    @property
    def is_playing(self):
        return self.state_name == "PLAYING"

    # ------------------------------------------------------------------
    # Combined helpers
    # ------------------------------------------------------------------
    def start_streaming(self, audio_url, settle_s=None):
        """Full startup: service → source → play → settle.

        Returns True if player reaches PLAYING state.
        """
        if settle_s is None:
            settle_s = PLAY_SETTLE_S

        self.start_service("generic")
        self.set_source(audio_url)
        self.play()

        time.sleep(settle_s)
        playing = self.is_playing
        if not playing:
            logger.warning(
                "Player %d: not PLAYING after %.1fs settle (state=%s)",
                self.port, settle_s, self.state_name,
            )
        return playing

    def stop_streaming(self):
        """Full shutdown: stop playback → delete session."""
        self.stop()
        self.stop_service("generic")

    def __repr__(self):
        return f"StreamingPlayerClient({self.device_ip}:{self.port})"


class StreamingPlayerManager:
    """Manage all media-player instances on a DM-NAX device."""

    def __init__(self, device_ip, num_zones, base_port=DEFAULT_BASE_PORT, mode=MODE_MP2, ssh=None):
        self.device_ip = device_ip
        self.num_zones = num_zones
        self.base_port = base_port
        self.mode = mode
        self.ssh = ssh
        self.players = {}
        for zone in range(1, num_zones + 1):
            port = base_port + (zone - 1)
            self.players[zone] = StreamingPlayerClient(device_ip, port, mode=mode, ssh=ssh)

    def get_player(self, zone):
        return self.players[zone]

    def start_all(self, audio_urls, settle_s=None):
        """Start streaming on all zones.

        Args:
            audio_urls: dict {zone: url} or list [url1, url2, ...] (1-indexed)
            settle_s: seconds to wait after the last play command
        """
        if isinstance(audio_urls, list):
            audio_urls = {z + 1: u for z, u in enumerate(audio_urls)}

        for zone, url in sorted(audio_urls.items()):
            player = self.players[zone]
            player.start_service("generic")
            player.set_source(url)
            player.play()

        wait = settle_s if settle_s is not None else PLAY_SETTLE_S
        time.sleep(wait)

    def stop_all(self):
        for zone in sorted(self.players.keys()):
            self.players[zone].stop_streaming()

    def status_all(self):
        result = {}
        for zone, player in sorted(self.players.items()):
            try:
                result[zone] = player.status()
            except Exception as e:
                result[zone] = {"error": str(e)}
        return result
