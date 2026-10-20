FROM python:3.12-slim
# uv from PyPI: ghcr.io pulls are denied on the team's network.
RUN pip install --no-cache-dir uv==0.8.23
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent ./agent
# Demo corpus baked in: an AgentBase Runtime is created from the image alone, with no file mounts.
# Build with the named context `corpus` (docker compose sets it; see AGENTS.md for a manual build).
COPY --from=corpus demo-documents.json /app/data/corpus.json
ENV CORPUS_PATH=/app/data/corpus.json
# AgentBase Runtime requires port 8080 (not configurable).
# Run as an unprivileged user: the app only reads its code and writes under /tmp.
RUN useradd --system --uid 10001 --create-home app
USER app
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"
CMD ["uvicorn", "agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
