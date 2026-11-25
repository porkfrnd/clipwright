from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class EngineProcess:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        env = {
            **os.environ,
            "CLIPWRIGHT_DATA_DIR": str(data_dir),
            "CLIPWRIGHT_RESOURCES": str(REPO / "resources"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(REPO / "engine"),
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "shorts_engine", "--stdio"],
            cwd=REPO,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.lines: queue.Queue[dict] = queue.Queue()
        self.raw: list[str] = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.events: list[dict] = []
        self.next_id = 1

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.raw.append(line)
            try:
                self.lines.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def send(self, method: str, params: dict | None = None, secrets: dict | None = None) -> str:
        request_id = f"req-{self.next_id}"
        self.next_id += 1
        payload = {"v": 1, "id": request_id, "method": method, "params": params or {}}
        if secrets:
            payload["secrets"] = secrets
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        return request_id

    def wait(self, request_id: str, timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.lines.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if message.get("method"):
                self.events.append(message)
                continue
            if message.get("id") == request_id:
                return message
        raise AssertionError(
            f"no response for request {request_id}; events={self.events[-5:]}; raw={self.raw[-5:]}"
        )

    def request(self, method: str, params: dict | None = None, secrets: dict | None = None, timeout: float = 30.0) -> dict:
        return self.wait(self.send(method, params, secrets), timeout=timeout)

    def kill(self) -> None:
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=10)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin and self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.kill()
        try:
            self.proc.stdout and self.proc.stdout.close()
        except Exception:
            pass


def test_protocol_handshake_and_error_envelope(tmp_path: Path):
    engine = EngineProcess(tmp_path / "engine")
    try:
        handshake = engine.request("engine.hello", {"protocolVersion": 1, "appVersion": "test"})
        assert "error" not in handshake
        result = handshake["result"]
        assert result["protocolVersion"] == 1
        assert result["productName"] == "Clipwright"
        assert result["engineVersion"]
        assert str(tmp_path / "engine") in result["dataDir"]

        pong = engine.request("engine.ping")
        assert pong["result"]["pong"] is True

        mismatch = engine.request("engine.hello", {"protocolVersion": 99, "appVersion": "test"})
        assert mismatch["error"]["code"] == "ENGINE_PROTOCOL_MISMATCH"

        unknown = engine.request("not.a.method")
        assert unknown["error"]["code"] == "METHOD_NOT_FOUND"
        assert unknown["error"]["message"]

        bad_params = engine.request("project.create", {"name": ""})
        assert bad_params["error"]["code"] in ("INVALID_PARAMS", "VALIDATION_ERROR")
    finally:
        engine.close()


def test_project_survives_engine_kill_and_restart(tmp_path: Path):
    data_dir = tmp_path / "engine"
    engine = EngineProcess(data_dir)
    try:
        engine.request("engine.hello", {"protocolVersion": 1, "appVersion": "test"})
        created = engine.request("project.create", {"name": "Survives a kill"})
        project_id = created["result"]["project"]["id"]
        assert created["result"]["project"]["name"] == "Survives a kill"
        engine.kill()
    finally:
        engine.close()

    engine2 = EngineProcess(data_dir)
    try:
        engine2.request("engine.hello", {"protocolVersion": 1, "appVersion": "test"})
        listed = engine2.request("project.list")
        ids = [p["id"] for p in listed["result"]["projects"]]
        assert project_id in ids
        opened = engine2.request("project.open", {"projectId": project_id})
        assert opened["result"]["project"]["name"] == "Survives a kill"
    finally:
        engine2.close()


def test_handshake_failure_does_not_pretend_to_be_ready(tmp_path: Path):
    engine = EngineProcess(tmp_path / "engine")
    try:
        response = engine.request("engine.hello", {"protocolVersion": 2, "appVersion": "test"})
        assert response["error"]["code"] == "ENGINE_PROTOCOL_MISMATCH"
        # The engine stays alive to answer the app and allow a clean shutdown.
        assert engine.request("engine.ping")["result"]["pong"] is True
    finally:
        engine.close()
