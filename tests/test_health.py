import json
import socket
import threading
import time
from contextlib import closing
from urllib.request import urlopen

import uvicorn
import pytest

from app.api.health import health
from app.main import app


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _wait_for_port(host: str, port: int, timeout_seconds: float = 5.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"Server on {host}:{port} did not start in time.")


def _request_health_over_http() -> tuple[int, dict[str, str]]:
    port = _find_free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for_port("127.0.0.1", port)

    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_health_endpoint_returns_ok() -> None:
    try:
        status_code, payload = _request_health_over_http()
    except PermissionError as exc:
        pytest.skip(f"socket access is not available in this environment: {exc}")

    assert status_code == 200
    assert payload == {"status": "ok"}


def test_health_endpoint_does_not_require_external_services(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("MARKET_DATA_API_KEY", raising=False)
    monkeypatch.delenv("NEWS_API_KEY", raising=False)

    assert "get" in app.openapi()["paths"]["/health"]
    assert health() == {"status": "ok"}
