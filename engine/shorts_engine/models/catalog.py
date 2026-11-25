from __future__ import annotations

from typing import Any

WHISPER_MODELS: list[dict[str, Any]] = [
    {
        "name": "tiny",
        "label": "Tiny (fastest, lowest accuracy)",
        "repo": "Systran/faster-whisper-tiny",
        "revision": "d90ca5fe260221311c53c58e660288d3deb8d356",
        "download_mb": 75,
        "ram_mb": 350,
        "languages": "multilingual",
        "tier": "low",
    },
    {
        "name": "base",
        "label": "Base",
        "repo": "Systran/faster-whisper-base",
        "revision": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
        "download_mb": 145,
        "ram_mb": 600,
        "languages": "multilingual",
        "tier": "low",
    },
    {
        "name": "small",
        "label": "Small (recommended for most laptops)",
        "repo": "Systran/faster-whisper-small",
        "revision": "536b0662742c02347bc0e980a01041f333bce120",
        "download_mb": 484,
        "ram_mb": 1200,
        "languages": "multilingual",
        "tier": "balanced",
    },
    {
        "name": "distil-small.en",
        "label": "Distil Small (English only, faster)",
        "repo": "Systran/faster-distil-whisper-small.en",
        "revision": "ef77d90526ccd62cde3808ee70626a01e5cf83e4",
        "download_mb": 166,
        "ram_mb": 800,
        "languages": "English",
        "tier": "balanced",
    },
    {
        "name": "medium",
        "label": "Medium",
        "repo": "Systran/faster-whisper-medium",
        "revision": "08e178d48790749d25932bbc082711ddcfdfbc4f",
        "download_mb": 1525,
        "ram_mb": 2800,
        "languages": "multilingual",
        "tier": "performance",
    },
    {
        "name": "large-v3",
        "label": "Large v3 (most accurate)",
        "repo": "Systran/faster-whisper-large-v3",
        "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        "download_mb": 3090,
        "ram_mb": 5200,
        "languages": "multilingual",
        "tier": "performance",
    },
    {
        "name": "distil-large-v3",
        "label": "Distil Large v3 (English, fast)",
        "repo": "Systran/faster-distil-whisper-large-v3",
        "revision": "c3058b475261292e64a0412df1d2681c06260fab",
        "download_mb": 1510,
        "ram_mb": 3400,
        "languages": "English",
        "tier": "performance",
    },
    {
        "name": "large-v3-turbo",
        "label": "Large v3 Turbo (good balance)",
        "repo": "deepdml/faster-whisper-large-v3-turbo-ct2",
        "revision": "4df90f75321148c3a29a9e2351b7ddf8f5b115a8",
        "download_mb": 1620,
        "ram_mb": 3600,
        "languages": "multilingual",
        "tier": "performance",
    },
]

LLM_MODELS: list[dict[str, Any]] = [
    {
        "name": "qwen3-0.6b",
        "label": "Qwen3 0.6B (local AI, Q8_0)",
        "repo": "Qwen/Qwen3-0.6B-GGUF",
        "revision": "23749fefcc72300e3a2ad315e1317431b06b590a",
        "filename": "Qwen3-0.6B-Q8_0.gguf",
        "url": "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/23749fefcc72300e3a2ad315e1317431b06b590a/Qwen3-0.6B-Q8_0.gguf",
        "sha256": "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
        "bytes": 639446688,
        "download_mb": 610,
        "ram_mb": 1100,
        "context_tokens": 16384,
        "license": "Apache-2.0 (Qwen3, Alibaba Cloud)",
        "tier": "low",
    },
]

FACE_MODELS: list[dict[str, Any]] = [
    {
        "name": "yunet-2023mar",
        "label": "YuNet face detector",
        "url": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "bytes": 232589,
        "license": "MIT (OpenCV Zoo, Shiqi Yu)",
        "download_mb": 0.3,
    }
]


def whisper_catalog() -> list[dict[str, Any]]:
    return [
        {
            "kind": "whisper",
            "name": m["name"],
            "label": m["label"],
            "downloadMb": m["download_mb"],
            "ramMb": m["ram_mb"],
            "languages": m["languages"],
            "tier": m["tier"],
            "license": "MIT (OpenAI Whisper weights, converted by Systran)",
        }
        for m in WHISPER_MODELS
    ]


def llm_catalog() -> list[dict[str, Any]]:
    return [
        {
            "kind": "llm",
            "name": m["name"],
            "label": m["label"],
            "downloadMb": m["download_mb"],
            "ramMb": m["ram_mb"],
            "languages": "English + multilingual",
            "tier": m["tier"],
            "license": m["license"],
            "contextTokens": m["context_tokens"],
        }
        for m in LLM_MODELS
    ]


def face_catalog() -> list[dict[str, Any]]:
    return [
        {
            "kind": "face",
            "name": m["name"],
            "label": m["label"],
            "downloadMb": m["download_mb"],
            "license": m["license"],
        }
        for m in FACE_MODELS
    ]
