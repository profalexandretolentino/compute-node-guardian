from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from agent.collectors.gpu import collect_gpu_metrics, parse_nvidia_smi_csv

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_gpu_fallback_when_nvidia_smi_missing():
    """Garante resiliência em nós sem GPU (CI/CD, EC2 Free Tier)."""
    with patch("agent.collectors.gpu.subprocess.run", side_effect=FileNotFoundError):
        result = collect_gpu_metrics()

    assert result["available"] is False
    assert result["gpus"] == []


def test_parse_rtx2000_idle_and_load_fixtures():
    """Valida o parser real contra as capturas reais da NVIDIA RTX 2000 Ada."""
    idle_csv = (FIXTURES_DIR / "rtx2000_idle.csv").read_text(encoding="utf-8")
    load_csv = (FIXTURES_DIR / "rtx2000_load.csv").read_text(encoding="utf-8")

    idle_gpus = parse_nvidia_smi_csv(idle_csv)
    load_gpus = parse_nvidia_smi_csv(load_csv)

    assert len(idle_gpus) >= 1
    assert len(load_gpus) >= 1
    assert "RTX 2000" in idle_gpus[0]["name"]

    # Valida que sob carga houve aumento real de utilização ou consumo de energia
    max_load_util = max(g["utilization_percent"] for g in load_gpus)
    max_load_power = max(g["power_draw_w"] for g in load_gpus)
    assert max_load_util >= idle_gpus[0]["utilization_percent"]
    assert max_load_power >= idle_gpus[0]["power_draw_w"]


def test_collect_gpu_metrics_with_mocked_subprocess():
    """Testa collect_gpu_metrics() injetando fixture real sem depender de GPU local."""
    idle_csv = (FIXTURES_DIR / "rtx2000_idle.csv").read_text(encoding="utf-8")
    fake_proc = CompletedProcess(args=["nvidia-smi"], returncode=0, stdout=idle_csv, stderr="")

    with patch("agent.collectors.gpu.subprocess.run", return_value=fake_proc):
        result = collect_gpu_metrics()

    assert result["available"] is True
    assert result["count"] >= 1
    assert result["gpus"][0]["memory_total_mib"] > 0
