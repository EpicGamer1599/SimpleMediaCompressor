import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from simplemedia.ffmpeg import detect


@pytest.fixture(scope="session")
def ffmpeg_info():
    info = detect()
    if not info.available or not info.probe:
        pytest.skip("FFmpeg and FFprobe are required for real codec integration tests")
    return info
