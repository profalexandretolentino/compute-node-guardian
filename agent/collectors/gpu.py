import csv
import io
import subprocess
from typing import Any, Dict, List

# Mesmas 12 colunas padronizadas no playbook de captura NVIDIA
GPU_QUERY_FIELDS = (
    "timestamp,name,driver_version,pci.bus_id,pcie.link.gen.current,"
    "pstate,temperature.gpu,utilization.gpu,memory.used,memory.total,"
    "power.draw,power.limit"
)


def _to_float(raw: str) -> float:
    """Extrai o valor numérico de campos como '45 MiB', '22.50 W' ou '62 %'."""
    cleaned = raw.strip().split()[0]
    try:
        return float(cleaned)
    except (ValueError, IndexError):
        return 0.0


def parse_nvidia_smi_csv(csv_text: str) -> List[Dict[str, Any]]:
    """
    Parser puro para a saída CSV do nvidia-smi.
    Separar o parsing da chamada de sistema permite validar o código contra
    fixtures reais de hardware (RTX 2000 Ada) no CI/CD sem precisar de GPU.
    """
    # Remove possível BOM UTF-8 gerado pelo PowerShell (Out-File -Encoding utf8)
    clean_text = csv_text.lstrip("\ufeff").strip()
    if not clean_text:
        return []

    reader = csv.DictReader(io.StringIO(clean_text))
    gpus: List[Dict[str, Any]] = []

    for row in reader:
        # Normaliza nomes das colunas (nvidia-smi inclui espaços e unidades nos headers)
        norm = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}

        mem_used = _to_float(norm.get("memory.used [mib]", "0"))
        mem_total = _to_float(norm.get("memory.total [mib]", "0"))
        mem_pct = round((mem_used / mem_total) * 100, 2) if mem_total > 0 else 0.0

        gpus.append({
            "timestamp": norm.get("timestamp", ""),
            "name": norm.get("name", "unknown"),
            "driver_version": norm.get("driver_version", ""),
            "pci_bus_id": norm.get("pci.bus_id", ""),
            "pcie_link_gen": int(_to_float(norm.get("pcie.link.gen.current", "0"))),
            "pstate": norm.get("pstate", ""),
            "temperature_c": _to_float(norm.get("temperature.gpu", "0")),
            "utilization_percent": _to_float(norm.get("utilization.gpu [%]", "0")),
            "memory_used_mib": mem_used,
            "memory_total_mib": mem_total,
            "memory_used_percent": mem_pct,
            "power_draw_w": _to_float(norm.get("power.draw [w]", "0")),
            "power_limit_w": _to_float(norm.get("power.limit [w]", "0")),
        })

    return gpus


def collect_gpu_metrics() -> Dict[str, Any]:
    """
    Coleta telemetria de GPUs NVIDIA via nvidia-smi.
    Em nós CPU-only (ex: EC2 Free Tier ou CI), retorna fallback gracioso sem erro.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={GPU_QUERY_FIELDS}", "--format=csv"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return {
                "available": False,
                "reason": result.stderr.strip() or "nvidia-smi retornou erro",
                "gpus": [],
            }

        gpus = parse_nvidia_smi_csv(result.stdout)
        return {
            "available": len(gpus) > 0,
            "count": len(gpus),
            "gpus": gpus,
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "reason": f"GPU/nvidia-smi indisponível neste nó ({exc.__class__.__name__})",
            "gpus": [],
        }
