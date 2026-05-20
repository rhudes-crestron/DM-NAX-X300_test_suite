"""
Email notification for DM-NAX nightly test runs.

Sends an HTML summary email after each orchestrator run with a link
to the per-run index page on the dashboard.  Optionally attaches
per-device zip archives of test_logs/ for offline debugging.
"""
import io
import json
import logging
import os
import smtplib
import zipfile
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


def _fmt_duration(seconds):
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


def _failed_test_log_names(results_dir):
    """Return set of test_log filenames that correspond to failed tests.

    Reads all_results.json to find failed test nodeids and maps them to the
    log filename convention: tests_<file>_<Class>_<method>_<param>.log
    """
    results_path = Path(results_dir) / "all_results.json"
    if not results_path.exists():
        return None  # Can't filter; fall back to including all
    try:
        with open(results_path) as f:
            data = json.load(f)
        tests = data.get("tests", [])
        failed_names = set()
        for t in tests:
            if t.get("outcome") != "passed":
                # nodeid: "tests/test_streaming.py::TestClass::test_method[param]"
                nodeid = t.get("nodeid", "")
                # Convert to log filename
                name = nodeid.replace("/", "_").replace("::", "_").replace("[", "_").replace("]", "")
                name = name.rstrip("_") + ".log"
                failed_names.add(name)
        return failed_names if failed_names else None
    except Exception:
        return None


