"""
Email notification for DM-NAX nightly test runs.

Sends an HTML summary email after each orchestrator run with a link
to the per-run index page on the dashboard.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


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
        dur = round(t.get("duration", 0), 1)

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
          <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center">{dur}s</td>
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
        {total_devices} devices &bull; {total_tests} tests &bull; {total_passed} passed &bull; {total_failed} failed &bull; {total_duration}s
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
    """Send the nightly run summary email.

    Args:
        summary:   dict from run_summary.json
        index_url: full URL to the run index page (e.g. http://nj6v-docker-04/run/2026-05-02_01-00-00)
        email_cfg: dict with keys: smtp_host, smtp_port, from_address, recipients[]
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    # Plain text fallback
    plain = (
        f"DM-NAX Nightly Test Run — {timestamp}\n"
        f"Status: {status}\n"
        f"Devices: {devices_passed}/{total_devices} passed\n"
        f"Tests: {summary.get('total_passed', 0)}/{summary.get('total_tests', 0)} passed\n"
        f"\nFull report: {index_url}\n"
    )
    msg.attach(MIMEText(plain, "plain"))

    # HTML body
    html_body = _build_html_body(summary, index_url)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.sendmail(from_addr, recipients, msg.as_string())
        logger.info("Notification email sent to %s", ", ".join(recipients))
    except Exception as exc:
        logger.error("Failed to send notification email: %s", exc)
