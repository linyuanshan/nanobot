FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY hatchery/ hatchery/

RUN uv pip install --system --no-cache fastapi uvicorn paho-mqtt pydantic httpx

EXPOSE 8090

CMD ["uvicorn", "hatchery.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]
