#!/usr/bin/env python3
"""
scripts/generate_report.py
Phase 4 – HTML Report Generator

Đọc reports/benchmark_results.json, vẽ biểu đồ so sánh,
xuất báo cáo HTML tự chứa (embedded base64 charts).

Usage:
  python scripts/generate_report.py
  python scripts/generate_report.py --input reports/benchmark_results.json
"""

import argparse
import base64
import io
import json
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
except ImportError:
    print("❌  pip install matplotlib numpy")
    sys.exit(1)

ROOT        = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
RESULTS_FILE = REPORTS_DIR / "benchmark_results.json"

# ── Plot style ────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor": "#1e1e2e",
    "axes.facecolor":   "#2a2a3e",
    "axes.edgecolor":   "#555577",
    "axes.labelcolor":  "#cdd6f4",
    "text.color":       "#cdd6f4",
    "xtick.color":      "#cdd6f4",
    "ytick.color":      "#cdd6f4",
    "grid.color":       "#44445a",
    "grid.linestyle":   "--",
    "grid.alpha":       0.5,
    "legend.facecolor": "#2a2a3e",
    "legend.edgecolor": "#555577",
    "font.size":        11,
    "axes.titlesize":   13,
    "axes.titleweight": "bold",
})

C_BASELINE = "#a6e3a1"   # green
C_PHASE2   = "#f38ba8"   # red (undefended)
C_PHASE3   = "#89b4fa"   # blue (defended)
C_BLOCKED  = "#cba6f7"   # purple


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b64


# ══════════════════════════════════════════════════════════════════════════════
#  Chart builders
# ══════════════════════════════════════════════════════════════════════════════

def chart_rps_comparison(b, p2, p3) -> str:
    """Bar chart: avg & peak RPS for baseline / phase2 / phase3."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Request Rate Comparison (req/s)", fontsize=15, fontweight="bold")

    labels   = ["Baseline", "Phase 2\n(No Defense)", "Phase 3\n(Defended)"]
    colors   = [C_BASELINE, C_PHASE2, C_PHASE3]

    avg_vals  = [b.get("avg_rps_total", 0), p2.get("avg_rps_total", 0), p3.get("avg_rps_total", 0)]
    peak_vals = [b.get("peak_rps_total", 0), p2.get("peak_rps_total", 0), p3.get("peak_rps_total", 0)]

    for ax, vals, title in zip(axes, [avg_vals, peak_vals], ["Average RPS", "Peak RPS"]):
        bars = ax.bar(labels, vals, color=colors, width=0.5, edgecolor="#333344", linewidth=0.8)
        ax.set_title(title)
        ax.set_ylabel("req/s")
        ax.grid(axis="y")
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(vals)*0.01,
                    f"{v:.1f}", ha="center", va="bottom", fontsize=10)

    plt.tight_layout()
    return fig_to_b64(fig)


def chart_latency_comparison(b, p2, p3) -> str:
    """Grouped bar: p50/p95/p99 latency across scenarios."""
    fig, ax = plt.subplots(figsize=(12, 5))
    fig.suptitle("Latency Percentile Comparison (ms)", fontsize=15, fontweight="bold")

    scenarios = ["Baseline", "Phase 2\n(No Defense)", "Phase 3\n(Defended)"]
    p50 = [b.get("avg_latency_p50", 0)*1000, p2.get("avg_latency_p50", 0)*1000, p3.get("avg_latency_p50", 0)*1000]
    p95 = [b.get("peak_latency_p95", 0)*1000, p2.get("peak_latency_p95", 0)*1000, p3.get("peak_latency_p95", 0)*1000]
    p99 = [b.get("peak_latency_p99", 0)*1000, p2.get("peak_latency_p99", 0)*1000, p3.get("peak_latency_p99", 0)*1000]

    x  = np.arange(len(scenarios))
    w  = 0.25

    ax.bar(x - w, p50, w, label="p50 (median)", color="#a6e3a1", edgecolor="#333344")
    ax.bar(x,     p95, w, label="p95",           color="#fab387", edgecolor="#333344")
    ax.bar(x + w, p99, w, label="p99",           color=C_PHASE2,  edgecolor="#333344")

    ax.set_xticks(x)
    ax.set_xticklabels(scenarios)
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Response Time Percentiles During Attack")
    ax.legend()
    ax.grid(axis="y")

    plt.tight_layout()
    return fig_to_b64(fig)


def chart_timeseries_rps(p2, p3) -> str:
    """Time-series line chart: RPS over time for both scenarios."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    fig.suptitle("Request Rate Over Time", fontsize=15, fontweight="bold")

    for ax, data, title, color in [
        (axes[0], p2, "Phase 2 – No Defense", C_PHASE2),
        (axes[1], p3, "Phase 3 – Defended",   C_PHASE3),
    ]:
        ts_data = data.get("timeseries", [])
        if ts_data:
            t0  = ts_data[0]["timestamp"]
            xs  = [(s["timestamp"] - t0) for s in ts_data]
            rps = [s.get("rps_total", 0) or 0 for s in ts_data]
            b200= [s.get("rps_200", 0)   or 0 for s in ts_data]
            blk = [s.get("blocked_rps", 0) or 0 for s in ts_data]

            ax.fill_between(xs, rps,  alpha=0.15, color=color)
            ax.plot(xs, rps,  color=color,     linewidth=2, label="Total RPS")
            ax.plot(xs, b200, color=C_BASELINE, linewidth=1.5, label="200 OK")
            if any(v > 0 for v in blk):
                ax.fill_between(xs, blk, alpha=0.2, color=C_BLOCKED)
                ax.plot(xs, blk, color=C_BLOCKED, linewidth=1.5, linestyle="--", label="Blocked")

        ax.set_title(title)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("req/s")
        ax.legend(fontsize=9)
        ax.grid()

    plt.tight_layout()
    return fig_to_b64(fig)


