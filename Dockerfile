sleep 2
curl -s http://localhost:8000/health | python3 -m json.tool
curl -s http://localhost:8000/metrics | python3 -m json.tool# ==========================================
# Stage 1: Builder (instala dependências)
# ==========================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Cria um venv isolado para copiar tudo limpo para o estágio final
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ==========================================
# Stage 2: Runtime (imagem final com hardening)
# ==========================================
FROM python:3.12-slim AS runtime

# Instala apenas 'iproute2' (para o comando 'ss' do coletor de rede) e limpa o cache do apt
RUN apt-get update && \
    apt-get install -y --no-install-recommends iproute2 && \
    rm -rf /var/lib/apt/lists/*

# Hardening: cria usuário dedicado non-root (UID fixo 10001 facilita políticas no Kubernetes)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin guardian

WORKDIR /app

# Copia apenas o ambiente Python pronto do estágio builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copia o código do agente já atribuindo posse ao usuário non-root
COPY --chown=guardian:guardian agent/ ./agent/

# Troca para usuário sem privilégios antes de subir o processo
USER guardian

EXPOSE 8000

# Uvicorn escutando em 0.0.0.0 para aceitar tráfego do Docker/Kubernetes
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
