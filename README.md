# DDoS Simulation Project – Hệ thống Mô phỏng Tấn công DDoS & Phòng thủ

Đồ án môn Bảo mật Hệ thống. Mô phỏng môi trường thực tế để nghiên cứu tấn công DDoS và các cơ chế phòng thủ.

---

## 📁 Cấu trúc dự án

```
system-security-ddos-sim/
├── docker-compose.yml          # Khởi động toàn bộ hệ thống
│
├── target_web/                 # Service 1: Backend bị tấn công
│   ├── Dockerfile
│   ├── app.py                  # Flask API với /api/data
│   └── requirements.txt
│
├── nginx/                      # Service 2: Reverse Proxy
│   └── nginx.conf
│
├── prometheus/                 # Service 3: Thu thập metrics
│   └── prometheus.yml
│
├── grafana/                    # Service 4: Trực quan hóa
│   └── provisioning/
│       ├── datasources/
│       │   └── prometheus.yml
│       └── dashboards/
│           ├── dashboard.yml
│           └── ddos_dashboard.json
│
└── scripts/
    ├── legitimate_traffic.py   # Script giả lập user hợp lệ
    └── run_attack.py           # [Phase 2] Script tấn công DDoS
```

---

## 🚀 Giai đoạn 1: Khởi động hệ thống

### Yêu cầu

- Docker Desktop (Windows/Mac) hoặc Docker Engine (Linux)
- Docker Compose v2+
- Python 3.8+ (để chạy script traffic)
- `requests` library: `pip install requests`

### Bước 1: Khởi động toàn bộ hệ thống

```bash
# Di chuyển vào thư mục dự án
cd system-security-ddos-sim

# Build image và khởi động tất cả services (chạy nền)
docker-compose up -d --build

# Theo dõi log (tùy chọn)
docker-compose logs -f
```

### Bước 2: Kiểm tra trạng thái services

```bash
# Xem tất cả containers
docker-compose ps

# Kết quả mong đợi:
# NAME             STATUS          PORTS
# target_web       running (healthy)   5000/tcp
# nginx_proxy      running (healthy)   0.0.0.0:80->80/tcp
# nginx_exporter   running             9113/tcp
# prometheus       running (healthy)   0.0.0.0:9090->9090/tcp
# grafana          running (healthy)   0.0.0.0:3000->3000/tcp
```

### Bước 3: Kiểm tra API hoạt động

```bash
# Test qua Nginx proxy (đường chính)
curl http://localhost/api/data

# Kết quả mong đợi:
# {
#   "status": "ok",
#   "message": "Hello from target_web!",
#   "computation": { "fibonacci_index": 32, "fibonacci_value": 2178309, "is_prime": false },
#   "server_time": "2025-01-01T10:00:00Z"
# }
```

### Bước 4: Truy cập giao diện web

| Service    | URL                          | Thông tin đăng nhập |
|------------|------------------------------|---------------------|
| Grafana    | http://localhost:3000        | admin / admin       |
| Prometheus | http://localhost:9090        | *(không cần)*       |
| API trực tiếp | http://localhost/api/data | *(public)*          |

> **Grafana:** Sau khi đăng nhập, vào **Dashboards → DDoS Sim → Phase 1: Base Infrastructure** để xem dashboard đã được cấu hình sẵn.

---

## 📊 Bước 5: Chạy script Legitimate Traffic

Mở một terminal mới và chạy:

```bash
# Chạy với tốc độ mặc định (7 req/s)
python scripts/legitimate_traffic.py

# Tùy chỉnh tốc độ và số workers
python scripts/legitimate_traffic.py --rate 10 --workers 3

# Xem đầy đủ options
python scripts/legitimate_traffic.py --help
```

### Output mẫu

```
  ╔══════════════════════════════════════════════════╗
  ║   DDoS Sim – Legitimate Traffic Simulator        ║
  ║   Phase 1: Baseline (No Defense)                 ║
  ╚══════════════════════════════════════════════════╝

  Target  : http://localhost/api/data
  Rate    : 7.0 req/s  (2 workers)

  [10:23:45.123] W01 GET http://localhost/api/data → HTTP 200  ⏱  45.2 ms
  [10:23:45.267] W02 GET http://localhost/api/data → HTTP 200  ⏱  38.7 ms
  ...

  ────────────────────────────────────────────────────────────
  📊  ROLLING STATISTICS  (last 10s window)
  ────────────────────────────────────────────────────────────
  Total Requests :       70  │  Rate: 7.0 req/s
  Errors         :        0  │  Success: 100.0%
  Latency        : avg=42.1ms  min=31.5ms  max=89.3ms  p95=67.2ms
  Status Counts  : 200=70
  ────────────────────────────────────────────────────────────
```

