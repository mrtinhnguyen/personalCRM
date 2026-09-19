FROM python:3.12-slim
WORKDIR /app
COPY services/api/pyproject.toml services/api/uv.lock* ./
RUN pip install --no-cache-dir uv && uv sync --no-dev --compile-bytecode
COPY services/api/app ./app
COPY migrations /migrations
RUN .venv/bin/python -m compileall -q app
ENV PYTHONPATH=/app UV_NO_SYNC=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
