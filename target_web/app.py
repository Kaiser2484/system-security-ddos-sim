"""
target_web/app.py
-----------------
A simple Flask web application that simulates a real backend service.

The /api/data endpoint performs a small CPU-bound computation 
(calculating the N-th Fibonacci number) so that CPU load is observable
when the server is under DDoS attack.

Prometheus metrics are exposed at /metrics via prometheus_flask_exporter.
"""

import math
import os
import time
import random
from flask import Flask, jsonify
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)

# ── Prometheus instrumentation ─────────────────────────────────────────────
# Automatically tracks: request count, latency histogram, in-flight requests
metrics = PrometheusMetrics(app)

# Custom static info metric (visible in Prometheus)
metrics.info("target_web_info", "Target Web Application Info", version="1.0.0")


# ── Helper: lightweight CPU work ──────────────────────────────────────────
def compute_fibonacci(n: int) -> int:
    """Iterative Fibonacci — O(n) time, avoids stack overflow."""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def is_prime(n: int) -> bool:
    """Simple primality test — adds a bit more CPU work."""
    if n < 2:
        return False
    for i in range(2, int(math.isqrt(n)) + 1):
        if n % i == 0:
            return False
    return True


# ── Routes ────────────────────────────────────────────────────────────────
@app.route("/api/data", methods=["GET"])
def api_data():
    """
    Main API endpoint.
    Performs a small computation to make CPU load visible under load testing.
    """
    # Random n in [30, 35] — noticeable but not blocking
    n = random.randint(30, 35)
    fib_value = compute_fibonacci(n)
    prime_check = is_prime(fib_value)

    response = {
        "status": "ok",
        "message": "Hello from target_web!",
        "computation": {
            "fibonacci_index": n,
            "fibonacci_value": fib_value,
            "is_prime": prime_check,
        },
        "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return jsonify(response), 200


@app.route("/health", methods=["GET"])
def health():
    """Health-check endpoint for Docker / load balancer."""
    return jsonify({"status": "healthy"}), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({"service": "target_web", "version": "1.0.0", "phase": "1 – Base (no defense)"}), 200


# ── Entry point (development only) ────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
