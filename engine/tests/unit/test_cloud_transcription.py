from __future__ import annotations

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from shorts_engine.common.errors import RateLimited
from shorts_engine.transcription.cloud_openai import CloudTranscriptionEngine


class _RateLimitedHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get('content-length', '0'))
        self.rfile.read(length)
        self.send_response(429)
        self.send_header('content-type', 'application/json')
        self.send_header('retry-after', '12')
        self.end_headers()
        self.wfile.write(b'{"error":{"message":"slow down"}}')

    def log_message(self, *args: object) -> None:
        pass


@pytest.mark.asyncio
async def test_cloud_transcription_surfaces_429_without_sleeping(tmp_path) -> None:
    server = ThreadingHTTPServer(('127.0.0.1', 0), _RateLimitedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        audio = tmp_path / 'chunk.wav'
        audio.write_bytes(b'RIFF0000WAVE')
        engine = CloudTranscriptionEngine(
            base_url=f'http://127.0.0.1:{server.server_port}',
            api_key='test-key',
            max_retries=3,
        )
        started = time.monotonic()
        with pytest.raises(RateLimited) as caught:
            await engine._transcribe_chunk(audio, 'en', True, None)
        assert caught.value.retry_after_s == 12
        assert time.monotonic() - started < 2, '429 must reach the job manager immediately'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
