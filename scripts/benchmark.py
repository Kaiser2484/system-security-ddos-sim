#!/usr/bin/env python3
"""
scripts/benchmark.py
─────────────────────────────────────────────────────────────────────────────
Phase 4 – Automated Benchmark & Comparison Runner

Mô tả:
  Script này tự động hóa toàn bộ quy trình so sánh Phase 2 (không phòng thủ)
  và Phase 3 (có phòng thủ) theo các bước:

    1. Kiểm tra Docker & services đang chạy
    2. Thu thập baseline metrics (không tấn công)
    3. [Phase 2] Chuyển sang nginx.conf → chạy HTTP Flood → ghi metrics
    4. Chờ hệ thống phục hồi
    5. [Phase 3] Chuyển sang nginx_defended.conf → chạy cùng attack → ghi metrics
    6. Lưu kết quả vào reports/benchmark_results.json

Output:
  reports/benchmark_results.json  ← dữ liệu thô để generate_report.py sử dụng

Usage:
  python scripts/benchmark.py
  python scripts/benchmark.py --workers 200 --duration 45
  python scripts/benchmark.py --skip-phase2   # chỉ chạy Phase 3
"""

import argparse
import io
import json
import os
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    print("❌  pip install requests")
    sys.exit(1)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
RESULTS_FILE = REPORTS_DIR / "benchmark_results.json"
ENV_FILE    = ROOT / ".env"

# ── URLs ──────────────────────────────────────────────────────────────────────
PROMETHEUS_URL = "http://127.0.0.1:9090"
TARGET_URL     = "http://127.0.0.1/api/data"

# ── ANSI colors ───────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
RED    = "\033[91m"
ORANGE = "\033[33m"
GRAY   = "\033[90m"
PURPLE = "\033[95m"

# ── Prometheus queries ────────────────────────────────────────────────────────
PROM_QUERIES = {
    "rps_total":      "sum(rate(flask_http_request_total[15s]))",
    "rps_200":        "sum(rate(flask_http_request_total{status='200'}[15s]))",
    "rps_5xx":        "sum(rate(flask_http_request_total{status=~'5..'}[15s]))",
    "latency_p50":    "histogram_quantile(0.50, sum(rate(flask_http_request_duration_seconds_bucket{path='/api/data'}[15s])) by (le))",
    "latency_p95":    "histogram_quantile(0.95, sum(rate(flask_http_request_duration_seconds_bucket{path='/api/data'}[15s])) by (le))",
    "latency_p99":    "histogram_quantile(0.99, sum(rate(flask_http_request_duration_seconds_bucket{path='/api/data'}[15s])) by (le))",
    "nginx_active":   "nginx_connections_active",
    "nginx_waiting":  "nginx_connections_waiting",
    "nginx_rps":      "rate(nginx_http_requests_total[15s])",
    "blocked_rps":    "clamp_min(rate(nginx_http_requests_total[15s]) - sum(rate(flask_http_request_total[15s])), 0)",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Prometheus helper
# ══════════════════════════════════════════════════════════════════════════════

def prom_instant(query: str) -> float | None:
    """Query Prometheus instant value. Returns None on error."""
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        data = r.json()
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
        return 0.0
    except Exception:
        return None


def prom_range(query: str, start: float, end: float, step: int = 5) -> list[dict]:
    """Query Prometheus range. Returns list of {ts, value} dicts."""
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=10,
        )
        data = r.json()
        results = data.get("data", {}).get("result", [])
        if results:
            return [{"ts": float(v[0]), "value": float(v[1])} for v in results[0]["values"]]
        return []
    except Exception:
        return []


def collect_snapshot(label: str = "") -> dict:
    """Collect all Prometheus metrics at this instant."""
    snap = {"timestamp": time.time(), "label": label}
    for key, query in PROM_QUERIES.items():
        val = prom_instant(query)
        snap[key] = val if val is not None else 0.0
    return snap


# ══════════════════════════════════════════════════════════════════════════════
#  Phase switching
# ══════════════════════════════════════════════════════════════════════════════

def set_phase(phase: int) -> bool:
    """Switch Nginx config via switch_phase.py."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "switch_phase.py"), str(phase)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60
    )
    ok = result.returncode == 0
    if ok:
        time.sleep(5)  # Wait for nginx to come up healthy
    return ok


# ══════════════════════════════════════════════════════════════════════════════
#  Attack runner (as subprocess)
# ══════════════════════════════════════════════════════════════════════════════

def run_attack_subprocess(workers: int, duration: int) -> subprocess.Popen:
    """Launch run_attack.py as a non-blocking subprocess."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_attack.py"),
            "--mode", "http_flood",
            "--workers", str(workers),
            "--duration", str(duration),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(ROOT),
        env=env,
    )
    return proc


# ══════════════════════════════════════════════════════════════════════════════
#  Metrics collector thread
# ══════════════════════════════════════════════════════════════════════════════

