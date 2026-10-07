FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS builder
ARG INSTALL_LLM=0
ARG BAKE_EMBEDDINGS=1
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.19
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY model.lock.json ./
COPY scripts/download_model.py ./scripts/download_model.py
RUN if [ "$INSTALL_LLM" = 1 ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential cmake && \
      CMAKE_ARGS='-DGGML_CUDA=OFF' uv sync --frozen --no-dev --extra llm; \
    else uv sync --frozen --no-dev; fi
RUN mkdir -p .cache/model && if [ "$BAKE_EMBEDDINGS" = 1 ]; then .venv/bin/python scripts/download_model.py; fi
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates && \
    rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/.cache/model /app/.cache/model
COPY src ./src
COPY data ./data
COPY config ./config
COPY model.lock.json llm.lock.json ./
COPY scripts ./scripts
COPY infra/aws/rds-ca.pem /app/infra/aws/rds-ca.pem
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/src PYTHONUNBUFFERED=1 ORT_DISABLE_TELEMETRY=1 FASTEMBED_CACHE_PATH=/tmp/refundguard-fastembed
USER app
EXPOSE 8000
ENTRYPOINT ["python", "scripts/container_entrypoint.py"]
CMD ["uvicorn", "refundguard.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
