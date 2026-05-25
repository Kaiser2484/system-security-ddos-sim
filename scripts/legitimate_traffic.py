#!/usr/bin/env python3
"""
scripts/legitimate_traffic.py
──────────────────────────────
Simulates legitimate users accessing the target web service.

Features:
  - Sends requests at a configurable rate (default: 5–10 req/s)
  - Color-coded terminal output: ✅ 2xx green, ⚠️  4xx yellow, ❌ 5xx/errors red
  - Rolling statistics: every 10 seconds prints avg/min/max/p95 latency
  - Graceful shutdown on Ctrl+C

Usage:
  python scripts/legitimate_traffic.py [--url URL] [--rate RATE] [--workers N]

Examples:
  python scripts/legitimate_traffic.py
  python scripts/legitimate_traffic.py --rate 10 --workers 3
  python scripts/legitimate_traffic.py --url http://localhost/api/data --rate 5
"""

import argparse
import statistics
import sys
import time
import threading
import random
from datetime import datetime
from collections import deque
from concurrent.futures import ThreadPoolExecutor

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("❌  Missing dependency: pip install requests")
    sys.exit(1)

# ── ANSI color codes ──────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
GRAY   = "\033[90m"
MAGENTA= "\033[95m"

# ── Shared state (thread-safe via lock) ──────────────────────────────────────
_lock          = threading.Lock()
_total_requests= 0
_total_errors  = 0
_latencies     = deque(maxlen=1000)   # Keep last 1000 samples for stats
_status_counts = {}
_start_time    = time.monotonic()

# ── Session factory ───────────────────────────────────────────────────────────
def create_session() -> requests.Session:
    """Create an HTTP session with retry logic and connection pooling."""
    session = requests.Session()
    retry_strategy = Retry(
        total=0,                  # No retries – we want to see failures
        status_forcelist=[],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "LegitUser/1.0 (DDoS-Sim Baseline Test)",
        "Accept": "application/json",
    })
    return session


# ── Color helpers ─────────────────────────────────────────────────────────────
def colorize_status(status: int) -> str:
    if 200 <= status < 300:
        return f"{GREEN}{BOLD}{status}{RESET}"
    elif 400 <= status < 500:
        return f"{YELLOW}{BOLD}{status}{RESET}"
    else:
        return f"{RED}{BOLD}{status}{RESET}"


def colorize_latency(ms: float) -> str:
    if ms < 200:
        return f"{GREEN}{ms:.1f} ms{RESET}"
    elif ms < 1000:
        return f"{YELLOW}{ms:.1f} ms{RESET}"
    else:
        return f"{RED}{ms:.1f} ms{RESET}"


# ── Single request worker ─────────────────────────────────────────────────────
def send_request(session: requests.Session, url: str, worker_id: int) -> None:
    global _total_requests, _total_errors

    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    try:
        t0 = time.monotonic()
        response = session.get(url, timeout=10)
        elapsed_ms = (time.monotonic() - t0) * 1000

        status     = response.status_code
        status_str = colorize_status(status)
        latency_str= colorize_latency(elapsed_ms)

        with _lock:
            _total_requests += 1
            _latencies.append(elapsed_ms)
            _status_counts[status] = _status_counts.get(status, 0) + 1

        # Per-request log line
        print(
            f"  {GRAY}[{ts}]{RESET} "
            f"{CYAN}W{worker_id:02d}{RESET} "
            f"GET {GRAY}{url}{RESET} → "
            f"HTTP {status_str}  "
            f"⏱  {latency_str}"
        )

    except requests.exceptions.ConnectionError:
        with _lock:
            _total_requests += 1
            _total_errors   += 1
            _status_counts["CONNECTION_ERROR"] = _status_counts.get("CONNECTION_ERROR", 0) + 1
        print(
            f"  {GRAY}[{ts}]{RESET} "
            f"{CYAN}W{worker_id:02d}{RESET} "
            f"GET {GRAY}{url}{RESET} → "
            f"{RED}{BOLD}CONNECTION REFUSED / RESET{RESET}"
        )

    except requests.exceptions.Timeout:
        with _lock:
            _total_requests += 1
            _total_errors   += 1
            _status_counts["TIMEOUT"] = _status_counts.get("TIMEOUT", 0) + 1
        print(
            f"  {GRAY}[{ts}]{RESET} "
            f"{CYAN}W{worker_id:02d}{RESET} "
            f"GET {GRAY}{url}{RESET} → "
            f"{RED}{BOLD}TIMEOUT{RESET}"
        )

    except Exception as exc:
        with _lock:
            _total_requests += 1
            _total_errors   += 1
        print(
            f"  {GRAY}[{ts}]{RESET} "
            f"{CYAN}W{worker_id:02d}{RESET} "
            f"GET {GRAY}{url}{RESET} → "
            f"{RED}{BOLD}ERROR: {exc}{RESET}"
        )