class MetricsCollector(threading.Thread):
    """Background thread: samples Prometheus every `interval` seconds."""

    def __init__(self, label: str, interval: int = 5):
        super().__init__(daemon=True)
        self.label    = label
        self.interval = interval
        self.samples: list[dict] = []
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            snap = collect_snapshot(self.label)
            self.samples.append(snap)
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()
        self.join(timeout=10)

    def summary(self) -> dict:
        """Compute peak / average statistics from collected samples."""
        if not self.samples:
            return {}

        def _values(key):
            return [s[key] for s in self.samples if s.get(key, 0) > 0]

        def _peak(key):
            v = _values(key)
            return max(v) if v else 0.0

        def _avg(key):
            v = _values(key)
            return sum(v) / len(v) if v else 0.0

        return {
            "phase_label":        self.label,
            "sample_count":       len(self.samples),
            "peak_rps_total":     _peak("rps_total"),
            "avg_rps_total":      _avg("rps_total"),
            "peak_rps_200":       _peak("rps_200"),
            "avg_rps_200":        _avg("rps_200"),
            "peak_rps_5xx":       _peak("rps_5xx"),
            "avg_rps_5xx":        _avg("rps_5xx"),
            "peak_latency_p50":   _peak("latency_p50"),
            "avg_latency_p50":    _avg("latency_p50"),
            "peak_latency_p95":   _peak("latency_p95"),
            "avg_latency_p95":    _avg("latency_p95"),
            "peak_latency_p99":   _peak("latency_p99"),
            "avg_latency_p99":    _avg("latency_p99"),
            "peak_nginx_active":  _peak("nginx_active"),
            "avg_nginx_active":   _avg("nginx_active"),
            "peak_nginx_waiting": _peak("nginx_waiting"),
            "peak_blocked_rps":   _peak("blocked_rps"),
            "avg_blocked_rps":    _avg("blocked_rps"),
            "timeseries":         self.samples,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Benchmark steps
# ══════════════════════════════════════════════════════════════════════════════

def check_services() -> bool:
    """Verify that Prometheus and Nginx are reachable."""
    print(f"\n  {CYAN}[*] Checking services...{RESET}")
    try:
        r = requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=5)
        if r.status_code != 200:
            print(f"  {RED}❌  Prometheus not healthy: {r.status_code}{RESET}")
            return False
    except Exception as e:
        print(f"  {RED}❌  Cannot reach Prometheus at {PROMETHEUS_URL}: {e}{RESET}")
        print(f"  {YELLOW}    Hint: Run 'docker-compose up -d' first.{RESET}")
        return False

    try:
        r = requests.get(TARGET_URL, timeout=5)
    except Exception as e:
        print(f"  {RED}❌  Cannot reach target: {TARGET_URL}: {e}{RESET}")
        return False

    print(f"  {GREEN}✓  Prometheus OK  |  Target OK{RESET}")
    return True


def collect_baseline(duration: int = 20) -> dict:
    """Collect metrics while no attack is running (baseline)."""
    print(f"\n  {CYAN}[*] Collecting {duration}s baseline (no attack)...{RESET}")
    collector = MetricsCollector(label="baseline")
    collector.start()
    time.sleep(duration)
    collector.stop()
    summary = collector.summary()
    print(f"  {GREEN}✓  Baseline: avg_rps={summary.get('avg_rps_total', 0):.1f} req/s  "
          f"avg_p50={summary.get('avg_latency_p50', 0)*1000:.1f}ms{RESET}")
    return summary


