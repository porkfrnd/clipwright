from __future__ import annotations

from typing import Any

from ..storage.repos import DEFAULT_EDIT


def _merge(overrides: dict[str, Any]) -> dict[str, Any]:
    import json

    base = json.loads(json.dumps(DEFAULT_EDIT))
    for key, value in overrides.items():
        if isinstance(value, dict):
            base[key].update(value)
        else:
            base[key] = value
    return base


BUILTIN_PRESETS: list[dict[str, Any]] = [
    {
        "id": "preset-podcast",
        "name": "Podcast",
        "settings": _merge(
            {
                "framing": {"layout": "blur"},
                "subtitles": {"fontSize": 66, "position": "lower_third", "highlightColor": "#F2C46D"},
                "effects": {"enabled": True, "fade": True},
                "audio": {"voiceEnhance": True, "loudnessTarget": -14.0},
            }
        ),
    },
    {
        "id": "preset-educational",
        "name": "Educational",
        "settings": _merge(
            {
                "framing": {"layout": "fill"},
                "subtitles": {"fontSize": 64, "highlightColor": "#7FD1C1", "position": "lower_third"},
                "effects": {"enabled": False, "fade": True},
                "audio": {"voiceEnhance": True},
            }
        ),
    },
    {
        "id": "preset-storytelling",
        "name": "Storytelling",
        "settings": _merge(
            {
                "framing": {"layout": "fill"},
                "subtitles": {"fontSize": 62, "highlightColor": "#E8C77B", "position": "lower_third"},
                "effects": {"enabled": True, "cinematic": True, "fade": True},
                "audio": {"loudnessTarget": -14.0},
            }
        ),
    },
    {
        "id": "preset-gaming",
        "name": "Gaming",
        "settings": _merge(
            {
                "framing": {"layout": "fill"},
                "subtitles": {"fontSize": 70, "highlightColor": "#FF7A45", "outline": 5},
                "effects": {"enabled": True, "zoomPunch": False, "fade": True},
                "audio": {"denoise": False, "loudnessTarget": -13.0},
            }
        ),
    },
    {
        "id": "preset-minimal",
        "name": "Minimal",
        "settings": _merge(
            {
                "framing": {"layout": "fill"},
                "subtitles": {"enabled": True, "fontSize": 58, "highlightColor": "#FFFFFF", "outline": 3},
                "effects": {"enabled": False, "fade": False, "progressBar": False, "cinematic": False},
                "audio": {"voiceEnhance": False, "denoise": False},
            }
        ),
    },
]
