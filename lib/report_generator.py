"""
HTML Report Generator
Produces beautiful, company-publishable HTML reports with test flow diagrams,
categorized results, and interactive charts.
"""
import os
import json
import logging
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")

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
             "stream_in": "Input05-08", "upgrade": "imgupd (.zip)", "fw": "fw21"},
    "8ZSA": {"sg": "28", "sg_name": "SIG", "zones": 8, "out1": "A1L",
             "stream_in": "Input05-12", "upgrade": "puf ALL (.puf)", "fw": "fw42"},
    "4ZSP": {"sg": "0",  "sg_name": "T1L", "zones": 8, "out1": "A1L",
             "stream_in": "Input05-12", "upgrade": "puf ALL (.puf)", "fw": "fw42"},
}


def _get_category_paths(model="4ZSA"):
    """Return per-category signal-path diagrams appropriate for the device model."""
    p = _DEVICE_PARAMS.get(model, _DEVICE_PARAMS["4ZSA"])
    sg = p["sg"]
    out1 = p["out1"]
    stream_in = p["stream_in"]
    upgrade = p["upgrade"]

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
            ("SSH: dsp \u2192 output_db per freq", "measure"),
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
            ("SSH: dsp \u2192 output_db per level", "measure"),
            ("Assert \u0394 output = \u0394 input \u00b11 dB", "verify"),
        ],
        "Signal Routing": [
            (f"SSH: dsp tone {sg}", "input"),
            ("SSH: dsp mix N\u2192out", "highlight"),
            ("DSP processing", "process"),
            ("SSH: dsp \u2192 ducker_db", "measure"),
            ("Assert level > floor", "verify"),
        ],
        "Volume": [
            ("SSH: dsp tone + mix", "input"),
            ("REST: Volume=0-1000", "highlight"),
            ("DSP processing", "process"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert level \u0394", "verify"),
        ],
        "Balance": [
            ("SSH: dsp tone + mix L+R", "input"),
            ("REST: Balance=\u00b1500", "highlight"),
            ("DSP processing", "process"),
            ("SSH: dsp \u2192 L/R output_db", "measure"),
            ("Assert L/R diff", "verify"),
        ],
        "Bass Treble": [
            ("SSH: dsp tone 100Hz/10kHz", "input"),
            (f"SSH: dsp mix \u2192 {out1}", "process"),
            ("REST: Bass/Treble=\u00b1120", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert level \u0394", "verify"),
        ],
        "Delay": [
            ("SSH: dsp tone + mix", "input"),
            ("REST: DelayInms=0-85", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("REST GET \u2192 DelayInms", "measure"),
            ("Assert signal + readback", "verify"),
        ],
        "Mute": [
            ("SSH: dsp tone + mix", "input"),
            ("REST: IsMuted=true", "highlight"),
            ("DSP processing", "process"),
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
            ("SSH: dsp gain ch set dB", "highlight"),
            ("SSH: dsp \u2192 gain_db", "measure"),
            ("Assert gain_db \u2248 set", "verify"),
        ],
        "Loudness": [
            ("SSH: dsp tone 100Hz", "input"),
            (f"SSH: dsp mix \u2192 {out1}", "process"),
            ("REST: Volume=400 (low)", "process"),
            ("REST: Loudness=true", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert boost \u0394", "verify"),
        ],
        "Tone Profiles": [
            ("SSH: dsp tone + mix", "input"),
            ("REST: ToneProfile=name", "highlight"),
            ("SSH: dsp \u2192 output_db", "measure"),
            ("Assert signal present", "verify"),
        ],
        "Night Mode": [
            ("SSH: dsp tone @ -6dB", "input"),
            (f"SSH: dsp mix \u2192 {out1}", "process"),
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


def generate_report(results_json_path, output_html_path, device_info=None):
    """Generate an HTML report from pytest JSON results."""
    with open(results_json_path) as f:
        data = json.load(f)

    tests = data.get("tests", [])
    summary = data.get("summary", {})
    env_info = data.get("environment", {})

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
    duration = summary.get("duration", 0)
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
    template = env.get_template("report.html")
    html = template.render(**context)

    with open(output_html_path, "w") as f:
        f.write(html)

    logger.info("Report generated: %s", output_html_path)
    return output_html_path