---

## 🛑 Dừng hệ thống

```bash
# Dừng tất cả containers (giữ data volumes)
docker-compose down

# Dừng VÀ xóa toàn bộ data (reset hoàn toàn)
docker-compose down -v
```

---

## 🗺️ Kiến trúc hệ thống – Giai đoạn 1

```
                    ┌─────────────────────────────────────────────────┐
                    │              Docker Network: ddos_net            │
                    │                                                  │
  Client/Script     │  ┌─────────────┐     ┌──────────────────────┐  │
  ──────────────────┼─►│ nginx_proxy │────►│     target_web       │  │
    port 80         │  │  :80        │     │  Flask + Gunicorn    │  │
                    │  │  (no limit) │     │  /api/data           │  │
                    │  └─────────────┘     │  /metrics            │  │
                    │        │             └──────────┬───────────┘  │
                    │  ┌─────▼──────┐                │              │
                    │  │nginx_export│     ┌───────────▼───────────┐  │
                    │  │    :9113   │     │       prometheus       │  │
                    │  └─────┬──────┘     │          :9090         │  │
                    │        └────────────►                        │  │
                    │                     └───────────┬───────────┘  │
                    │                                 │              │
                    │                     ┌───────────▼───────────┐  │
Grafana UI ◄────────┼─────────────────────│        grafana         │  │
port 3000           │                     │          :3000         │  │
                    │                     └───────────────────────┘  │
                    └─────────────────────────────────────────────────┘
```

---

## 📋 Metrics được theo dõi

| Metric                    | Nguồn          | Mô tả                        |
|---------------------------|----------------|------------------------------|
| `flask_http_request_total`| target_web     | Tổng requests theo status    |
| `flask_http_request_duration_seconds` | target_web | Latency histogram  |
| `nginx_connections_active`| nginx_exporter | Kết nối đang hoạt động       |
| `nginx_http_requests_total`| nginx_exporter| Tổng requests qua Nginx      |

---

## 🔄 Roadmap các giai đoạn

| Giai đoạn | Mô tả                                      | Trạng thái    |
|-----------|--------------------------------------------|---------------|
| Phase 1   | Base Infrastructure                        | ✅ Hoàn thành |
| Phase 2   | DDoS Attack Simulation                     | ✅ Hoàn thành |
| Phase 3   | Defense Mechanisms (Rate Limit + Conn Limit)| ✅ Hoàn thành |
| Phase 4   | Comparison & Analysis (Benchmark + Report) | ✅ Hoàn thành |

---

## 🛡️ Giai đoạn 3: Cơ chế Phòng thủ

### Tổng quan các cơ chế được triển khai

| Cơ chế | Directive Nginx | Mục tiêu tấn công | Hiệu quả |
|--------|----------------|-------------------|----------|
| **Rate Limiting** | `limit_req` – 20 req/s/IP, burst=40 | HTTP Flood | Trả 429 ngay khi vượt ngưỡng |
| **Connection Limiting** | `limit_conn` – 15 conn/IP | Slowloris | Ngắt kết nối dư thừa |
| **Header Timeout** | `client_header_timeout 5s` | Slow Headers | Đóng socket nếu header không gửi xong trong 5s |
| **Body Limit** | `client_max_body_size 1m` | POST Flood | Từ chối body quá lớn |

### Cách chuyển đổi Phase

```bash
# ── Chuyển sang Phase 3 (bật defense) ──────────────────────────────────────
python scripts/switch_phase.py 3

# ── Quay về Phase 1/2 (tắt defense, baseline) ───────────────────────────────
python scripts/switch_phase.py 1

# ── Xem phase hiện tại ───────────────────────────────────────────────────────
python scripts/switch_phase.py
```

> Hoặc thủ công: sửa `NGINX_CONF` trong file `.env` rồi chạy `docker-compose up -d --no-deps nginx_proxy`

### Kịch bản kiểm thử so sánh

**Bước 1** – Chạy legitimate traffic (terminal 1):
```bash
python scripts/legitimate_traffic.py --rate 7 --workers 2
```

**Bước 2** – Bật Phase 3 defense:
```bash
python scripts/switch_phase.py 3
```