def run_scenario(label: str, phase: int, workers: int, duration: int,
                 recovery_time: int = 20) -> dict:
    """
    Full scenario: switch phase → launch attack → collect metrics → wait recovery.
    Returns summary dict.
    """
    print(f"\n  {'─'*60}")
    print(f"  {BOLD}{YELLOW}▶ Scenario: {label}{RESET}")
    print(f"  {'─'*60}")

    # Switch phase
    print(f"  {CYAN}[1/4] Switching to Phase {phase}...{RESET}")
    if not set_phase(phase):
        print(f"  {RED}❌  Failed to switch phase. Aborting scenario.{RESET}")
        return {}

    phase_label = "Phase 3 (Defended)" if phase == 3 else "Phase 2 (No Defense)"
    print(f"  {GREEN}✓  Active: {phase_label}{RESET}")

    # Start metrics collector
    print(f"  {CYAN}[2/4] Starting metrics collector...{RESET}")
    collector = MetricsCollector(label=label)
    collector.start()

    # Launch attack
    print(f"  {CYAN}[3/4] Launching HTTP Flood ({workers} workers, {duration}s)...{RESET}")
    t_attack_start = time.time()
    proc = run_attack_subprocess(workers=workers, duration=duration)

    # Progress indicator during attack
    deadline = t_attack_start + duration + 5   # +5s for startup overhead
    while time.time() < deadline and proc.poll() is None:
        elapsed = int(time.time() - t_attack_start)
        snap = collector.samples[-1] if collector.samples else {}
        rps   = snap.get("rps_total", 0)
        p99   = snap.get("latency_p99", 0) * 1000
        blk   = snap.get("blocked_rps", 0)
        bar_len = min(int(rps / 10), 30)
        bar = "█" * bar_len
        print(
            f"\r  {ORANGE}[{elapsed:>3}s]{RESET}  "
            f"rps={RED}{rps:>7.1f}{RESET}  "
            f"p99={ORANGE}{p99:>7.1f}ms{RESET}  "
            f"blocked={PURPLE}{blk:>7.1f}{RESET}  "
            f"{GRAY}{bar}{RESET}",
            end="", flush=True
        )
        time.sleep(2)

    print()   # newline after progress bar
    proc.wait()
    t_attack_end = time.time()

    # Recovery wait
    print(f"  {CYAN}[4/4] Waiting {recovery_time}s for system recovery...{RESET}")
    time.sleep(recovery_time)

    # Stop collector
    collector.stop()
    summary = collector.summary()
    summary["attack_workers"]  = workers
    summary["attack_duration"] = duration
    summary["phase"]           = phase
    summary["t_start"]         = t_attack_start
    summary["t_end"]           = t_attack_end

    print(f"  {GREEN}✓  Done.  peak_rps={summary.get('peak_rps_total', 0):.1f}  "
          f"peak_p99={summary.get('peak_latency_p99', 0)*1000:.1f}ms  "
          f"peak_blocked={summary.get('peak_blocked_rps', 0):.1f}{RESET}")
    return summary


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Phase 4 – Automated DDoS Benchmark & Comparison"
    )
    parser.add_argument("--workers",     type=int, default=200,
                        help="HTTP Flood workers (default: 200)")
    parser.add_argument("--duration",    type=int, default=45,
                        help="Attack duration in seconds (default: 45)")
    parser.add_argument("--baseline",    type=int, default=20,
                        help="Baseline collection duration in seconds (default: 20)")
    parser.add_argument("--recovery",    type=int, default=20,
                        help="Recovery wait between scenarios (default: 20)")
    parser.add_argument("--skip-phase2", action="store_true",
                        help="Skip Phase 2 (undefended) scenario")
    parser.add_argument("--skip-phase3", action="store_true",
                        help="Skip Phase 3 (defended) scenario")
    args = parser.parse_args()

    # Banner
    print()
    print(f"  {CYAN}{BOLD}╔══════════════════════════════════════════════════════╗{RESET}")
    print(f"  {CYAN}{BOLD}║  📊 Phase 4: Automated Benchmark & Comparison        ║{RESET}")
    print(f"  {CYAN}{BOLD}║     DDoS Simulation – Educational Lab                ║{RESET}")
    print(f"  {CYAN}{BOLD}╚══════════════════════════════════════════════════════╝{RESET}")
    print(f"\n  Config:  workers={args.workers}  duration={args.duration}s  "
          f"baseline={args.baseline}s  recovery={args.recovery}s")
    print(f"  Output:  {REPORTS_DIR / 'benchmark_results.json'}")

    # Check services
    if not check_services():
        sys.exit(1)

    # Prepare output directory
    REPORTS_DIR.mkdir(exist_ok=True)

    results = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workers":   args.workers,
            "duration":  args.duration,
        },
        "baseline":  {},
        "phase2":    {},
        "phase3":    {},
    }

    # Baseline
    print(f"\n  {BOLD}━━━ STEP 1: Baseline (No Attack) ━━━{RESET}")
    results["baseline"] = collect_baseline(duration=args.baseline)

    # Phase 2 – No defense
    if not args.skip_phase2:
        print(f"\n  {BOLD}━━━ STEP 2: Phase 2 – No Defense (Attack) ━━━{RESET}")
        results["phase2"] = run_scenario(
            label="Phase 2 – No Defense",
            phase=1,
            workers=args.workers,
            duration=args.duration,
            recovery_time=args.recovery,
        )
    else:
        print(f"\n  {YELLOW}[SKIP] Phase 2 scenario skipped.{RESET}")

    # Phase 3 – Defended
    if not args.skip_phase3:
        print(f"\n  {BOLD}━━━ STEP 3: Phase 3 – Defended (Attack) ━━━{RESET}")
        results["phase3"] = run_scenario(
            label="Phase 3 – Defended",
            phase=3,
            workers=args.workers,
            duration=args.duration,
            recovery_time=args.recovery,
        )
    else:
        print(f"\n  {YELLOW}[SKIP] Phase 3 scenario skipped.{RESET}")

    # Restore to Phase 3 (defended) by default after benchmark
    print(f"\n  {CYAN}[*] Restoring to Phase 3 (defended) after benchmark...{RESET}")
    set_phase(3)

    # Save results
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n  {GREEN}{BOLD}✅  Benchmark complete!{RESET}")
    print(f"  Results saved → {RESULTS_FILE}")
    print(f"\n  Next step: generate the comparison report:")
    print(f"  {YELLOW}  python scripts/generate_report.py{RESET}\n")


if __name__ == "__main__":
    main()
