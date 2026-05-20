"""
CresNext REST API client for DM-NAX devices.
Provides authenticated HTTPS access to read and write device properties
via the CresNext JSON web services interface.
"""
import logging
import json
import time
import warnings
import requests
import urllib3
from .test_trace import log_event

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

logger = logging.getLogger(__name__)


class CresNextClient:
    """Authenticated REST client for CresNext device properties."""

    def __init__(self, ip, username="admin", password="crestron"):
        self.ip = ip
        self.username = username
        self.password = password
        self._session = None
        self._xsrf_token = None

    def connect(self, retries=5, retry_delay=10):
        """Establish an authenticated HTTPS session.

        Retries if the CresNext web server is not yet ready (e.g. after
        a firmware upgrade reboot cycle).
        """
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                self._try_connect()
                return
            except (requests.exceptions.ConnectionError, ConnectionError) as exc:
                last_exc = exc
                if attempt < retries:
                    logger.warning(
                        "CresNext connect attempt %d/%d to %s failed: %s — "
                        "retrying in %ds",
                        attempt, retries, self.ip, exc, retry_delay,
                    )
                    import time
                    time.sleep(retry_delay)
        raise ConnectionError(
            f"CresNext on {self.ip} not reachable after {retries} attempts"
        ) from last_exc

    def _try_connect(self):
        """Single connect attempt.

        Protocol negotiation:
          - Try HTTPS first (fw42 devices: 4ZSP, 8ZSA).
          - If HTTPS fails (connection refused / SSL error), fall back to HTTP
            (fw21 devices: 4ZSA, which may not serve HTTPS on port 443).
          - POST credentials to the same base URL that successfully served
            the GET, so the session cookie is valid for the POST.
        """
        self._session = requests.Session()
        self._session.verify = False

        # Determine working base URL: HTTPS preferred, HTTP fallback.
        base = f"https://{self.ip}"
        for candidate_base in (f"https://{self.ip}", f"http://{self.ip}"):
            login_headers = {
                "Origin": candidate_base,
                "Referer": f"{candidate_base}/index_banner.html",
            }
            try:
                log_event("CRESNEXT", f"GET {candidate_base}/userlogin.html")
                r = self._session.get(
                    f"{candidate_base}/userlogin.html",
                    headers=login_headers,
                    timeout=15,
                    allow_redirects=True,
                )
                # Successful response — use this base for the POST too.
                base = candidate_base
                break
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.SSLError,
                    requests.exceptions.Timeout):
                log_event("CRESNEXT",
                          f"GET {candidate_base}/userlogin.html failed, trying next")
                continue

        login_headers = {
            "Origin": base,
            "Referer": f"{base}/index_banner.html",
        }

        # POST credentials to the same base URL that served the GET.
        log_event("CRESNEXT", f"POST {base}/userlogin.html (login)")
        r = self._session.post(
            f"{base}/userlogin.html",
            data={"login": self.username, "passwd": self.password},
            headers=login_headers,
            timeout=15,
        )
        self._xsrf_token = r.headers.get("CREST-XSRF-TOKEN", "")
        if not self._xsrf_token:
            raise ConnectionError(f"Login failed for {self.ip}: no XSRF token returned")
        logger.info("CresNext session established to %s", self.ip)

    def disconnect(self):
        """Logout and close the session."""
        if self._session:
            try:
                self._session.get(
                    f"https://{self.ip}/logout",
                    headers=self._headers(),
                    timeout=10,
                )
            except Exception:
                pass
            self._session.close()
            self._session = None
            self._xsrf_token = None
            logger.info("CresNext session closed for %s", self.ip)

    def _headers(self):
        h = {}
        if self._xsrf_token:
            h["X-CREST-XSRF-TOKEN"] = self._xsrf_token
        return h

    def _ensure_connected(self):
        if not self._session or not self._xsrf_token:
            self.connect()

    def get(self, uri, retries=2):
        """GET a CresNext URI and return the parsed JSON object.

        Args:
            uri: CresNext path, e.g. '/Device/ZoneOutputs/Zones/Zone1/ZoneAudio/'
            retries: Number of retry attempts on transient ConnectionError.
        """
        self._ensure_connected()
        if not uri.startswith("/"):
            uri = "/" + uri
        last_exc = None
        for attempt in range(1, retries + 2):
            try:
                log_event("CRESNEXT", f"GET https://{self.ip}{uri}")
                r = self._session.get(
                    f"https://{self.ip}{uri}", headers=self._headers(), timeout=30
                )
                r.raise_for_status()
                payload = r.json()
                log_event("CRESNEXT", f"RESP {r.status_code} GET ok")
                return payload
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                if attempt <= retries:
                    logger.warning(
                        "CresNext GET %s attempt %d/%d failed: %s — reconnecting",
                        uri, attempt, retries + 1, exc,
                    )
                    time.sleep(2)
                    self._try_connect()
        raise last_exc

    def set(self, uri, body, retries=2):
        """POST a CresNext property change.

        Args:
            uri:  CresNext path, e.g. '/Device/ZoneOutputs/Zones/Zone1/ZoneAudio/'
            body: Nested dict matching the CresNext object structure.
            retries: Number of retry attempts on transient ConnectionError.
        """
        self._ensure_connected()
        if not uri.startswith("/"):
            uri = "/" + uri
        body_s = json.dumps(body, separators=(",", ":"))
        if len(body_s) > 500:
            body_s = body_s[:500] + "..."
        last_exc = None
        for attempt in range(1, retries + 2):
            try:
                log_event("CRESNEXT", f"POST https://{self.ip}{uri} body={body_s}")
                r = self._session.post(
                    f"https://{self.ip}{uri}",
                    json=body,
                    headers=self._headers(),
                    timeout=30,
                )
                r.raise_for_status()
                break
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                if attempt <= retries:
                    logger.warning(
                        "CresNext POST %s attempt %d/%d failed: %s — reconnecting",
                        uri, attempt, retries + 1, exc,
                    )
                    time.sleep(2)
                    self._try_connect()
                else:
                    raise
        result = r.json()
        status_items = []
        actions = result.get("Actions", [])
        for action in actions:
            for res in action.get("Results", []):
                status_items.append(f"{res.get('StatusId', 0)}:{res.get('StatusInfo', '')}")
        if status_items:
            log_event("CRESNEXT", f"RESP {r.status_code} POST statuses={'; '.join(status_items[:6])}")
        else:
            log_event("CRESNEXT", f"RESP {r.status_code} POST ok")
        # Check CresNext response for errors
        actions = result.get("Actions", [])
        for action in actions:
            for res in action.get("Results", []):
                status = res.get("StatusId", 0)
                info = res.get("StatusInfo", "")
                # StatusId 3 = "Value is same as previous" — benign, skip
                if status != 0 and status != 3:
                    raise RuntimeError(
                        f"CresNext error: {info} "
                        f"(path={res.get('Path')}, prop={res.get('Property')})"
                    )
        return result

    # ------------------------------------------------------------------
    # Convenience: Zone-level properties
    # ------------------------------------------------------------------
    def get_zone_info(self, zone):
        """Read zone-level properties (IsSignalDetected, Name, etc.)."""
        uri = f"/Device/ZoneOutputs/Zones/Zone{zone}/"
        data = self.get(uri)
        return (
            data.get("Device", {})
            .get("ZoneOutputs", {})
            .get("Zones", {})
            .get(f"Zone{zone}", {})
        )

    # ------------------------------------------------------------------
    # Convenience: Zone audio properties
    # ------------------------------------------------------------------
    def _zone_audio_uri(self, zone):
        return f"/Device/ZoneOutputs/Zones/Zone{zone}/ZoneAudio/"

    def _zone_audio_body(self, zone, **props):
        return {
            "Device": {
                "ZoneOutputs": {
                    "Zones": {
                        f"Zone{zone}": {
                            "ZoneAudio": props
                        }
                    }
                }
            }
        }

    def get_zone_audio(self, zone):
        """Read all ZoneAudio properties for a zone."""
        data = self.get(self._zone_audio_uri(zone))
        return (
            data.get("Device", {})
            .get("ZoneOutputs", {})
            .get("Zones", {})
            .get(f"Zone{zone}", {})
            .get("ZoneAudio", {})
        )

    def set_zone_audio(self, zone, **props):
        """Set one or more ZoneAudio properties.

        Examples:
            client.set_zone_audio(1, Volume=800)
            client.set_zone_audio(1, Balance=500, Bass=0)
            client.set_zone_audio(1, IsMuted=True)
            client.set_zone_audio(1, NightMode="Medium")
        """
        uri = self._zone_audio_uri(zone)
        body = self._zone_audio_body(zone, **props)
        logger.info("CresNext SET Zone%d: %s", zone, props)
        return self.set(uri, body)

    # ------------------------------------------------------------------
    # Convenience: AV Matrix Routing
    # ------------------------------------------------------------------
    def set_zone_source(self, zone, source):
        """Set the audio source for a zone via AvMatrixRouting."""
        uri = f"/Device/AvMatrixRouting/Routes/Zone{zone}/"
        body = {
            "Device": {
                "AvMatrixRouting": {
                    "Routes": {
                        f"Zone{zone}": {
                            "AudioSource": source
                        }
                    }
                }
            }
        }
        return self.set(uri, body)

    def clear_zone_route(self, zone):
        """Remove a zone's AvMatrixRouting entry entirely.

        Unlike ``set_zone_source(zone, "")`` (which keeps the route binding
        alive with an empty AudioSource), sending an empty-object body
        deletes the Zone{N} entry from Routes.  On fw42 (iMX8) this is
        required to fully sever the MediaStreamer audio source so it stops
        feeding residual noise (~-70 dB) into the zone amp output after
        a player has been stopped.
        """
        uri = f"/Device/AvMatrixRouting/Routes/Zone{zone}/"
        body = {
            "Device": {
                "AvMatrixRouting": {
                    "Routes": {
                        f"Zone{zone}": {}
                    }
                }
            }
        }
        return self.set(uri, body)

    def get_zone_source(self, zone):
        """Read the current AudioSource for a zone from AvMatrixRouting.

        Returns the AudioSource string (e.g. 'Input01', 'Input05') or None
        if the response does not contain the expected field.
        """
        uri = f"/Device/AvMatrixRouting/Routes/Zone{zone}/"
        data = self.get(uri)
        return (
            data.get("Device", {})
            .get("AvMatrixRouting", {})
            .get("Routes", {})
            .get(f"Zone{zone}", {})
            .get("AudioSource", None)
        )

    def set_zone_sources_streamrouting(self, zone_to_source):
        """Set multiple zone AudioSource values in one StreamRoutings-style call.

        Uses parent path and comma-separated zone/source lists (as documented in
        AP_TestCases StreamRoutings for MP1 on 8-zone platforms).
        """
        if not zone_to_source:
            return {}

        ordered = sorted((int(z), str(src)) for z, src in zone_to_source.items())
        zone_csv = ",".join(f"Zone{z}" for z, _ in ordered)
        source_csv = ",".join(src for _, src in ordered)

        uri = f"/Device/AvMatrixRouting/Routes/{zone_csv}/"
        body = {
            "Device": {
                "AvMatrixRouting": {
                    "Routes": {
                        zone_csv: {
                            "AudioSource": source_csv
                        }
                    }
                }
            }
        }
        logger.info("CresNext SET StreamRoutings %s -> %s", zone_csv, source_csv)
        return self.set(uri, body)

    # ------------------------------------------------------------------
    # Convenience: Input source properties
    # ------------------------------------------------------------------
    def set_input_mute(self, input_num, muted):
        """Mute/unmute an input source (1-indexed, e.g. Input01)."""
        input_key = f"Input{input_num:02d}"
        uri = f"/Device/InputSources/Inputs/{input_key}/SourceAudio/"
        body = {
            "Device": {
                "InputSources": {
                    "Inputs": {
                        input_key: {
                            "SourceAudio": {
                                "IsMuteEnabled": bool(muted)
                            }
                        }
                    }
                }
            }
        }
        logger.info("CresNext SET %s IsMuteEnabled=%s", input_key, muted)
        return self.set(uri, body)

    def get_input_source_audio(self, input_num):
        """Read SourceAudio properties for an input source (1-indexed)."""
        input_key = f"Input{input_num:02d}"
        uri = f"/Device/InputSources/Inputs/{input_key}/SourceAudio/"
        data = self.get(uri)
        return (
            data.get("Device", {})
            .get("InputSources", {})
            .get("Inputs", {})
            .get(input_key, {})
            .get("SourceAudio", {})
        )

    def set_input_compensation(self, input_num, compensation):
        """Set input SourceAudio Compensation (-100..100, in 0.1 dB steps)."""
        input_key = f"Input{input_num:02d}"
        uri = f"/Device/InputSources/Inputs/{input_key}/SourceAudio/"
        body = {
            "Device": {
                "InputSources": {
                    "Inputs": {
                        input_key: {
                            "SourceAudio": {
                                "Compensation": int(compensation)
                            }
                        }
                    }
                }
            }
        }
        logger.info("CresNext SET %s Compensation=%s", input_key, compensation)
        return self.set(uri, body)

    # ------------------------------------------------------------------
    # Convenience: EQ (PEQ) band properties
    # ------------------------------------------------------------------
    def _peq_band_uri(self, zone, band):
        return f"/Device/ZoneOutputs/Zones/Zone{zone}/ZoneAudio/Peq/Bands/Band{band:02d}/"

    def get_peq_band(self, zone, band):
        """Read a PEQ band's properties."""
        data = self.get(self._peq_band_uri(zone, band))
        return (
            data.get("Device", {})
            .get("ZoneOutputs", {})
            .get("Zones", {})
            .get(f"Zone{zone}", {})
            .get("ZoneAudio", {})
            .get("Peq", {})
            .get("Bands", {})
            .get(f"Band{band:02d}", {})
        )

    def set_peq_band(self, zone, band, **props):
        """Set PEQ band properties (Type, Gain, Frequency, Bandwidth, IsEqBypassEnabled)."""
        uri = self._peq_band_uri(zone, band)
        body = {
            "Device": {
                "ZoneOutputs": {
                    "Zones": {
                        f"Zone{zone}": {
                            "ZoneAudio": {
                                "Peq": {
                                    "Bands": {
                                        f"Band{band:02d}": props
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        logger.info("CresNext SET Zone%d Band%02d: %s", zone, band, props)
        return self.set(uri, body)

    # ------------------------------------------------------------------
    # Convenience: Speaker Protect
    # ------------------------------------------------------------------
    def get_speaker_protect(self, zone):
        """Read Speaker Protect properties for a zone."""
        uri = f"/Device/ZoneOutputs/Zones/Zone{zone}/ZoneAudio/Speaker/"
        data = self.get(uri)
        return (
            data.get("Device", {})
            .get("ZoneOutputs", {})
            .get("Zones", {})
            .get(f"Zone{zone}", {})
            .get("ZoneAudio", {})
            .get("Speaker", {})
        )

    def set_speaker_protect(self, zone, **props):
        """Set Speaker Protect properties (IsSpeakerProtectEnabled, Power, Impedance)."""
        uri = f"/Device/ZoneOutputs/Zones/Zone{zone}/ZoneAudio/Speaker/"
        body = {
            "Device": {
                "ZoneOutputs": {
                    "Zones": {
                        f"Zone{zone}": {
                            "ZoneAudio": {
                                "Speaker": props
                            }
                        }
                    }
                }
            }
        }
        logger.info("CresNext SET Zone%d Speaker: %s", zone, props)
        return self.set(uri, body)

    # ------------------------------------------------------------------
    # Convenience: Door Chimes
    # ------------------------------------------------------------------
    def get_chime_slot(self, slot):
        """Read a door chime slot (1-indexed → DefaultSlot01..DefaultSlot26)."""
        slot_key = f"DefaultSlot{slot:02d}"
        uri = f"/Device/DoorChimes/DefaultChimes/{slot_key}/"
        data = self.get(uri)
        return (
            data.get("Device", {})
            .get("DoorChimes", {})
            .get("DefaultChimes", {})
            .get(slot_key, {})
        )

    def set_chime_zone(self, slot, zone, enabled):
        """Enable/disable a zone for chime playback."""
        slot_key = f"DefaultSlot{slot:02d}"
        uri = f"/Device/DoorChimes/DefaultChimes/{slot_key}/PlaybackZones/Zone{zone}/"
        body = {
            "Device": {
                "DoorChimes": {
                    "DefaultChimes": {
                        slot_key: {
                            "PlaybackZones": {
                                f"Zone{zone}": {
                                    "IsEnabled": bool(enabled)
                                }
                            }
                        }
                    }
                }
            }
        }
        logger.info("CresNext SET Chime %s Zone%d IsEnabled=%s", slot_key, zone, enabled)
        return self.set(uri, body)

    def play_chime(self, slot):
        """Trigger chime playback."""
        slot_key = f"DefaultSlot{slot:02d}"
        uri = f"/Device/DoorChimes/DefaultChimes/{slot_key}/"
        body = {
            "Device": {
                "DoorChimes": {
                    "DefaultChimes": {
                        slot_key: {
                            "Play": True
                        }
                    }
                }
            }
        }
        logger.info("CresNext PLAY Chime %s", slot_key)
        return self.set(uri, body)

    def set_announcing_volume(self, zone, volume):
        """Set the announcing (chime) volume for a zone."""
        uri = f"/Device/ZoneOutputs/Zones/Zone{zone}/Announcing/"
        body = {
            "Device": {
                "ZoneOutputs": {
                    "Zones": {
                        f"Zone{zone}": {
                            "Announcing": {
                                "Volume": volume
                            }
                        }
                    }
                }
            }
        }
        return self.set(uri, body)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
