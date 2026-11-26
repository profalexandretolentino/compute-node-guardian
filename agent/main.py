import os
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from agent.collectors.gpu import collect_gpu_metrics
from agent.collectors.linux_kernel import collect_kernel_metrics
from agent.collectors.network import collect_network_metrics

app = FastAPI(
    title="compute-node-guardian",
    description="Agente leve de monitoramento e autorrecuperação para nós Linux",
    version="0.3.0",
)

# Threshold configurável via env var (12-Factor App)
MAX_MEM_PERCENT = float(os.getenv("MAX_MEM_PERCENT", "90.0"))

# Registro Prometheus isolado (evita colisão em testes e mantém exportação limpa)
GUARDIAN_REGISTRY = CollectorRegistry()

G_MEM_USED_PCT = Gauge(
    "node_guardian_memory_used_percent",
    "Percentual real de RAM utilizada (baseado em MemAvailable)",
    registry=GUARDIAN_REGISTRY,
)
G_MEM_AVAIL_MB = Gauge(
    "node_guardian_memory_available_mb",
    "Memória RAM disponível em MB",
    registry=GUARDIAN_REGISTRY,
)
G_CPU_LOAD_1M = Gauge(
    "node_guardian_cpu_load_1m",
    "Load average do kernel Linux nos últimos 1 minuto",
    registry=GUARDIAN_REGISTRY,
)
G_DNS_LATENCY_MS = Gauge(
    "node_guardian_dns_latency_ms",
    "Latência de resolução DNS em milissegundos",
    registry=GUARDIAN_REGISTRY,
)
G_NET_RX_DROPPED = Gauge(
    "node_guardian_net_rx_dropped_packets",
    "Pacotes descartados na recepção por interface (/proc/net/dev)",
    ["interface"],
    registry=GUARDIAN_REGISTRY,
)
G_GPU_AVAILABLE = Gauge(
    "node_guardian_gpu_available",
    "Indica se há GPU NVIDIA acessível no nó (1=sim, 0=não)",
    registry=GUARDIAN_REGISTRY,
)
G_GPU_TEMP_C = Gauge(
    "node_guardian_gpu_temperature_celsius",
    "Temperatura da GPU NVIDIA em graus Celsius",
    ["gpu"],
    registry=GUARDIAN_REGISTRY,
)
G_GPU_UTIL_PCT = Gauge(
    "node_guardian_gpu_utilization_percent",
    "Percentual de utilização da GPU NVIDIA",
    ["gpu"],
    registry=GUARDIAN_REGISTRY,
)
G_GPU_POWER_W = Gauge(
    "node_guardian_gpu_power_draw_watts",
    "Consumo de energia da GPU NVIDIA em Watts",
    ["gpu"],
    registry=GUARDIAN_REGISTRY,
)


@app.get("/status")
def get_status() -> Dict[str, Any]:
    """
    Telemetria completa em JSON para troubleshooting humano rápido via curl.
    Decisão Arquitetural #5 (Opção B): separado do /metrics padrão Prometheus.
    """
    return {
        "node": socket.gethostname(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "kernel": collect_kernel_metrics(),
        "network": collect_network_metrics(),
        "gpu": collect_gpu_metrics(),
    }


@app.get("/metrics")
def get_prometheus_metrics() -> Response:
    """
    Endpoint padrão Cloud Native consumido via scrape pelo Prometheus/Kubernetes.
    Atualiza os Gauges sob demanda a cada coleta.
    """
    kernel = collect_kernel_metrics()
    network = collect_network_metrics()
    gpu = collect_gpu_metrics()

    G_MEM_USED_PCT.set(kernel["memory"]["used_percent"])
    G_MEM_AVAIL_MB.set(kernel["memory"]["available_mb"])
    G_CPU_LOAD_1M.set(kernel["cpu_load"]["load_1m"])

    if network["dns"]["latency_ms"] is not None:
        G_DNS_LATENCY_MS.set(network["dns"]["latency_ms"])

    for iface, stats in network["interfaces"].items():
        G_NET_RX_DROPPED.labels(interface=iface).set(stats["rx_dropped"])

    G_GPU_AVAILABLE.set(1 if gpu["available"] else 0)
    for idx, g in enumerate(gpu.get("gpus", [])):
        label = f"{idx}:{g['name']}"
        G_GPU_TEMP_C.labels(gpu=label).set(g["temperature_c"])
        G_GPU_UTIL_PCT.labels(gpu=label).set(g["utilization_percent"])
        G_GPU_POWER_W.labels(gpu=label).set(g["power_draw_w"])

    return Response(content=generate_latest(GUARDIAN_REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health_check() -> JSONResponse:
    """
    Endpoint de saúde padrão Kubernetes (readinessProbe / livenessProbe).
    Retorna HTTP 503 quando o nó cruza limiares críticos.
    """
    kernel = collect_kernel_metrics()
    network = collect_network_metrics()

    reasons: List[str] = []

    mem_used = kernel["memory"]["used_percent"]
    if mem_used >= MAX_MEM_PERCENT:
        reasons.append(f"Uso de memória crítico: {mem_used}% (limite: {MAX_MEM_PERCENT}%)")

    if network["dns"]["status"] != "ok":
        reasons.append(f"Falha na resolução DNS para {network['dns']['target']}")

    if reasons:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "node": socket.gethostname(), "reasons": reasons},
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "healthy",
            "node": socket.gethostname(),
            "memory_used_percent": mem_used,
            "dns_latency_ms": network["dns"]["latency_ms"],
        },
    )