**Bước 3** – Tấn công trong khi defense đang hoạt động (terminal 2):
```bash
$env:PYTHONIOENCODING="utf-8"
python scripts/run_attack.py --mode http_flood --workers 150 --duration 30
```

**Bước 4** – Tắt defense, tấn công lại để so sánh:
```bash
python scripts/switch_phase.py 1
python scripts/run_attack.py --mode http_flood --workers 150 --duration 30
```

### Kết quả đã xác minh (150 workers, 20 giây)

| | Phase 2 (No Defense) | Phase 3 (Defended) |
|---|---|---|
| Tổng requests gửi | 14,913 | 23,558 |
| HTTP 200 (server xử lý) | 14,913 (100%) | **1,103 (4.7%)** |
| HTTP 429 (bị chặn) | 0 (0%) | **22,455 (95.3%)** ✅ |
| Avg Latency | 90ms | 350ms (do queue burst) |
| Server errors (5xx) | 0 | **0** ✅ (server ổn định) |

> **Kết luận**: Với Rate Limiting bật, 95.3% traffic tấn công bị chặn ngay tại Nginx, server Flask chỉ nhận ~20 req/s thay vì 450+ req/s → **server hoàn toàn khỏe mạnh**.

### Những gì thấy trên Grafana (Phase 3)

Mở **http://localhost:3000** → Dashboard: **DDoS Sim – Phase 1, 2 & 3: Attack & Defense**

Cuộn xuống row **"🛡️ Phase 3: Defense Effectiveness"**:

- 🟣 **Rate-Limited (429/s)**: chuyển màu **tím** → defense đang hoạt động
- 🟢 **Defense Effectiveness %**: tăng lên **~95%** khi bị tấn công
- 📊 **Pass vs Block Timeline**: đường xanh (200) phẳng, đường tím (429) tăng vọt

### File cấu hình

| File | Mô tả |
|------|-------|
| `nginx/nginx.conf` | Phase 1/2 – Không có defense (baseline) |
| `nginx/nginx_defended.conf` | Phase 3 – Rate limit + Conn limit + Timeout |
| `.env` | Biến `NGINX_CONF` điều khiển config nào được dùng |
| `scripts/switch_phase.py` | Tiện ích chuyển đổi phase nhanh |


---

## 🔴 Giai đoạn 2: Tấn công DDoS

### Tổng quan

`scripts/run_attack.py` triển khai 2 kiểu tấn công:

| Mode          | Nguyên lý                                            | Quan sát trên Grafana                          |
|---------------|------------------------------------------------------|------------------------------------------------|
| `http_flood`  | Hàng trăm threads gửi GET request liên tục không ngừng | RPS tăng vọt → latency bùng nổ → 5xx errors   |
| `slowloris`   | Mở nhiều TCP socket, gửi header HTTP dở dang để "treo" connection | Active Connections tăng → Waiting connections bùng nổ → legit requests bị block |

### Thiết lập 2 terminal

**Terminal 1** – Legitimate Traffic (giả lập người dùng hợp lệ, đã chạy):
```bash
python scripts/legitimate_traffic.py --rate 7 --workers 2
```

**Terminal 2** – Tấn công DDoS (chạy song song):

```bash
# ── Tấn công 1: HTTP Flood nhẹ (50 workers, 30 giây) ──────────────────────
python scripts/run_attack.py --mode http_flood --workers 50 --duration 30

# ── Tấn công 2: HTTP Flood mạnh (200 workers, 60 giây) ────────────────────
python scripts/run_attack.py --mode http_flood --workers 200 --duration 60

# ── Tấn công 3: Slowloris (150 kết nối treo, 60 giây) ────────────────────
python scripts/run_attack.py --mode slowloris --connections 150 --duration 60

# Xem tất cả options:
python scripts/run_attack.py --help
```

### Những gì bạn sẽ thấy trên Grafana

Mở **http://localhost:3000** → Dashboard: **DDoS Sim – Phase 1 & 2: Attack Observation**

#### Khi bị HTTP Flood:
- 🔴 **Request Rate** nhảy từ ~7 req/s lên **hàng trăm req/s**
- 🔴 **Avg Response Time** tăng từ ~50ms lên **hàng giây**
- 🔴 **Error Rate** xuất hiện lỗi 500/503/504
- 🔴 **Success Rate** giảm từ 100% xuống dưới 50%
- 🔴 **Latency p99** bùng nổ (gauge chuyển đỏ)

