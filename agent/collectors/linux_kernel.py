import subprocess
from pathlib import Path
from typing import Any, Dict


def read_meminfo() -> Dict[str, Any]:
    """
    Lê /proc/meminfo diretamente do kernel Linux.
    Usamos 'MemAvailable' (e não 'MemFree') porque o Linux aproveita RAM livre
    como Page Cache de disco.
    """
    mem_data: Dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            key = parts[0].strip()
            mem_data[key] = int(parts[1].strip().split()[0])

    total_kb = mem_data.get("MemTotal", 0)
    available_kb = mem_data.get("MemAvailable", 0)
    used_kb = max(total_kb - available_kb, 0)
    used_percent = round((used_kb / total_kb) * 100, 2) if total_kb > 0 else 0.0

    return {
        "total_mb": round(total_kb / 1024, 2),
        "available_mb": round(available_kb / 1024, 2),
        "used_percent": used_percent,
    }


def read_loadavg() -> Dict[str, float]:
    """
    Lê /proc/loadavg (fila de processos em CPU/IO em 1, 5 e 15 min).
    """
    raw = Path("/proc/loadavg").read_text().strip().split()
    return {
        "load_1m": float(raw[0]),
        "load_5m": float(raw[1]),
        "load_15m": float(raw[2]),
    }


def check_dmesg_errors() -> Dict[str, Any]:
    """
    Inspeciona o ring buffer do kernel (dmesg) atrás de OOM Killer e erros de hardware/PCIe.
    Usa timeout curto e fallback gracioso para funcionar em containers non-root.
    """
    keywords = ("oom-killer", "out of memory", "pcie bus error", "i/o error")
    try:
        result = subprocess.run(
            ["dmesg", "--level=err,crit,alert,emerg", "-T"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return {
                "accessible": False,
                "reason": "Permissão restrita ao ring buffer do kernel (esperado em non-root)",
                "critical_events": 0,
            }

        matches = [
            line for line in result.stdout.splitlines()
            if any(kw in line.lower() for kw in keywords)
        ]
        return {
            "accessible": True,
            "critical_events": len(matches),
            "last_events": matches[-3:],
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "accessible": False,
            "reason": str(exc),
            "critical_events": 0,
        }


def collect_kernel_metrics() -> Dict[str, Any]:
    return {
        "memory": read_meminfo(),
        "cpu_load": read_loadavg(),
        "kernel_dmesg": check_dmesg_errors(),
    }
