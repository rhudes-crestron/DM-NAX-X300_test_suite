"""
HTML Report Generator
Produces beautiful, company-publishable HTML reports with test flow diagrams,
categorized results, and interactive charts.
"""
import os
import json
import logging
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")


def _fmt_duration(seconds):
    """Format a duration in seconds as a human-readable string.

    Examples: 45s, 7m 30s, 1h 23m
    """
    seconds = int(seconds or 0)
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    if seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{seconds}s"

# ── Per-category signal-path diagrams ──
# Each entry is an ordered list of (label, css_class) tuples showing the
# actual test flow.  css_class values:
#   input     = signal source / stimulus
#   process   = DSP processing stage (not under test)
#   highlight = the stage being tested
#   measure   = how we read/measure the result
#   verify    = the assertion

# Device-specific parameters for diagrams
_DEVICE_PARAMS = {
    "4ZSA": {"sg": "28", "sg_name": "SIG", "zones": 4, "out1": "A1L",
             "stream_in": "Input05-08", "upgrade": "imgupd (.zip)", "fw": "fw21",
             "fw_ver": 21},
    "8ZSA": {"sg": "0",  "sg_name": "T1L", "zones": 8, "out1": "A1L",
             "stream_in": "Input05-12", "upgrade": "puf ALL (.puf)", "fw": "fw42",
             "fw_ver": 42},
    "4ZSP": {"sg": "0",  "sg_name": "T1L", "zones": 8, "out1": "A1L",
             "stream_in": "Input05-12", "upgrade": "puf ALL (.puf)", "fw": "fw42",
             "fw_ver": 42},
}


