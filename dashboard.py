"""
Web Dashboard Server
Serves test results, historical trends, and individual reports.
Accessible by anyone on the network.
"""
import os
import json
import glob
import logging
from datetime import datetime
from flask import Flask, render_template, send_file, abort
import yaml

logger = logging.getLogger(__name__)

SUITE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SUITE_DIR, "templates")
RESULTS_DIR = os.path.join(SUITE_DIR, "results")
CONFIG_PATH = os.path.join(SUITE_DIR, "config", "devices.yaml")


def create_app():
    app = Flask(__name__, template_folder=TEMPLATE_DIR,
                static_folder=os.path.join(SUITE_DIR, "static"))

    @app.template_filter("fmt_duration")
    def fmt_duration(seconds):
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

    def _load_config():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)

    def _scan_results():
        """Scan result directories and build run history."""
        runs = []
        if not os.path.isdir(RESULTS_DIR):
            return runs

        for entry in sorted(os.listdir(RESULTS_DIR)):
            run_dir = os.path.join(RESULTS_DIR, entry)
            json_path = os.path.join(run_dir, "results.json")
            if not os.path.isfile(json_path):
                continue

            try:
                with open(json_path) as f:
                    data = json.load(f)
                summary = data.get("summary", {})
                env = data.get("environment", {})
                total = summary.get("total", 0)
                passed = summary.get("passed", 0)
                failed = summary.get("failed", 0)
                duration = round(summary.get("duration", 0), 1)
                pass_rate = round(passed / total * 100, 1) if total > 0 else 0

                # Read device info if saved
                info_path = os.path.join(run_dir, "device_info.json")
                device_info = {}
                if os.path.isfile(info_path):
                    with open(info_path) as f2:
                        device_info = json.load(f2)

                runs.append({
                    "id": entry,
                    "date": entry.replace("_", " "),
                    "date_short": entry[:10],
                    "device": device_info.get("model", "N/A"),
                    "firmware": device_info.get("version", "N/A"),
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "pass_rate": pass_rate,
                    "pass_pct": pass_rate,
                    "fail_pct": round(failed / total * 100, 1) if total > 0 else 0,
                    "duration": duration,
                })
            except Exception as e:
                logger.warning("Failed to parse %s: %s", json_path, e)

        return runs

    def _scan_run_summaries():
        """Scan for per-run summary directories (run_summary.json)."""
        summaries = []
        if not os.path.isdir(RESULTS_DIR):
            return summaries

        for entry in sorted(os.listdir(RESULTS_DIR)):
            summary_path = os.path.join(RESULTS_DIR, entry, "run_summary.json")
            if not os.path.isfile(summary_path):
                continue
            try:
                with open(summary_path) as f:
                    data = json.load(f)
                devices_failed = data.get("devices_failed", 0)
                devices_passed = data.get("devices_passed", 0)
                if devices_failed == 0:
                    status = "pass"
                elif devices_passed > 0:
                    status = "mixed"
                else:
                    status = "fail"
                device_names = ", ".join(t.get("target", "?") for t in data.get("targets", []))
                summaries.append({
                    "timestamp": data.get("timestamp", entry),
                    "date": entry.replace("_", " "),
                    "total_devices": data.get("total_devices", 0),
                    "devices_passed": devices_passed,
                    "devices_failed": devices_failed,
                    "total_tests": data.get("total_tests", 0),
                    "total_passed": data.get("total_passed", 0),
                    "total_failed": data.get("total_failed", 0),
                    "total_duration": data.get("total_duration", 0),
                    "status": status,
                    "device_names": device_names,
                })
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", summary_path, exc)

        return summaries

    @app.route("/")
    def dashboard():
        runs = _scan_results()
        latest_pass_rate = runs[-1]["pass_rate"] if runs else 0
        latest_device = runs[-1]["device"] if runs else "N/A"

        # Calculate streak
        streak_count = 0
        streak_status = "passing"
        for run in reversed(runs):
            if run["failed"] == 0:
                if streak_status == "passing":
                    streak_count += 1
                else:
                    break
            else:
                if streak_count == 0:
                    streak_status = "failing"
                    streak_count += 1
                else:
                    break

        return render_template("dashboard.html",
            runs=runs, total_runs=len(runs),
            latest_pass_rate=latest_pass_rate,
            latest_device=latest_device,
            streak_count=streak_count,
            streak_status=streak_status,
            run_summaries=_scan_run_summaries(),
        )

    @app.route("/history")
    def history():
        return dashboard()  # Same page, could be extended with filters

    @app.route("/devices")
    def devices():
        cfg = _load_config()
        dev_list = cfg.get("devices", {})
        return render_template("dashboard.html",
            runs=_scan_results(), total_runs=len(_scan_results()),
            latest_pass_rate=0, latest_device="N/A",
            streak_count=0, streak_status="unknown",
        )

    @app.route("/report/<run_id>")
    def view_report(run_id):
        # Sanitize to prevent path traversal
        safe_id = os.path.basename(run_id)
        report_path = os.path.join(RESULTS_DIR, safe_id, "report.html")
        if not os.path.isfile(report_path):
            abort(404)
        return send_file(report_path)

    @app.route("/run/<timestamp>")
    def view_run_index(timestamp):
        """Serve the per-run index page (lists all devices with report links)."""
        safe_ts = os.path.basename(timestamp)
        index_path = os.path.join(RESULTS_DIR, safe_ts, "index.html")
        if not os.path.isfile(index_path):
            abort(404)
        return send_file(index_path)

    @app.route("/api/results")
    def api_results():
        """JSON API for CI/CD integration."""
        runs = _scan_results()
        return json.dumps(runs, indent=2), 200, {"Content-Type": "application/json"}

    @app.route("/api/latest")
    def api_latest():
        runs = _scan_results()
        if not runs:
            return json.dumps({"error": "no results"}), 404
        return json.dumps(runs[-1], indent=2), 200, {"Content-Type": "application/json"}

    return app


def main():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    dash_cfg = cfg.get("dashboard", {})

    app = create_app()
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 5000)

    print(f"\n{'='*60}")
    print(f"  DM-NAX DSP Test Dashboard")
    print(f"  http://{host}:{port}")
    print(f"  Results dir: {RESULTS_DIR}")
    print(f"{'='*60}\n")

    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
