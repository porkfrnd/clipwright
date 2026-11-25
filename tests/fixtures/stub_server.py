"""A local OpenAI-compatible stub used only to verify control flow.

It is never evidence that a real provider works. It answers with deterministic
segment ranges taken from the prompt so validation, refinement, dedupe and
ranking can be tested without network access or an API key.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SEG_LINE = re.compile(r"\[(s\d{4,6})\|(\d{2}):(\d{2}):(\d{2})\]")
CAND_LINE = re.compile(r"\[(\d+)\] (s\d{4,6})-(s\d{4,6})")


def _rating(score: int, evidence: str) -> dict[str, Any]:
    return {"score": score, "evidence": evidence}


class StubState:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.rate_limit_once = False
        self.lock = threading.Lock()


def make_handler(state: StubState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            return

        def _send(self, code: int, payload: dict[str, Any], extra_headers: dict[str, str] | None = None):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-ratelimit-limit-requests", "1000")
            self.send_header("x-ratelimit-remaining-requests", "999")
            self.send_header("x-ratelimit-limit-tokens", "8000")
            self.send_header("x-ratelimit-remaining-tokens", "7900")
            self.send_header("x-ratelimit-reset-tokens", "60s")
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.endswith("/models"):
                self._send(200, {"data": [{"id": "stub-model", "owned_by": "test"}]})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self._send(400, {"error": "bad json"})
                return
            with state.lock:
                state.requests.append(payload)
                if state.rate_limit_once:
                    state.rate_limit_once = False
                    self._send(429, {"error": {"message": "rate limited"}}, {"retry-after": "1"})
                    return
            messages = payload.get("messages") or []
            system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
            user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
            fmt = payload.get("response_format") or {}
            if "probe" in str(fmt) or "Reply with JSON only" in system:
                content = json.dumps({"ok": True})
            elif "Candidate summaries" in user or "rank" in system.lower() and "ranking" in user:
                candidates = CAND_LINE.findall(user)
                ranking = [
                    {"start_seg": s, "end_seg": e, "rank": i + 1, "best_overall": i == 0}
                    for i, (_, s, e) in enumerate(candidates)
                ]
                content = json.dumps({"ranking": ranking})
            elif "publishing metadata" in system.lower():
                content = json.dumps(
                    {
                        "title": "A clear test title",
                        "description": "A short description.",
                        "hashtags": ["#test", "#clips"],
                        "hook_suggestions": ["Start with the question."],
                        "thumbnail_text": ["SMALL MOMENTS"],
                        "thumbnail_time_s": 1.5,
                    }
                )
            else:
                segments = SEG_LINE.findall(user)
                if not segments:
                    content = json.dumps({"candidates": []})
                else:
                    first = segments[0][0]
                    last = segments[-1][0]
                    mid = segments[min(1, len(segments) - 1)][0]
                    content = json.dumps(
                        {
                            "candidates": [
                                {
                                    "category": "educational",
                                    "start_seg": first,
                                    "end_seg": last,
                                    "title": "The whole idea in one pass",
                                    "excerpt": "A test excerpt",
                                    "rationale": "It states the idea and then lands it with a clear closing line.",
                                    "ratings": {
                                        "hook_strength": _rating(4, "Opens by naming the subject directly."),
                                        "context_completeness": _rating(5, "The full explanation is inside the clip."),
                                        "ending_quality": _rating(4, "Ends after the closing line."),
                                        "standalone_clarity": _rating(5, "No earlier context is required."),
                                    },
                                    "weaknesses": ["Synthetic test audio."],
                                },
                                {
                                    "category": "insight",
                                    "start_seg": mid,
                                    "end_seg": last,
                                    "title": "The practical rule",
                                    "excerpt": "A shorter rule",
                                    "rationale": "It names the practical rule and explains why it works.",
                                    "ratings": {
                                        "hook_strength": _rating(3, "Starts mid-thought."),
                                        "context_completeness": _rating(4, "Enough context follows."),
                                        "ending_quality": _rating(4, "Closes on the rule."),
                                        "standalone_clarity": _rating(4, "Mostly understandable alone."),
                                    },
                                    "weaknesses": ["Needs the preceding sentence."],
                                },
                            ]
                        }
                    )
            self._send(
                200,
                {
                    "choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
                    "model": payload.get("model") or "stub-model",
                },
            )

    return Handler


class StubServer:
    def __init__(self, *, rate_limit_once: bool = False) -> None:
        self.state = StubState()
        self.state.rate_limit_once = rate_limit_once
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def __enter__(self) -> "StubServer":
        self.thread.start()
        return self

    def __exit__(self, *args) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