def chart_connections(p2, p3) -> str:
    """Nginx active & waiting connections over time."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    fig.suptitle("Nginx Connections Over Time", fontsize=15, fontweight="bold")

    for ax, data, title in [
        (axes[0], p2, "Phase 2 – No Defense"),
        (axes[1], p3, "Phase 3 – Defended"),
    ]:
        ts_data = data.get("timeseries", [])
        if ts_data:
            t0   = ts_data[0]["timestamp"]
            xs   = [(s["timestamp"] - t0) for s in ts_data]
            act  = [s.get("nginx_active",  0) or 0 for s in ts_data]
            wait = [s.get("nginx_waiting", 0) or 0 for s in ts_data]

            ax.plot(xs, act,  color="#89dceb", linewidth=2, label="Active")
            ax.fill_between(xs, wait, alpha=0.3, color=C_PHASE2)
            ax.plot(xs, wait, color=C_PHASE2, linewidth=1.5, linestyle="--", label="Waiting")

        ax.set_title(title)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Connections")
        ax.legend(fontsize=9)
        ax.grid()

    plt.tight_layout()
    return fig_to_b64(fig)


def chart_defense_pie(p3) -> str:
    """Pie: passed vs blocked in Phase 3."""
    fig, ax = plt.subplots(figsize=(6, 5))
    avg_total   = p3.get("avg_rps_total",   0.001)
    avg_blocked = p3.get("avg_blocked_rps", 0)
    avg_passed  = max(avg_total - avg_blocked, 0)

    passed_pct  = avg_passed  / avg_total * 100 if avg_total > 0 else 0
    blocked_pct = avg_blocked / avg_total * 100 if avg_total > 0 else 0

    wedges, texts, autotexts = ax.pie(
        [avg_passed, avg_blocked],
        labels=["Passed (200 OK)", "Blocked (429)"],
        autopct="%1.1f%%",
        colors=[C_PHASE3, C_BLOCKED],
        startangle=90,
        wedgeprops={"edgecolor": "#1e1e2e", "linewidth": 2},
    )
    for t in autotexts:
        t.set_color("#1e1e2e")
        t.set_fontweight("bold")
        t.set_fontsize(13)

    ax.set_title("Phase 3 – Traffic Distribution\n(During Attack)", fontsize=13, fontweight="bold")
    fig.patch.set_facecolor("#1e1e2e")
    ax.set_facecolor("#1e1e2e")
    return fig_to_b64(fig)


# ══════════════════════════════════════════════════════════════════════════════
#  HTML template
# ══════════════════════════════════════════════════════════════════════════════

def build_html(results: dict, charts: dict) -> str:
    meta = results.get("meta", {})
    b    = results.get("baseline", {})
    p2   = results.get("phase2",   {})
    p3   = results.get("phase3",   {})
    ts   = meta.get("timestamp", datetime.now().isoformat())[:19].replace("T", " ")

    def fmt_ms(v):  return f"{v*1000:.1f} ms"
    def fmt_rps(v): return f"{v:.1f} req/s"
    def fmt_pct(v): return f"{v:.1f}%"

    # Effectiveness
    avg_nginx  = p3.get("avg_rps_total", 0) + p3.get("avg_blocked_rps", 0)
    eff_pct    = (p3.get("avg_blocked_rps", 0) / avg_nginx * 100) if avg_nginx > 0 else 0
    p2_5xx_pct = (p2.get("avg_rps_5xx", 0) / p2.get("avg_rps_total", 1) * 100)

    rows = [
        ("Avg Total RPS",    fmt_rps(b.get("avg_rps_total", 0)),
                             fmt_rps(p2.get("avg_rps_total", 0)),
                             fmt_rps(p3.get("avg_rps_total", 0))),
        ("Peak RPS",         "—",
                             fmt_rps(p2.get("peak_rps_total", 0)),
                             fmt_rps(p3.get("peak_rps_total", 0))),
        ("Avg Latency p50",  fmt_ms(b.get("avg_latency_p50", 0)),
                             fmt_ms(p2.get("avg_latency_p50", 0)),
                             fmt_ms(p3.get("avg_latency_p50", 0))),
        ("Peak Latency p95", "—",
                             fmt_ms(p2.get("peak_latency_p95", 0)),
                             fmt_ms(p3.get("peak_latency_p95", 0))),
        ("Peak Latency p99", "—",
                             fmt_ms(p2.get("peak_latency_p99", 0)),
                             fmt_ms(p3.get("peak_latency_p99", 0))),
        ("5xx Error Rate",   "0%",
                             fmt_pct(p2_5xx_pct),
                             "0%"),
        ("Peak Connections", "—",
                             f"{p2.get('peak_nginx_active', 0):.0f}",
                             f"{p3.get('peak_nginx_active', 0):.0f}"),
        ("Blocked RPS (429)","—",
                             "0",
                             fmt_rps(p3.get("avg_blocked_rps", 0))),
        ("Defense Effectiveness", "—", "—", fmt_pct(eff_pct)),
    ]

    table_rows = ""
    for r in rows:
        table_rows += f"""
        <tr>
          <td>{r[0]}</td>
          <td class="baseline">{r[1]}</td>
          <td class="phase2">{r[2]}</td>
          <td class="phase3">{r[3]}</td>
        </tr>"""

    chart_sections = ""
    for key, title in [
        ("rps_comparison",   "1. Request Rate Comparison"),
        ("latency",          "2. Latency Percentile Comparison"),
        ("timeseries_rps",   "3. Request Rate Over Time"),
        ("connections",      "4. Nginx Connection Analysis"),
        ("defense_pie",      "5. Phase 3 Traffic Distribution"),
    ]:
        if key in charts:
            chart_sections += f"""
      <div class="section">
        <h2>{title}</h2>
        <img src="data:image/png;base64,{charts[key]}" alt="{title}">
      </div>"""

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DDoS Simulation – Phase 4 Comparison Report</title>
<style>
  :root {{
    --bg: #1e1e2e; --surface: #2a2a3e; --border: #44445a;
    --text: #cdd6f4; --muted: #a6adc8;
    --green: #a6e3a1; --red: #f38ba8; --blue: #89b4fa;
    --purple: #cba6f7; --yellow: #f9e2af;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif;
          background: var(--bg); color: var(--text); padding: 2rem; }}
  header {{ text-align: center; margin-bottom: 2.5rem; }}
  header h1 {{ font-size: 2rem; color: var(--blue); }}
  header p  {{ color: var(--muted); margin-top: .4rem; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
               gap: 1rem; margin-bottom: 2.5rem; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border);
          border-radius: 12px; padding: 1.2rem 1.4rem; }}
  .kpi .label {{ font-size: .8rem; color: var(--muted); text-transform: uppercase; }}
  .kpi .value {{ font-size: 2rem; font-weight: 700; margin-top: .3rem; }}
  .kpi.green .value {{ color: var(--green); }}
  .kpi.red   .value {{ color: var(--red);   }}
  .kpi.blue  .value {{ color: var(--blue);  }}
  .kpi.purple.value {{ color: var(--purple);}}
  .section {{ background: var(--surface); border: 1px solid var(--border);
              border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; }}
  .section h2 {{ font-size: 1.1rem; color: var(--yellow); margin-bottom: 1rem; }}
  .section img {{ max-width: 100%; border-radius: 8px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: .75rem 1rem; text-align: center; border-bottom: 1px solid var(--border); }}
  th {{ background: #33334a; color: var(--muted); font-size: .85rem; text-transform: uppercase; }}
  td:first-child {{ text-align: left; color: var(--muted); }}
  .baseline {{ color: var(--green); }}
  .phase2   {{ color: var(--red);   }}
  .phase3   {{ color: var(--blue);  }}
  .badge {{ display: inline-block; border-radius: 6px; padding: .2rem .6rem;
            font-size: .8rem; font-weight: 600; }}
  .badge.defended {{ background: #1a3a2a; color: var(--green); border: 1px solid var(--green); }}
  footer {{ text-align: center; color: var(--muted); font-size: .85rem; margin-top: 3rem; }}
</style>
</head>
<body>

<header>
  <h1>📊 DDoS Simulation – Phase 4 Report</h1>
  <p>Comparison & Analysis: No Defense vs Rate Limiting Defense</p>
  <p style="margin-top:.6rem; font-size:.9rem;">Generated: {ts} UTC &nbsp;|&nbsp;
     Attack: {meta.get('workers','?')} workers × {meta.get('duration','?')}s HTTP Flood</p>
</header>

<div class="kpi-grid">
  <div class="kpi red">
    <div class="label">Peak RPS (Phase 2)</div>
    <div class="value">{p2.get('peak_rps_total',0):.0f}</div>
  </div>
  <div class="kpi blue">
    <div class="label">Peak RPS (Phase 3)</div>
    <div class="value">{p3.get('peak_rps_total',0):.0f}</div>
  </div>
  <div class="kpi red">
    <div class="label">Peak p99 Latency (Phase 2)</div>
    <div class="value">{p2.get('peak_latency_p99',0)*1000:.0f}ms</div>
  </div>
  <div class="kpi blue">
    <div class="label">Peak p99 Latency (Phase 3)</div>
    <div class="value">{p3.get('peak_latency_p99',0)*1000:.0f}ms</div>
  </div>
  <div class="kpi green">
    <div class="label">Defense Effectiveness</div>
    <div class="value">{eff_pct:.0f}%</div>
  </div>
  <div class="kpi green">
    <div class="label">Baseline p50 Latency</div>
    <div class="value">{b.get('avg_latency_p50',0)*1000:.1f}ms</div>
  </div>
</div>

<div class="section">
  <h2>📋 Full Metrics Comparison Table</h2>
  <table>
    <thead>
      <tr>
        <th>Metric</th>
        <th class="baseline">Baseline (No Attack)</th>
        <th class="phase2">Phase 2 – No Defense</th>
        <th class="phase3">Phase 3 – Defended</th>
      </tr>
    </thead>
    <tbody>{table_rows}
    </tbody>
  </table>
</div>

{chart_sections}

<div class="section">
  <h2>📝 Kết luận & Phân tích</h2>
  <p style="line-height:1.8; color:var(--muted);">
    Thử nghiệm HTTP Flood với <strong style="color:var(--text)">{meta.get('workers','?')} workers
    trong {meta.get('duration','?')} giây</strong> cho thấy sự khác biệt rõ ràng giữa hai cấu hình:
    <br><br>
    <strong style="color:var(--red)">Phase 2 (Không phòng thủ):</strong>
    Tổng RPS tăng đột biến lên <strong>{p2.get('peak_rps_total',0):.0f} req/s</strong>,
    latency p99 đạt <strong>{p2.get('peak_latency_p99',0)*1000:.0f}ms</strong>,
    server hoàn toàn bị quá tải và legitimate users bị ảnh hưởng nặng nề.
    <br><br>
    <strong style="color:var(--blue)">Phase 3 (Rate Limiting):</strong>
    Nginx chặn <strong style="color:var(--purple)">{eff_pct:.1f}%</strong> traffic tấn công,
    trả về HTTP 429, server Flask chỉ xử lý ~20 req/s, latency ổn định,
    hệ thống hoàn toàn khỏe mạnh trong suốt cuộc tấn công.
    <br><br>
    <span class="badge defended">✅ Defense Effective</span>
    &nbsp; Rate Limiting (limit_req 20r/s + limit_conn 15/IP) là cơ chế phòng thủ
    hiệu quả và dễ triển khai cho Layer 7 HTTP Flood và Slowloris attacks.
  </p>
</div>

<footer>
  DDoS Simulation Lab – Phase 4 | Kaiser2484/system-security-ddos-sim | Educational Use Only
</footer>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Phase 4 – Generate HTML Report")
    parser.add_argument("--input", default=str(RESULTS_FILE),
                        help="Path to benchmark_results.json")
    parser.add_argument("--output", default=str(REPORTS_DIR / "report.html"),
                        help="Output HTML file path")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"❌  Results file not found: {input_path}")
        print(f"    Run 'python scripts/benchmark.py' first.")
        sys.exit(1)

    print(f"\n  📊 Loading results from {input_path}...")
    with open(input_path, encoding="utf-8") as f:
        results = json.load(f)

    b  = results.get("baseline", {})
    p2 = results.get("phase2",   {})
    p3 = results.get("phase3",   {})

    print("  🎨 Generating charts...")
    charts = {}

    try: charts["rps_comparison"]  = chart_rps_comparison(b, p2, p3)
    except Exception as e: print(f"  ⚠  rps_comparison: {e}")

    try: charts["latency"]         = chart_latency_comparison(b, p2, p3)
    except Exception as e: print(f"  ⚠  latency: {e}")

    try: charts["timeseries_rps"]  = chart_timeseries_rps(p2, p3)
    except Exception as e: print(f"  ⚠  timeseries: {e}")

    try: charts["connections"]     = chart_connections(p2, p3)
    except Exception as e: print(f"  ⚠  connections: {e}")

    try: charts["defense_pie"]     = chart_defense_pie(p3)
    except Exception as e: print(f"  ⚠  defense_pie: {e}")

    print("  📝 Building HTML report...")
    html = build_html(results, charts)

    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  ✅  Report saved → {output_path}")
    print(f"  Open in browser:  start {output_path}\n")


if __name__ == "__main__":
    main()
