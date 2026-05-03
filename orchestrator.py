#!/usr/bin/env python3
"""
DM-NAX Test Orchestrator — Parallel multi-device test runner.

Reads config/test_manifest.yaml and launches one pytest session per
enabled device target, in parallel.  Each device gets its own results
directory, console log, and HTML report.  A combined summary is written
for the dashboard.

Usage:
    python3 orchestrator.py                          # run all enabled targets
    python3 orchestrator.py --targets 4ZSA 8ZSA      # run specific targets
    python3 orchestrator.py --schedule nightly        # run a named schedule
    python3 orchestrator.py --targets 4ZSA --skip-upgrade
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import yaml
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SUITE_DIR / "config"
RESULTS_DIR = SUITE_DIR / "results"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")


def load_manifest():
    manifest_path = CONFIG_DIR / "test_manifest.yaml"
    with open(manifest_path) as f:
        return yaml.safe_load(f)


def load_devices():
    devices_path = CONFIG_DIR / "devices.yaml"
    with open(devices_path) as f:
        return yaml.safe_load(f)


def flatten_tests(test_list):
    """Flatten nested test group lists into a unique ordered list."""
    seen = set()
    flat = []
    for item in test_list:
        if isinstance(item, list):
            for t in item:
                if t not in seen:
                    seen.add(t)
                    flat.append(t)
        elif isinstance(item, str):
            if item not in seen:
                seen.add(item)
                flat.append(item)
    return flat


def purge_old_results(retention_days):
    """Delete result directories older than retention_days."""
    if not RESULTS_DIR.exists():
        return
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for entry in RESULTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        try:
            # Parse directory name format: YYYY-MM-DD_HH-MM-SS_DEVICE
            parts = entry.name.split("_")
            dir_date = datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y-%m-%d_%H-%M-%S")
            if dir_date < cutoff:
                shutil.rmtree(entry)
                removed += 1
        except (ValueError, IndexError):
            continue
    if removed:
        logger.info("Purged %d old result directories (>%d days)", removed, retention_days)


def wait_for_cresnext_ready(device_cfg, timeout_s=300, retry_delay_s=10):
    """Wait until CresNext web login is reachable and accepts authentication.

    This is primarily needed right after firmware upgrade, where SSH may be up
    before the CresNext web service is fully initialized.
    """
    from lib.cresnext_client import CresNextClient

    ip = device_cfg["ip"]
    username = device_cfg["username"]
    password = device_cfg["password"]

    retries = max(1, int(timeout_s // retry_delay_s))
    client = CresNextClient(ip=ip, username=username, password=password)
    try:
        logger.info(
            "Waiting for CresNext on %s (timeout=%ss, interval=%ss)",
            ip,
            timeout_s,
            retry_delay_s,
        )
        client.connect(retries=retries, retry_delay=retry_delay_s)
        logger.info("CresNext ready on %s", ip)
        return True
    except Exception as e:
        logger.error("CresNext not ready on %s after %ds: %s", ip, timeout_s, e)
        return False
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def run_device_tests(target_name, target_cfg, devices_cfg, timestamp, skip_upgrade):
    """Run tests for a single device target.  Executed in a child process."""
    device_name = target_cfg["device"]
    device = devices_cfg["devices"].get(device_name)
    if not device:
        return {
            "target": target_name,
            "status": "error",
            "message": f"Device '{device_name}' not found in devices.yaml",
        }

    # Per-device results directory
    run_dir = RESULTS_DIR / f"{timestamp}_{target_name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Build test file list
    all_tests = flatten_tests(target_cfg.get("tests", []))
    skip_tests = set(target_cfg.get("skip_tests", []))
    test_files = [t for t in all_tests if t not in skip_tests]

    if not test_files:
        return {
            "target": target_name,
            "status": "skipped",
            "message": "No test files to run",
        }

    # Separate firmware tests from DSP tests
    firmware_tests = [t for t in test_files if "upgrade" in t]
    dsp_tests = [t for t in test_files if "upgrade" not in t]

    # Build common pytest args
    base_args = [
        sys.executable, "-m", "pytest",
        f"--device={device_name}",
        f"--config={CONFIG_DIR / 'devices.yaml'}",
        f"--results-dir={run_dir}",
        "--json-report",
        "--tb=short",
        "-v",
    ]
    extra = target_cfg.get("extra_pytest_args", "")
    if extra:
        base_args.extend(extra.split())

    firmware_file = target_cfg.get("firmware_file", "")
    if firmware_file:
        base_args.append(f"--firmware-file={firmware_file}")

    results = {"target": target_name, "device": device_name}
    timeout_s = target_cfg.get("timeout_minutes",
                                60) * 60

    # Phase 1: Firmware upgrade
    upgrade_ok = True
    if firmware_tests and not skip_upgrade:
        logger.info("[%s] Phase 1: Firmware upgrade", target_name)
        upgrade_cmd = base_args + [
            f"--json-report-file={run_dir / 'upgrade_results.json'}",
        ] + firmware_tests

        with open(run_dir / "upgrade_console.log", "w") as log_f:
            proc = subprocess.run(
                upgrade_cmd, stdout=log_f, stderr=subprocess.STDOUT,
                timeout=timeout_s, cwd=str(SUITE_DIR),
            )
        upgrade_ok = proc.returncode == 0
        results["upgrade_exit"] = proc.returncode
        logger.info("[%s] Upgrade: %s (exit=%d)", target_name,
                    "PASS" if upgrade_ok else "FAIL", proc.returncode)
    else:
        results["upgrade_exit"] = -1  # skipped

    # Phase 2: DSP tests
    if dsp_tests:
        # After firmware upgrade, wait until CresNext is fully ready before
        # launching DSP tests to avoid fixture setup failures.
        if firmware_tests and not skip_upgrade:
            wait_timeout_s = target_cfg.get("post_upgrade_cresnext_timeout_s", 600)
            wait_retry_s = target_cfg.get("post_upgrade_cresnext_retry_s", 10)
            if not wait_for_cresnext_ready(
                device,
                timeout_s=wait_timeout_s,
                retry_delay_s=wait_retry_s,
            ):
                return {
                    "target": target_name,
                    "device": device_name,
                    "upgrade_exit": results.get("upgrade_exit", -1),
                    "test_exit": 1,
                    "status": "error",
                    "message": (
                        "CresNext web service not ready after firmware upgrade "
                        f"(timeout={wait_timeout_s}s)"
                    ),
                    "results_dir": str(run_dir),
                    "report_html": str(run_dir / "report.html"),
                }

        logger.info("[%s] Phase 2: DSP tests (%d files)", target_name, len(dsp_tests))
        dsp_cmd = base_args + [
            f"--json-report-file={run_dir / 'results.json'}",
        ] + dsp_tests

        with open(run_dir / "console.log", "w") as log_f:
            proc = subprocess.run(
                dsp_cmd, stdout=log_f, stderr=subprocess.STDOUT,
                timeout=timeout_s, cwd=str(SUITE_DIR),
            )
        results["test_exit"] = proc.returncode
        logger.info("[%s] Tests: exit=%d", target_name, proc.returncode)
    else:
        results["test_exit"] = 0

    # Save device info
    try:
        _save_device_info(device, run_dir)
    except Exception as e:
        logger.warning("[%s] Failed to save device info: %s", target_name, e)

    # Merge results and generate report
    try:
        _merge_and_report(run_dir, device)
    except Exception as e:
        logger.warning("[%s] Failed to generate report: %s", target_name, e)

    # Read summary for the combined report
    try:
        with open(run_dir / "all_results.json") as f:
            data = json.load(f)
        summary = data.get("summary", {})
        results["total"] = summary.get("total", 0)
        results["passed"] = summary.get("passed", 0)
        results["failed"] = summary.get("failed", 0)
        results["skipped"] = summary.get("skipped", 0)
        # pytest-json-report stores duration at root level, not inside summary
        results["duration"] = round(data.get("duration", 0) or summary.get("duration", 0), 1)
        results["status"] = "passed" if results["failed"] == 0 else "failed"
    except FileNotFoundError:
        results["status"] = "error"
        results["message"] = "No results JSON produced"

    results["results_dir"] = str(run_dir)
    results["report_html"] = str(run_dir / "report.html")
    return results


def _save_device_info(device_cfg, run_dir):
    """SSH to device and save version info."""
    from lib.device_ssh import DeviceSSH

    info = {
        "model": device_cfg["model"],
        "ip": device_cfg["ip"],
        "zones": device_cfg["zones"],
    }
    try:
        ssh = DeviceSSH(device_cfg["ip"], device_cfg["username"], device_cfg["password"])
        ssh.connect()
        info["version"] = ssh.get_version()
        ssh.disconnect()
    except Exception:
        info["version"] = "N/A"
    with open(run_dir / "device_info.json", "w") as f:
        json.dump(info, f, indent=2)


def _merge_and_report(run_dir, device_cfg):
    """Merge upgrade + DSP results and generate HTML report."""
    dsp_path = run_dir / "results.json"
    upgrade_path = run_dir / "upgrade_results.json"
    merged_path = run_dir / "all_results.json"

    if not dsp_path.exists() and not upgrade_path.exists():
        return

    merged = {}
    if dsp_path.exists():
        with open(dsp_path) as f:
            merged = json.load(f)

    if upgrade_path.exists():
        with open(upgrade_path) as f:
            upgrade = json.load(f)
        upgrade_tests = upgrade.get("tests", [])
        merged.setdefault("tests", [])
        merged["tests"] = upgrade_tests + merged["tests"]
        for key in ("passed", "failed", "skipped", "error"):
            merged.setdefault("summary", {})[key] = (
                merged.get("summary", {}).get(key, 0)
                + upgrade.get("summary", {}).get(key, 0)
            )
        merged["summary"]["total"] = len(merged["tests"])
        merged["summary"]["duration"] = (
            merged.get("summary", {}).get("duration", 0)
            + upgrade.get("summary", {}).get("duration", 0)
        )

    if not merged and dsp_path.exists():
        with open(dsp_path) as f:
            merged = json.load(f)

    with open(merged_path, "w") as f:
        json.dump(merged, f, indent=2)

    # Generate HTML report
    from lib.report_generator import generate_report

    device_info = {}
    info_path = run_dir / "device_info.json"
    if info_path.exists():
        with open(info_path) as f:
            device_info = json.load(f)
    generate_report(str(merged_path), str(run_dir / "report.html"), device_info=device_info)


def write_combined_summary(all_results, timestamp):
    """Write a combined summary JSON for the dashboard."""
    summary_dir = RESULTS_DIR / timestamp
    summary_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "timestamp": timestamp,
        "targets": all_results,
        "total_devices": len(all_results),
        "devices_passed": sum(1 for r in all_results if r.get("status") == "passed"),
        "devices_failed": sum(1 for r in all_results if r.get("status") == "failed"),
        "total_tests": sum(r.get("total", 0) for r in all_results),
        "total_passed": sum(r.get("passed", 0) for r in all_results),
        "total_failed": sum(r.get("failed", 0) for r in all_results),
        "total_duration": round(sum(r.get("duration", 0) for r in all_results), 1),
    }

    with open(summary_dir / "run_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Combined summary written to %s", summary_dir / "run_summary.json")
    return summary


def main():
    parser = argparse.ArgumentParser(description="DM-NAX Parallel Test Orchestrator")
    parser.add_argument("--targets", nargs="*", help="Specific target names to run")
    parser.add_argument("--schedule", help="Run a named schedule (nightly, weekly_full)")
    parser.add_argument("--skip-upgrade", action="store_true", help="Skip firmware upgrade phase")
    parser.add_argument("--max-parallel", type=int, default=0,
                        help="Max parallel device sessions (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    args = parser.parse_args()

    manifest = load_manifest()
    devices_cfg = load_devices()
    defaults = manifest.get("defaults", {})
    targets = manifest.get("test_targets", {})

    # Determine which targets to run
    if args.schedule:
        schedule = manifest.get("schedule", {}).get(args.schedule)
        if not schedule:
            logger.error("Schedule '%s' not found in manifest", args.schedule)
            sys.exit(1)
        selected = schedule["targets"]
    elif args.targets:
        selected = args.targets
    else:
        # All enabled targets
        selected = [name for name, cfg in targets.items() if cfg.get("enabled", True)]

    # Validate targets
    run_targets = {}
    for name in selected:
        if name not in targets:
            logger.warning("Target '%s' not in manifest, skipping", name)
            continue
        cfg = targets[name]
        if not cfg.get("enabled", True):
            logger.info("Target '%s' is disabled, skipping", name)
            continue
        # Merge defaults
        merged = {**defaults, **cfg}
        run_targets[name] = merged

    if not run_targets:
        logger.error("No targets to run")
        sys.exit(1)

    # Purge old results
    retention = defaults.get("results_retention_days", 30)
    purge_old_results(retention)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    skip_upgrade = args.skip_upgrade

    logger.info("=" * 60)
    logger.info("  DM-NAX Parallel Test Orchestrator")
    logger.info("  Timestamp: %s", timestamp)
    logger.info("  Targets:   %s", ", ".join(run_targets.keys()))
    logger.info("  Parallel:  %s", args.max_parallel or len(run_targets))
    logger.info("  Upgrade:   %s", "skip" if skip_upgrade else "enabled")
    logger.info("=" * 60)

    if args.dry_run:
        for name, cfg in run_targets.items():
            tests = flatten_tests(cfg.get("tests", []))
            skips = cfg.get("skip_tests", [])
            active = [t for t in tests if t not in skips]
            logger.info("[%s] Would run %d test files on %s (%s)",
                        name, len(active), cfg["device"],
                        devices_cfg["devices"][cfg["device"]]["ip"])
            for t in active:
                logger.info("  - %s", t)
        return

    # Run in parallel
    max_workers = args.max_parallel or len(run_targets)
    all_results = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for name, cfg in run_targets.items():
            fut = executor.submit(
                run_device_tests, name, cfg, devices_cfg, timestamp, skip_upgrade
            )
            futures[fut] = name

        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result = fut.result()
                all_results.append(result)
                status = result.get("status", "unknown")
                total = result.get("total", 0)
                passed = result.get("passed", 0)
                failed = result.get("failed", 0)
                logger.info("[%s] Complete: %s (%d/%d passed, %d failed)",
                            name, status.upper(), passed, total, failed)
            except Exception as e:
                logger.error("[%s] Exception: %s", name, e)
                all_results.append({
                    "target": name, "status": "error", "message": str(e)
                })

    # Write combined summary
    summary = write_combined_summary(all_results, timestamp)

    # Generate per-run index page (links to each device's report.html)
    try:
        from lib.report_generator import generate_run_index
        summary_dir = str(RESULTS_DIR / timestamp)
        index_path = generate_run_index(summary, summary_dir)
        logger.info("Run index: %s", index_path)
    except Exception as exc:
        logger.error("Failed to generate run index: %s", exc)

    # Send email notification
    try:
        from lib.email_notifier import send_run_notification
        email_cfg = manifest.get("email", {})
        if email_cfg.get("enabled", False):
            base_url = email_cfg.get("base_url", "http://nj6v-docker-04")
            index_url = f"{base_url}/run/{timestamp}"
            send_run_notification(summary, index_url, email_cfg)
    except Exception as exc:
        logger.error("Failed to send notification email: %s", exc)

    # Final report
    logger.info("")
    logger.info("=" * 60)
    logger.info("  COMBINED RESULTS")
    logger.info("  Devices: %d passed, %d failed (of %d)",
                summary["devices_passed"], summary["devices_failed"],
                summary["total_devices"])
    logger.info("  Tests:   %d passed, %d failed (of %d)",
                summary["total_passed"], summary["total_failed"],
                summary["total_tests"])
    logger.info("  Duration: %.1f seconds", summary["total_duration"])
    logger.info("=" * 60)

    for r in all_results:
        logger.info("  %-20s %s  %s", r["target"],
                     r.get("status", "?").upper(),
                     r.get("report_html", ""))

    # Exit 1 if any device failed
    if summary["devices_failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
