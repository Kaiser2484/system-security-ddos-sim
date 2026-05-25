#!/usr/bin/env python3
"""
scripts/switch_phase.py
─────────────────────────────────────────────────────────
Tiện ích chuyển đổi giữa các Phase của đồ án DDoS Simulation.

Thao tác:
  - Ghi NGINX_CONF vào file .env
  - Reload nginx_proxy container (không cần restart toàn bộ stack)

Usage:
  python scripts/switch_phase.py 1    # Phase 1/2 – No defense
  python scripts/switch_phase.py 3    # Phase 3   – Rate Limiting + Conn Limit
  python scripts/switch_phase.py      # Hiển thị phase hiện tại
"""

import io
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

PHASES = {
    "1": {"conf": "nginx.conf",           "label": "Phase 1/2 – No Defense   (baseline)"},
    "2": {"conf": "nginx.conf",           "label": "Phase 1/2 – No Defense   (baseline)"},
    "3": {"conf": "nginx_defended.conf",  "label": "Phase 3   – Defended      (rate limit + conn limit)"},
}

BOLD  = "\033[1m"
GREEN = "\033[92m"
CYAN  = "\033[96m"
RED   = "\033[91m"
YELLOW= "\033[93m"
RESET = "\033[0m"


def read_current_conf() -> str:
    if not ENV_FILE.exists():
        return "nginx.conf"
    text = ENV_FILE.read_text(encoding="utf-8")
    m = re.search(r"^NGINX_CONF\s*=\s*(\S+)", text, re.MULTILINE)
    return m.group(1) if m else "nginx.conf"


def write_conf(conf: str) -> None:
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    if re.search(r"^NGINX_CONF\s*=", text, re.MULTILINE):
        text = re.sub(r"^(NGINX_CONF\s*=\s*)\S+", f"\\g<1>{conf}", text, flags=re.MULTILINE)
    else:
        text += f"\nNGINX_CONF={conf}\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def reload_nginx() -> bool:
    """Restart nginx_proxy container to pick up new config."""
    print(f"  {CYAN}[*] Reloading nginx_proxy...{RESET}", flush=True)
    result = subprocess.run(
        ["docker-compose", "up", "-d", "--no-deps", "nginx_proxy"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"  {GREEN}[+] nginx_proxy reloaded successfully.{RESET}")
        return True
    else:
        print(f"  {RED}[-] Failed to reload nginx_proxy:{RESET}")
        print(result.stderr)
        return False


def show_status() -> None:
    current = read_current_conf()
    print()
    print(f"  {BOLD}Current Phase Config{RESET}")
    print(f"  {'─'*40}")
    for num, info in [("1/2", PHASES["1"]), ("3", PHASES["3"])]:
        active = "  <── ACTIVE" if info["conf"] == current else ""
        icon   = f"{GREEN}*{RESET}" if info["conf"] == current else " "
        print(f"  {icon} Phase {num}: {info['label']}{YELLOW}{active}{RESET}")
    print(f"  {'─'*40}")
    print(f"  Config file: {CYAN}{current}{RESET}")
    print()


def main() -> None:
    args = sys.argv[1:]

    if not args:
        show_status()
        print(f"  Usage: python scripts/switch_phase.py [1|2|3]")
        print()
        return

    phase = args[0].strip()
    if phase not in PHASES:
        print(f"  {RED}Unknown phase: '{phase}'. Choose 1, 2, or 3.{RESET}")
        sys.exit(1)

    target_conf  = PHASES[phase]["conf"]
    target_label = PHASES[phase]["label"]
    current_conf = read_current_conf()

    print()
    print(f"  {BOLD}DDoS Sim – Phase Switcher{RESET}")
    print(f"  {'─'*40}")
    print(f"  From : {YELLOW}{current_conf}{RESET}")
    print(f"  To   : {GREEN}{target_conf}{RESET}  ({target_label})")
    print()

    if current_conf == target_conf:
        print(f"  {YELLOW}Already using '{target_conf}'. No change needed.{RESET}")
        print()
        return

    write_conf(target_conf)
    print(f"  {GREEN}[+] .env updated: NGINX_CONF={target_conf}{RESET}")

    ok = reload_nginx()

    print()
    if ok:
        print(f"  {GREEN}{BOLD}Phase switched to: {target_label}{RESET}")
        if phase == "3":
            print(f"\n  {CYAN}Defense active:{RESET}")
            print(f"    Rate limit  : 20 req/s per IP (burst=40) → HTTP Flood blocked")
            print(f"    Conn limit  : 15 connections per IP     → Slowloris blocked")
            print(f"    Header timeout: 5s                      → Slow-header blocked")
            print(f"\n  Now re-run the attack to see it get blocked:")
            print(f"  {YELLOW}  python scripts/run_attack.py --mode http_flood --workers 200 --duration 30{RESET}")
        else:
            print(f"\n  {YELLOW}No defense active. Run Phase 2 attack scripts freely.{RESET}")
    print()


if __name__ == "__main__":
    main()