#### Khi bị Slowloris:
- 🔴 **Nginx Active Connections** tăng vọt
- 🔴 **Nginx Waiting Connections** tăng liên tục (connections bị "treo")
- 🔴 Legitimate users bắt đầu nhận lỗi **502 Bad Gateway**

#### Sau khi tấn công dừng:
- Hệ thống dần hồi phục (không có defense → có thể mất 10-30s)
- Grafana hiển thị rõ đường phân ranh giới "trước / trong / sau" tấn công

### Output mẫu của script tấn công

```
  ╔══════════════════════════════════════════════════════╗
  ║  💀 DDoS Sim – Phase 2: ATTACK SIMULATOR             ║
  ║     FOR EDUCATIONAL/LAB USE ONLY                     ║
  ╚══════════════════════════════════════════════════════╝

  Mode     : HTTP_FLOOD
  Target   : http://localhost/api/data
  Scale    : 200 workers
  Duration : 60s

  🔥 HTTP FLOOD STARTING
  ──────────────────────────────────────────────────────────────
  [16:30:01] ⚡ ATTACK [HTTP Flood] workers=200 sent=12,847 rps=1284 err%=23.5% lat_avg=890ms lat_max=5100ms
             status: 200=9833  503=2814  TIMEOUT=200
  [16:30:03] ⚡ ATTACK [HTTP Flood] workers=200 sent=15,203 rps=1267 err%=28.1% ...
```

---

## 📊 Giai đoạn 4: So sánh & Phân tích

### Tổng quan

Phase 4 tự động hóa toàn bộ quy trình benchmarking và tạo báo cáo HTML trực quan:

| Script | Chức năng |
|--------|----------|
| `scripts/benchmark.py` | Chạy attack ở Phase 2 & 3, query Prometheus, lưu JSON |
| `scripts/generate_report.py` | Đọc JSON, vẽ biểu đồ, xuất `reports/report.html` |

### Cài đặt dependencies (một lần)

```bash
pip install -r requirements.txt
```

### Quy trình chạy Phase 4

**Bước 1** – Đảm bảo Docker stack đang chạy:
```bash
docker-compose up -d
```

**Bước 2** – Chạy benchmark tự động (chuyển phase, tấn công, ghi metrics):
```bash
# Mặc định: 200 workers × 45 giây
python scripts/benchmark.py

# Tùy chỉnh:
python scripts/benchmark.py --workers 150 --duration 60 --baseline 20
```

Script sẽ tự động:
1. Thu thập baseline 20s (không tấn công)
2. Chuyển sang Phase 2 (no defense) → HTTP Flood → ghi metrics
3. Đợi phục hồi
4. Chuyển sang Phase 3 (defended) → cùng attack → ghi metrics
5. Lưu `reports/benchmark_results.json`

**Bước 3** – Tạo báo cáo HTML:
```bash
python scripts/generate_report.py
# Output: reports/report.html

# Mở báo cáo:
start reports\report.html        # Windows
```

### Nội dung báo cáo HTML

- 🔢 **KPI Cards**: Peak RPS, p99 Latency, Defense Effectiveness %
- 📋 **Bảng so sánh** đầy đủ 9 metrics (Baseline / Phase 2 / Phase 3)
- 📈 **5 biểu đồ**:
  - Request Rate Comparison (bar)
  - Latency Percentile Comparison (grouped bar)
  - RPS Over Time (time-series)
  - Nginx Connections Over Time
  - Phase 3 Traffic Distribution (pie: passed vs blocked)
- 📝 **Kết luận tự động** dựa trên dữ liệu thực

### Kết quả mẫu

| Metric | Phase 2 (No Defense) | Phase 3 (Defended) |
|--------|---------------------|--------------------|
| Peak RPS (tổng) | ~450 req/s | ~450 req/s |
| Peak RPS đến Flask | ~450 req/s | **~20 req/s** ✅ |
| Peak p99 Latency | >1000ms | <50ms ✅ |
| 5xx Errors | Có | **0** ✅ |
| Blocked (429) | 0 | **~95%** ✅ |

### Files Phase 4

| File | Mô tả |
|------|-------|
| `scripts/benchmark.py` | Benchmark orchestrator |
| `scripts/generate_report.py` | HTML report generator |
| `requirements.txt` | Host dependencies (matplotlib, numpy) |
| `reports/benchmark_results.json` | Raw metrics data (auto-generated) |
| `reports/report.html` | Final comparison report (auto-generated) |