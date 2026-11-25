import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List


def read_net_dev_drops() -> Dict[str, Dict[str, int]]:
    """
    Lê /proc/net/dev diretamente do kernel Linux.
    Por quê? Em infraestrutura de alta performance, 'rx_drop' e 'tx_drop'
    indicam buffers de placa de rede (NIC) saturados ou congestionamento.
    Retransmissões TCP derrubam a latência de inferência e treino distribuído.
    """
    interfaces: Dict[str, Dict[str, int]] = {}
    lines = Path("/proc/net/dev").read_text().splitlines()

    # As 2 primeiras linhas são cabeçalhos do kernel; os dados começam na linha 3
    for line in lines[2:]:
        if ":" not in line:
            continue
        iface, raw_stats = line.split(":", 1)
        iface = iface.strip()
        stats = raw_stats.split()

        # Layout padrão do /proc/net/dev:
        # Receive:  bytes(0) packets(1) errs(2) drop(3) ...
        # Transmit: bytes(8) packets(9) errs(10) drop(11) ...
        interfaces[iface] = {
            "rx_errors": int(stats[2]),
            "rx_dropped": int(stats[3]),
            "tx_errors": int(stats[10]),
            "tx_dropped": int(stats[11]),
        }

    return interfaces


def measure_dns_latency(hostname: str = "cloudflare.com") -> Dict[str, Any]:
    """
    Mede a latência de resolução DNS em milissegundos.
    Por quê? Em clusters Kubernetes, falhas ou lentidão no CoreDNS causam
    timeouts em cascata nos serviços antes mesmo de o tráfego sair do nó.
    """
    start = time.perf_counter()
    try:
        socket.getaddrinfo(hostname, 443)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "target": hostname,
            "status": "ok",
            "latency_ms": elapsed_ms,
        }
    except socket.gaierror as exc:
        return {
            "target": hostname,
            "status": "error",
            "latency_ms": None,
            "reason": str(exc),
        }


def check_listening_tcp_ports() -> Dict[str, Any]:
    """
    Audita portas TCP em estado LISTEN usando 'ss -tln' (substituto moderno do netstat).
    Por quê? Ajuda a validar hardening do host (nenhuma porta inesperada exposta)
    e confirmar se serviços críticos do nó estão de pé.
    """
    try:
        result = subprocess.run(
            ["ss", "-tlnH"],  # -t (TCP), -l (listening), -n (numérico), -H (sem cabeçalho)
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return {"accessible": False, "ports": []}

        ports: List[str] = []
        for line in result.stdout.splitlines():
            cols = line.split()
            if len(cols) >= 4:
                # Coluna 4 traz o endereço local:porta (ex: 127.0.0.1:8000 ou *:22)
                ports.append(cols[3])

        return {
            "accessible": True,
            "listening_count": len(ports),
            "endpoints": ports[:15],  # Limita a 15 para manter o payload leve
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"accessible": False, "reason": str(exc), "ports": []}


def collect_network_metrics() -> Dict[str, Any]:
    return {
        "interfaces": read_net_dev_drops(),
        "dns": measure_dns_latency(),
        "tcp_listening": check_listening_tcp_ports(),
    }
