from __future__ import annotations

import sys

import pytest

from shorts_engine.common.proc import ProcessRunner


@pytest.mark.asyncio
async def test_process_runner_reads_stdout_lines_larger_than_asyncio_default_limit():
    result = await ProcessRunner().run(
        [sys.executable, "-c", "print('x' * 200_000)"],
        timeout=30,
    )
    assert result.returncode == 0
    assert len(result.stdout) == 200_001
    assert set(result.stdout.strip()) == {"x"}
