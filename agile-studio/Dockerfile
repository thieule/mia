FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-mcp.txt ./
RUN pip install --no-cache-dir -r requirements-mcp.txt

COPY agile_hub ./agile_hub
COPY mcp_server ./mcp_server

ENV PYTHONPATH=/app
ENV AGILE_LISTEN_HOST=0.0.0.0
ENV AGILE_LISTEN_PORT=9120

EXPOSE 9120

# --reload: pick up code changes when agile_hub is bind-mounted (docker compose dev).
CMD ["uvicorn", "agile_hub.main:app", "--host", "0.0.0.0", "--port", "9120", "--reload", "--reload-dir", "/app/agile_hub"]
