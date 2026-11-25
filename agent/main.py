import os
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from agent.collectors.linux_kernel import collect_kernel_metrics
from agent.collectors.network import collect_network_metrics

app = FastAPI(
    title="compute-node-guardian",
    description="Agente leve de monitoramento e autorrecuperação para nós Linux",
    version="0.1.0",
)

# Threshold configurável via env var (12-Factor App) — evita rebuild só para ajustar alerta
MAX_MEM_PERCENT = float(os.getenv("MAX_MEM_PERCENT", "90.0"))


@app.get("/metrics")
def get_metrics() -> Dict[str, Any]:
    """
    Expõe telemetria completa do nó (Kernel Linux + Rede).
    Consumido por sistemas de observabilidade ou troubleshooting rápido via curl.
    """
    return {
        "node": socket.gethostname(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "kernel": collect_kernel_metrics(),
        "network": collect_network_metrics(),
    }


@app.get("/health")
def health_check() -> JSONResponse:
    """
    Endpoint de saúde integrado ao padrão Kubernetes (readinessProbe / livenessProbe).
    Decisão Arquitetural #2 (Opção B): retorna HTTP 503 quando o nó cruza limiares críticos,
    permitindo que o orquestrador drene tráfego ou dispare autorrecuperação.
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
