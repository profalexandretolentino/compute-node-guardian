from unittest.mock import patch
from fastapi.testclient import TestClient

from agent.main import app

client = TestClient(app)


def test_metrics_endpoint_returns_kernel_and_network_data():
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "kernel" in body
    assert "network" in body
    assert "memory" in body["kernel"]
    assert "interfaces" in body["network"]


def test_health_returns_200_when_healthy():
    fake_kernel = {"memory": {"used_percent": 40.0}, "cpu_load": {}, "kernel_dmesg": {}}
    fake_network = {"dns": {"target": "cloudflare.com", "status": "ok", "latency_ms": 12.5}}

    with patch("agent.main.collect_kernel_metrics", return_value=fake_kernel), \
         patch("agent.main.collect_network_metrics", return_value=fake_network):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_returns_503_when_memory_is_critical():
    """Valida a Decisão Arquitetural #2 (Opção B): degradação deve retornar HTTP 503."""
    fake_kernel = {"memory": {"used_percent": 95.5}, "cpu_load": {}, "kernel_dmesg": {}}
    fake_network = {"dns": {"target": "cloudflare.com", "status": "ok", "latency_ms": 10.0}}

    with patch("agent.main.collect_kernel_metrics", return_value=fake_kernel), \
         patch("agent.main.collect_network_metrics", return_value=fake_network):
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert len(body["reasons"]) == 1