# ── Periodic stats printer ────────────────────────────────────────────────────
def print_stats(interval: int = 10) -> None:
    """Background thread: prints rolling statistics every `interval` seconds."""
    while True:
        time.sleep(interval)
        with _lock:
            total  = _total_requests
            errors = _total_errors
            lats   = list(_latencies)
            counts = dict(_status_counts)

        elapsed = time.monotonic() - _start_time
        rps     = total / elapsed if elapsed > 0 else 0

        if lats:
            avg_lat = statistics.mean(lats)
            min_lat = min(lats)
            max_lat = max(lats)
            p95_lat = statistics.quantiles(lats, n=20)[18] if len(lats) >= 20 else max_lat
        else:
            avg_lat = min_lat = max_lat = p95_lat = 0

        success = total - errors
        success_pct = (success / total * 100) if total > 0 else 0

        print()
        print(f"  {MAGENTA}{'─'*60}{RESET}")
        print(f"  {MAGENTA}{BOLD}📊  ROLLING STATISTICS  (last {interval}s window){RESET}")
        print(f"  {MAGENTA}{'─'*60}{RESET}")
        print(f"  Total Requests : {BOLD}{total:>8,}{RESET}  │  Rate: {BOLD}{rps:.1f} req/s{RESET}")
        print(f"  Errors         : {RED}{BOLD}{errors:>8,}{RESET}  │  Success: {GREEN}{BOLD}{success_pct:.1f}%{RESET}")
        print(f"  Latency        : "
              f"avg={CYAN}{avg_lat:.1f}ms{RESET}  "
              f"min={GREEN}{min_lat:.1f}ms{RESET}  "
              f"max={RED}{max_lat:.1f}ms{RESET}  "
              f"p95={YELLOW}{p95_lat:.1f}ms{RESET}")
        print(f"  Status Counts  : ", end="")
        for code, cnt in sorted(counts.items(), key=lambda x: str(x[0])):
            color = GREEN if isinstance(code, int) and 200 <= code < 300 else \
                    YELLOW if isinstance(code, int) and 400 <= code < 500 else RED
            print(f"{color}{code}={cnt}{RESET}  ", end="")
        print()
        print(f"  {MAGENTA}{'─'*60}{RESET}")
        print()


# ── Main loop ─────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Legitimate traffic simulator for DDoS baseline testing."
    )
    parser.add_argument(
        "--url", default="http://localhost/api/data",
        help="Target URL (default: http://localhost/api/data)"
    )
    parser.add_argument(
        "--rate", type=float, default=7.0,
        help="Target requests per second (default: 7.0)"
    )
    parser.add_argument(
        "--workers", type=int, default=2,
        help="Number of concurrent worker threads (default: 2)"
    )
    parser.add_argument(
        "--stats-interval", type=int, default=10,
        help="Statistics print interval in seconds (default: 10)"
    )
    args = parser.parse_args()

    interval = 1.0 / args.rate   # Seconds between requests per worker
    total_rps = args.rate

    # ── Banner ────────────────────────────────────────────────────────────────
    print()
    print(f"  {GREEN}{BOLD}╔══════════════════════════════════════════════════╗{RESET}")
    print(f"  {GREEN}{BOLD}║   DDoS Sim – Legitimate Traffic Simulator        ║{RESET}")
    print(f"  {GREEN}{BOLD}║   Phase 1: Baseline (No Defense)                 ║{RESET}")
    print(f"  {GREEN}{BOLD}╚══════════════════════════════════════════════════╝{RESET}")
    print()
    print(f"  Target  : {CYAN}{args.url}{RESET}")
    print(f"  Rate    : {CYAN}{total_rps:.1f} req/s{RESET}  ({args.workers} workers)")
    print(f"  Stats   : every {args.stats_interval}s")
    print()
    print(f"  {GRAY}Press Ctrl+C to stop.{RESET}")
    print()

    # Start stats thread
    stats_thread = threading.Thread(
        target=print_stats,
        args=(args.stats_interval,),
        daemon=True
    )
    stats_thread.start()

    # Create per-worker sessions (each has its own connection pool)
    sessions = [create_session() for _ in range(args.workers)]

    # ── Main send loop ────────────────────────────────────────────────────────
    worker_idx = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            while True:
                t_start = time.monotonic()

                # Submit request to next worker (round-robin)
                wid = (worker_idx % args.workers)
                executor.submit(send_request, sessions[wid], args.url, wid + 1)
                worker_idx += 1

                # Sleep to maintain target rate; add tiny jitter for realism
                jitter = random.uniform(-0.05, 0.05) * interval
                sleep_time = max(0, (1.0 / args.rate) - (time.monotonic() - t_start) + jitter)
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print()
        print(f"\n  {YELLOW}{BOLD}⚠  Interrupted by user. Final statistics:{RESET}")
        with _lock:
            total  = _total_requests
            errors = _total_errors
            lats   = list(_latencies)
        elapsed  = time.monotonic() - _start_time
        avg_rps  = total / elapsed if elapsed > 0 else 0
        avg_lat  = statistics.mean(lats) if lats else 0
        print(f"  Total: {total} requests in {elapsed:.1f}s  ({avg_rps:.1f} req/s avg)")
        print(f"  Errors: {errors}  |  Avg Latency: {avg_lat:.1f}ms")
        print(f"\n  {GREEN}Bye! 👋{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
