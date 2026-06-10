# DDoS Simulation & Defense – Đồ án Bảo mật Hệ thống

Môi trường lab Docker mô phỏng tấn công DDoS và cơ chế phòng thủ theo 4 giai đoạn.

---

## 🏗️ Kiến trúc

```
Client → nginx_proxy:80 → target_web:5000 (Flask)
                ↓
        nginx_exporter:9113 → prometheus:9090 → grafana:3000
```

**5 containers:** `target_web` · `nginx_proxy` · `nginx_exporter` · `prometheus` · `grafana`

---

## ⚡ Khởi động nhanh

**Yêu cầu:** Docker Desktop, Python 3.8+

```bash
# 1. Khởi động toàn bộ hệ thống
docker-compose up -d --build

# 2. Kiểm tra
docker-compose ps
curl http://localhost/api/data

# 3. Cài Python dependencies (cho scripts)
pip install -r requirements.txt
```

| URL | Mô tả | Login |
|-----|-------|-------|
| <http://localhost> | API target | — |
| <http://localhost:3000> | Grafana dashboard | admin / admin |
| <http://localhost:9090> | Prometheus | — |

---

## 📋 Cấu trúc thư mục

```
├── docker-compose.yml
├── .env                          # NGINX_CONF=nginx_defended.conf
├── requirements.txt              # matplotlib, numpy, requests
├── target_web/                   # Flask app + Dockerfile
├── nginx/
│   ├── nginx.conf                # Phase 1/2: không có defense
│   └── nginx_defended.conf       # Phase 3: rate limit + conn limit
├── prometheus/prometheus.yml
├── grafana/provisioning/
└── scripts/
    ├── legitimate_traffic.py     # Giả lập user hợp lệ
    ├── run_attack.py             # Tấn công DDoS (HTTP Flood / Slowloris)
    ├── switch_phase.py           # Chuyển đổi phase
    ├── benchmark.py              # Phase 4: benchmark tự động
    └── generate_report.py        # Phase 4: tạo báo cáo HTML
```

---

## 🔄 Các giai đoạn

| Phase | Nội dung | Trạng thái |
|-------|----------|-----------|
| 1 | Base Infrastructure (Docker stack + Grafana) | ✅ |
| 2 | DDoS Attack Simulation (HTTP Flood + Slowloris) | ✅ |
| 3 | Defense Mechanisms (Rate Limiting + Connection Limit) | ✅ |
| 4 | Comparison & Analysis (Benchmark + HTML Report) | ✅ |

---

## 🔴 Phase 2 – Tấn công DDoS

```bash
# Windows: set encoding trước
$env:PYTHONIOENCODING="utf-8"

# HTTP Flood (làm quá tải server)
python scripts/run_attack.py --mode http_flood --workers 150 --duration 30

# Slowloris (chiếm hết connections)
python scripts/run_attack.py --mode slowloris --connections 150 --duration 60
```

| Kiểu tấn công | Cơ chế | Dấu hiệu trên Grafana |
|---------------|--------|----------------------|
| HTTP Flood | Hàng trăm threads gửi GET liên tục | RPS tăng vọt, latency bùng nổ, 5xx errors |
| Slowloris | Giữ socket với headers dở dang | Active/Waiting connections tăng, legit users bị block |

---

## 🛡️ Phase 3 – Cơ chế Phòng thủ

**Cơ chế triển khai trong `nginx/nginx_defended.conf`:**

| Directive | Giá trị | Chống |
|-----------|---------|-------|
| `limit_req_zone` | 20 req/s/IP, burst=40 | HTTP Flood |
| `limit_conn_zone` | 15 conn/IP | Slowloris |
| `client_header_timeout` | 5s | Slow Headers |
| `client_max_body_size` | 1m | POST Flood |

**Chuyển đổi phase:**

```bash
python scripts/switch_phase.py 3   # bật defense
python scripts/switch_phase.py 1   # tắt defense (baseline)
python scripts/switch_phase.py     # xem phase hiện tại
```

**Kết quả đo được (150 workers):**

| | Phase 2 (No Defense) | Phase 3 (Defended) |
|--|--|--|
| Peak RPS đến Flask | ~450 req/s | ~20 req/s ✅ |
| 5xx Errors | Có | 0 ✅ |
| Bị chặn (429) | 0% | ~95% ✅ |

---

## 📊 Phase 4 – So sánh & Báo cáo

Tự động benchmark cả 2 phases và xuất báo cáo HTML với biểu đồ so sánh.

```bash
# Bước 1: Chạy benchmark (~4 phút)
python scripts/benchmark.py --workers 150 --duration 35
# → Lưu: reports/benchmark_results.json

# Bước 2: Tạo báo cáo HTML
python scripts/generate_report.py
# → Lưu: reports/report.html

# Bước 3: Mở báo cáo
start reports\report.html
```

**Báo cáo gồm:** KPI cards · Bảng so sánh 9 metrics · 5 biểu đồ (bar, time-series, pie)

---

## 🛑 Dừng hệ thống

```bash
docker-compose down      # dừng, giữ data
docker-compose down -v   # dừng + xóa data
```