def _create_test_logs_zip(results_dir, device_name, max_bytes=1_000_000):
    """Create an in-memory zip of test_logs/ for a device run.

    If the full zip exceeds max_bytes, retries with only failed-test logs.
    Returns (zip_bytes, filename) or None if no logs exist.
    """
    logs_dir = Path(results_dir) / "test_logs"
    if not logs_dir.is_dir():
        return None

    log_files = sorted(logs_dir.glob("*.log"))
    if not log_files:
        return None

    def _zip_files(files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in files:
                zf.write(fp, arcname=fp.name)
        return buf.getvalue()

    # Try full archive first
    zip_data = _zip_files(log_files)
    if len(zip_data) <= max_bytes:
        filename = f"{device_name}_test_logs.zip"
        logger.info("Zip %s: %d files, %d KB", filename, len(log_files), len(zip_data) // 1024)
        return zip_data, filename

    # Over limit — fall back to failed-test logs only
    logger.info("Full zip for %s is %d KB (over %d KB limit), using failed-only",
                device_name, len(zip_data) // 1024, max_bytes // 1024)
    failed_names = _failed_test_log_names(results_dir)
    if failed_names:
        failed_files = [f for f in log_files if f.name in failed_names]
        # Also include module reset logs for context
        failed_files += [f for f in log_files if f.name.startswith("module_reset")]
        failed_files = sorted(set(failed_files))
        if failed_files:
            zip_data = _zip_files(failed_files)
            if len(zip_data) <= max_bytes:
                filename = f"{device_name}_failed_logs.zip"
                logger.info("Zip %s: %d files, %d KB", filename, len(failed_files), len(zip_data) // 1024)
                return zip_data, filename

    # Still over limit or no failed tests identified — skip
    logger.warning("Zip for %s exceeds limit even with failed-only (%d KB), skipping attachment",
                   device_name, len(zip_data) // 1024)
    return None


def _build_html_body(summary, index_url):
    """Build a compact HTML email body with the run summary table."""
    timestamp = summary.get("timestamp", "")
    total_devices = summary.get("total_devices", 0)
    devices_passed = summary.get("devices_passed", 0)
    devices_failed = summary.get("devices_failed", 0)
    total_tests = summary.get("total_tests", 0)
    total_passed = summary.get("total_passed", 0)
    total_failed = summary.get("total_failed", 0)
    total_duration = summary.get("total_duration", 0)

    if devices_failed == 0:
        status_text = "ALL PASSED"
        status_color = "#3fb950"
        status_bg = "#0d2818"
    elif devices_passed > 0:
        status_text = "MIXED"
        status_color = "#d29922"
        status_bg = "#2b2000"
    else:
        status_text = "ALL FAILED"
        status_color = "#f85149"
        status_bg = "#2d1014"

    # Per-device rows
    device_rows = ""
    for t in summary.get("targets", []):
        name = t.get("target", "?")
        status = t.get("status", "?")
        passed = t.get("passed", 0)
        failed = t.get("failed", 0)
        total = t.get("total", 0)
        rate = round(passed / total * 100, 1) if total > 0 else 0
        dur = _fmt_duration(t.get("duration", 0))

        if status == "passed":
            s_badge = f'<span style="color:#3fb950;font-weight:600">PASS</span>'
        elif status == "failed":
            s_badge = f'<span style="color:#f85149;font-weight:600">FAIL</span>'
        else:
            s_badge = f'<span style="color:#d29922;font-weight:600">{status.upper()}</span>'

        device_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d">{name}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center">{s_badge}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center;color:#3fb950">{passed}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center;color:{'#f85149' if failed > 0 else '#484f58'}">{failed}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center">{total}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center">{rate}%</td>
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center">{dur}</td>
        </tr>"""

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:0 auto;color:#c9d1d9">
      <div style="text-align:center;padding:20px 0">
        <h2 style="margin:0 0 4px;font-size:1.3em;color:#ffffff">DM-NAX Nightly Test Run</h2>
        <div style="color:#8b949e;font-size:0.9em">{timestamp}</div>
        <div style="margin-top:10px">
          <span style="display:inline-block;padding:4px 18px;border-radius:16px;font-weight:600;background:{status_bg};color:{status_color};border:1px solid {status_color}">{status_text}</span>
        </div>
      </div>

      <div style="text-align:center;padding:10px 0;font-size:0.95em;color:#8b949e">
        {total_devices} devices &bull; {total_tests} tests &bull; {total_passed} passed &bull; {total_failed} failed &bull; {_fmt_duration(total_duration)}
      </div>

      <table style="width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:6px">
        <thead>
          <tr style="background:#21262d">
            <th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:0.8em">Device</th>
            <th style="padding:8px 12px;text-align:center;color:#8b949e;font-size:0.8em">Status</th>
            <th style="padding:8px 12px;text-align:center;color:#8b949e;font-size:0.8em">Passed</th>
            <th style="padding:8px 12px;text-align:center;color:#8b949e;font-size:0.8em">Failed</th>
            <th style="padding:8px 12px;text-align:center;color:#8b949e;font-size:0.8em">Total</th>
            <th style="padding:8px 12px;text-align:center;color:#8b949e;font-size:0.8em">Rate</th>
            <th style="padding:8px 12px;text-align:center;color:#8b949e;font-size:0.8em">Duration</th>
          </tr>
        </thead>
        <tbody>
          {device_rows}
        </tbody>
      </table>

      <div style="text-align:center;padding:20px 0">
        <a href="{index_url}" style="display:inline-block;padding:10px 28px;background:#238636;color:#fff;border-radius:6px;text-decoration:none;font-weight:600">View Full Report &rarr;</a>
      </div>

      <div style="text-align:center;color:#484f58;font-size:0.75em;padding:10px 0;border-top:1px solid #30363d">
        DM-NAX DSP Test Suite &bull; Crestron Electronics &bull; Automated nightly report
      </div>
    </div>
    """


def send_run_notification(summary, index_url, email_cfg):
    """Send the nightly run summary email with optional log attachments.

    Args:
        summary:   dict from run_summary.json (includes targets[].results_dir)
        index_url: full URL to the run index page (e.g. http://nj6v-docker-04/run/2026-05-02_01-00-00)
        email_cfg: dict with keys: smtp_host, smtp_port, from_address, recipients[],
                   attach_logs (bool), max_attachment_mb (float)
    """
    smtp_host = email_cfg.get("smtp_host", "smtp.crestron.com")
    smtp_port = email_cfg.get("smtp_port", 25)
    from_addr = email_cfg.get("from_address", "dmnax-nightly@crestron.com")
    recipients = email_cfg.get("recipients", [])

    if not recipients:
        logger.warning("No email recipients configured — skipping notification")
        return

    timestamp = summary.get("timestamp", "unknown")
    devices_failed = summary.get("devices_failed", 0)
    total_devices = summary.get("total_devices", 0)
    devices_passed = summary.get("devices_passed", 0)

    if devices_failed == 0:
        status = "ALL PASS"
    elif devices_passed > 0:
        status = "MIXED"
    else:
        status = "ALL FAIL"

    subject = (
        f"[DM-NAX Nightly] {timestamp} — {status} "
        f"({devices_passed}/{total_devices} devices passed)"
    )

    # Build email: outer "mixed" (body + attachments)
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    # Inner "alternative" for plain/HTML body
    body_part = MIMEMultipart("alternative")

    plain = (
        f"DM-NAX Nightly Test Run — {timestamp}\n"
        f"Status: {status}\n"
        f"Devices: {devices_passed}/{total_devices} passed\n"
        f"Tests: {summary.get('total_passed', 0)}/{summary.get('total_tests', 0)} passed\n"
        f"\nFull report: {index_url}\n"
    )
    body_part.attach(MIMEText(plain, "plain"))

    html_body = _build_html_body(summary, index_url)
    body_part.attach(MIMEText(html_body, "html"))

    msg.attach(body_part)

    # Attach per-device test log zips (if enabled)
    attach_logs = email_cfg.get("attach_logs", False)
    if attach_logs:
        max_mb = float(email_cfg.get("max_attachment_mb", 3))
        max_per_device = int(max_mb * 1_000_000 / max(total_devices, 1))
        # Cap per-device at 1MB regardless
        max_per_device = min(max_per_device, 1_000_000)

        total_attached = 0
        for target in summary.get("targets", []):
            results_dir = target.get("results_dir")
            device_name = target.get("target", "unknown")
            if not results_dir or not Path(results_dir).is_dir():
                continue

            result = _create_test_logs_zip(results_dir, device_name, max_bytes=max_per_device)
            if result is None:
                continue

            zip_data, filename = result
            total_attached += len(zip_data)
            if total_attached > max_mb * 1_000_000:
                logger.warning("Total attachment size exceeds %s MB, skipping remaining", max_mb)
                break

            part = MIMEBase("application", "zip")
            part.set_payload(zip_data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
            logger.info("Attached %s (%d KB)", filename, len(zip_data) // 1024)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.sendmail(from_addr, recipients, msg.as_string())
        logger.info("Notification email sent to %s", ", ".join(recipients))
    except Exception as exc:
        logger.error("Failed to send notification email: %s", exc)