def _get_category_paths(model="4ZSA"):
    """Return per-category signal-path diagrams appropriate for the device model."""
    p = _DEVICE_PARAMS.get(model, _DEVICE_PARAMS["4ZSA"])
    sg = p["sg"]
    out1 = p["out1"]
    stream_in = p["stream_in"]
    upgrade = p["upgrade"]
    fw42 = p.get("fw_ver", 21) >= 42

    # On fw42 the zone chain is only active when AvMatrixRouting assigns the
    # input to the zone.  The mixer is still needed to deliver the digital
    # tone signal to the output measurement point (output_db).
    # On fw21 the mixer feeds INTO the zone chain, so dsp mix alone is correct.
    zone_route_step = (
        (f"REST: AvMatrixRouting + dsp mix {sg}\u2192out", "process") if fw42
        else (f"SSH: dsp mix {sg}\u2192{out1}", "process")
    )

    return {
        "Device Upgrade": [
            ("Find firmware", "input"),
            (f"SFTP upload \u2192 firmware/", "process"),
            (f"SSH: {upgrade}", "highlight"),
            ("Wait reboot cycle", "process"),
            ("SSH: ver (post)", "measure"),
            ("Assert device online + version", "verify"),
        ],
        "Streaming": [
            (f"REST: AudioSource={stream_in}", "input"),
            ("HTTP srv: WAV file", "process"),
            ("Player: setSource + play", "highlight"),
            ("DSP board: output_db", "measure"),
            ("Assert level -20\u00b15 dB", "verify"),
        ],
        "Freq Response": [
            (f"SSH: dsp tone {sg} @freq,-20", "input"),
            (f"SSH: dsp mix {sg}\u2192{out1}", "process"),
            ("DSP processing (flat)", "process"),
            ("SSH: dsp \u2192 ducker_db per freq", "measure"),
            ("Assert \u00b10.5 dB flatness", "verify"),
        ],
        "Signal To Noise": [
            ("SSH: dsp (idle, no tone)", "input"),
            ("SSH: dsp \u2192 noise floor", "measure"),
            ("SSH: dsp tone + mix", "input"),
            ("SSH: dsp \u2192 signal level", "measure"),
            ("Assert SNR > 70 dB", "verify"),
        ],
        "Clipping": [
            (f"SSH: dsp tone {sg} @var gain", "input"),
            (f"SSH: dsp mix {sg}\u2192{out1}", "process"),
            ("DSP processing (full gain)", "process"),
            ("SSH: dsp agc \u2192 gain_reduction", "measure"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert no AGC + output tracks", "verify"),
        ],
        "Crosstalk": [
            (f"SSH: dsp tone {sg} @1kHz,-20", "input"),
            (f"SSH: dsp mix {sg}\u2192ONE ch", "highlight"),
            ("DSP processing", "process"),
            ("SSH: dsp \u2192 ALL output_db", "measure"),
            ("Assert active hot, others < -80", "verify"),
        ],
        "Level Linearity": [
            (f"SSH: dsp tone {sg} @var gain", "input"),
            (f"SSH: dsp mix {sg}\u2192{out1}", "process"),
            ("DSP processing (linear)", "process"),
            ("SSH: dsp \u2192 ducker_db per level", "measure"),
            ("Assert \u0394 output = \u0394 input \u00b11 dB", "verify"),
        ],
        "Signal Routing": [
            (f"SSH: dsp tone {sg}", "input"),
            ("SSH: dsp mix N\u2192out", "highlight"),
            ("DSP processing", "process"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert level > floor", "verify"),
        ],
        "Volume": [
            (f"SSH: dsp tone {sg}", "input"),
            zone_route_step,
            ("REST: Volume=0-1000", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert level \u0394", "verify"),
        ],
        "Balance": [
            (f"SSH: dsp tone {sg}", "input"),
            zone_route_step,
            ("REST: Balance=\u00b1500", "highlight"),
            ("SSH: dsp \u2192 L/R output_db", "measure"),
            ("Assert L/R diff", "verify"),
        ],
        "Bass Treble": [
            ("SSH: dsp tone 100Hz/10kHz", "input"),
            zone_route_step,
            ("REST: Bass/Treble=\u00b1120", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert level \u0394", "verify"),
        ],
        "Delay": [
            (f"SSH: dsp tone {sg}", "input"),
            zone_route_step,
            ("REST: DelayInms=0-85", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("REST GET \u2192 DelayInms", "measure"),
            ("Assert signal + readback", "verify"),
        ],
        "Mute": [
            (f"SSH: dsp tone {sg}", "input"),
            zone_route_step,
            ("REST: IsMuted=true", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert < -80 dB", "verify"),
        ],
        "Input Mute": [
            ("REST: IsMuteEnabled=true", "highlight"),
            ("REST GET SourceAudio", "measure"),
            ("Assert readback match", "verify"),
        ],
        "Input Compensation": [
            ("SSH: dsp tone on ch", "input"),
            ("REST: SourceAudio Compensation", "highlight"),
            ("REST GET SourceAudio", "measure"),
            ("SSH: dsp \u2192 gain_db + ducker_db", "measure"),
            ("Assert readback + output \u0394", "verify"),
        ],
        "Loudness": [
            ("SSH: dsp tone 100Hz", "input"),
            zone_route_step,
            ("REST: Volume=400 (low)", "process"),
            ("REST: Loudness=true", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert boost \u0394", "verify"),
        ],
        "Tone Profiles": [
            (f"SSH: dsp tone {sg}", "input"),
            zone_route_step,
            ("REST: ToneProfile=name", "highlight"),
            ("REST GET ZoneAudio", "measure"),
            ("SSH: dsp \u2192 output_db @ 200/1k/8k", "measure"),
            ("Assert profile \u2260 Off (\u0394)", "verify"),
        ],
        "Night Mode": [
            ("SSH: dsp tone @ -6dB", "input"),
            zone_route_step,
            ("REST: NightMode=Off/Lo/Med/Hi", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert level \u2264 Off", "verify"),
        ],
        "Amp Health": [
            ("SSH: ampctrl", "input"),
            ("SSH: ampctrl FaultSt", "measure"),
            ("SSH: ampctrl DacIceStatus", "measure"),
            ("Assert no faults", "verify"),
        ],
        "Eq": [
            (f"SSH: dsp tone {sg}", "input"),
            zone_route_step,
            ("REST: PEQ Band Type/Gain/Freq/BW", "highlight"),
            ("REST: IsEqBypassEnabled", "highlight"),
            ("REST GET \u2192 band readback", "measure"),
            ("Assert readback match", "verify"),
            ("SSH: dsp \u2192 output_db \u0394", "verify"),
        ],
        "Speaker Protect": [
            ("SSH: dsp tone + mix", "input"),
            ("REST: IsSpeakerProtectEnabled", "highlight"),
            ("REST: Power / Impedance", "highlight"),
            ("REST GET \u2192 Speaker readback", "measure"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert readback + level", "verify"),
        ],
        "Chimes": [
            ("REST: set_chime_zone enable", "highlight"),
            ("REST: Play=true (trigger)", "highlight"),
            ("REST: Announcing Volume", "process"),
            ("REST GET \u2192 slot readback", "measure"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert readback + audio", "verify"),
        ],
        "Bridging": [
            ("REST GET \u2192 ZoneConfiguration", "measure"),
            ("REST GET \u2192 SupportedConfigs", "measure"),
            ("REST GET \u2192 Stereo/Routes", "measure"),
            ("SSH: dsp tone + mix", "input"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert Standard + signal", "verify"),
        ],
    }


def _load_trace_logs(results_dir):
    """Load per-test trace logs from the test_logs/ subdirectory.

    Returns a dict mapping nodeid fragments to trace-log content strings.
    File names follow the convention produced by lib/test_trace.py:
      tests_test_signal_routing.py_TestSignalRouting_test_device_reachable.log
    We build a lookup key from the nodeid by replacing '/' and '::' with '_'.
    """
    trace_dir = os.path.join(results_dir, "test_logs")
    logs = {}
    if not os.path.isdir(trace_dir):
        return logs

    for fname in os.listdir(trace_dir):
        if not fname.endswith(".log"):
            continue
        key = fname[:-4]  # strip .log
        path = os.path.join(trace_dir, fname)
        try:
            with open(path, errors="replace") as f:
                logs[key] = f.read()
        except OSError:
            pass
    return logs


def _nodeid_to_trace_key(nodeid):
    """Convert a pytest nodeid to the trace-log filename stem.

    Must mirror lib/test_trace._sanitize_nodeid exactly:
      re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid).strip("_")[:220]

    Example: tests/test_bass_treble.py::TestBassTreble::test_bass_changes_level[120-boost +12dB-1]
           → tests_test_bass_treble.py_TestBassTreble_test_bass_changes_level_120-boost_12dB-1
    """
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid)
    return key.strip("_")[:220] or "unknown_test"


_TRACE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<src>[^\]]+)\]\s+(?P<msg>.*)$")


def _trace_kind(message):
    """Classify a trace line as Request/Response/Event."""
    msg = (message or "").strip()
    upper = msg.upper()
    if upper.startswith("RESP ") or upper.startswith("STDERR="):
        return "Response"
    if msg.startswith("GET ") or msg.startswith("POST "):
        return "Request"
    if "CMD=" in upper or upper.startswith("EXEC "):
        return "Request"
    return "Event"


def _parse_trace_steps(trace_text):
    """Convert raw trace text into numbered, chronological step records."""
    if not trace_text:
        return []

    steps = []
    for line in trace_text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        # Keep test boundary markers as events
        if raw.startswith("=== TEST START") or raw.startswith("=== TEST END"):
            steps.append({"time": "", "source": "TEST", "kind": "Event", "message": raw})
            continue

        m = _TRACE_RE.match(raw)
        if not m:
            # Carry any unmatched line as generic event so nothing is lost
            steps.append({"time": "", "source": "TRACE", "kind": "Event", "message": raw})
            continue

        msg = m.group("msg")
        steps.append(
            {
                "time": m.group("ts"),
                "source": m.group("src"),
                "kind": _trace_kind(msg),
                "message": msg,
            }
        )
    return steps


def generate_report(results_json_path, output_html_path, device_info=None):
    """Generate an HTML report from pytest JSON results."""
    with open(results_json_path) as f:
        data = json.load(f)

    tests = data.get("tests", [])
    summary = data.get("summary", {})
    env_info = data.get("environment", {})

    # Attach per-test trace logs (SSH/CresNext command traces)
    # Also compute a flat 'duration' field per test from the nested
    # setup/call/teardown phases (pytest-json-report stores them separately).
    results_dir = os.path.dirname(results_json_path)
    trace_logs = _load_trace_logs(results_dir)
    for test in tests:
        nodeid = test.get("nodeid", "")
        key = _nodeid_to_trace_key(nodeid)
        trace_text = trace_logs.get(key, "")
        test["_trace_log"] = trace_text
        test["_trace_steps"] = _parse_trace_steps(trace_text)

        # Attach the module-level reset log so every test row has a
        # dedicated "reset" button.  The log file is named:
        #   _module_reset_<module_name>.log
        # where module_name = nodeid file part converted to dotted module path.
        # e.g. tests/test_balance.py  →  tests.test_balance
        file_part = nodeid.split("::")[0]          # e.g. tests/test_balance.py
        module_name = file_part.replace("/", ".")
        if module_name.endswith(".py"):
            module_name = module_name[:-3]
        reset_key = f"_module_reset_{module_name}"
        reset_text = trace_logs.get(reset_key, "")
        test["_reset_log"] = reset_text
        test["_reset_steps"] = _parse_trace_steps(reset_text)

        # Compute total duration from phases
        if "duration" not in test:
            d = 0.0
            for phase in ("setup", "call", "teardown"):
                phase_data = test.get(phase)
                if isinstance(phase_data, dict):
                    d += phase_data.get("duration", 0)
            test["duration"] = d

    # Categorize tests
    categories = {}
    for test in tests:
        nodeid = test.get("nodeid", "")
        # Extract category from test file name: tests/test_volume.py -> volume
        parts = nodeid.split("::")
        file_part = parts[0] if parts else ""
        cat = file_part.replace("tests/test_", "").replace(".py", "").replace("_", " ").title()
        if cat not in categories:
            categories[cat] = {"tests": [], "pass": 0, "fail": 0, "skip": 0, "error": 0}
        categories[cat]["tests"].append(test)
        outcome = test.get("outcome", "unknown")
        if outcome == "passed":
            categories[cat]["pass"] += 1
        elif outcome == "failed":
            categories[cat]["fail"] += 1
        elif outcome == "skipped":
            categories[cat]["skip"] += 1
        else:
            categories[cat]["error"] += 1

    total = len(tests)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    errors = summary.get("error", 0)
    # Total duration lives at JSON root (pytest-json-report), not in summary
    duration = data.get("duration", 0) or summary.get("duration", 0)
    pass_rate = round((passed / total * 100), 1) if total > 0 else 0

    # Attach signal path diagrams to each category (device-aware)
    model = (device_info or {}).get("model", "4ZSA")
    category_paths = _get_category_paths(model)
    for cat_name in categories:
        categories[cat_name]["path"] = category_paths.get(cat_name, [])

    # Build template context
    context = {
        "title": "DM-NAX DSP Test Report",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "device_info": device_info or {},
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
            "duration": round(duration, 1),
            "pass_rate": pass_rate,
        },
        "categories": categories,
        "tests": tests,
    }

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters["fmt_duration"] = _fmt_duration
    template = env.get_template("report.html")
    html = template.render(**context)

    with open(output_html_path, "w") as f:
        f.write(html)

    logger.info("Report generated: %s", output_html_path)
    return output_html_path


def generate_run_index(summary, output_dir):
    """Generate a per-run index.html that links to each device's report.

    Args:
        summary: dict from run_summary.json (timestamp, targets[], totals)
        output_dir: directory to write index.html into (results/{timestamp}/)

    Returns:
        str: path to the generated index.html
    """
    # Add relative report links for each device target
    for target in summary.get("targets", []):
        report_html = target.get("report_html", "")
        if report_html and os.path.isfile(report_html):
            # Use the Flask /report/<run_id> route so links work when served
            # by the dashboard.  run_id is the basename of the device results dir.
            run_id = os.path.basename(os.path.dirname(report_html))
            target["report_link"] = f"/report/{run_id}"
        else:
            target["report_link"] = ""

    context = {
        "timestamp": summary.get("timestamp", ""),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "targets": summary.get("targets", []),
        "total_devices": summary.get("total_devices", 0),
        "devices_passed": summary.get("devices_passed", 0),
        "devices_failed": summary.get("devices_failed", 0),
        "total_tests": summary.get("total_tests", 0),
        "total_passed": summary.get("total_passed", 0),
        "total_failed": summary.get("total_failed", 0),
        "total_duration": summary.get("total_duration", 0),
    }

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.filters["fmt_duration"] = _fmt_duration
    template = env.get_template("run_index.html")
    html = template.render(**context)

    output_path = os.path.join(output_dir, "index.html")
    with open(output_path, "w") as f:
        f.write(html)

    logger.info("Run index generated: %s", output_path)
    return output_path
