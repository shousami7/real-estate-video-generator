import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.video_duration import probe_video_duration


def test_mp4_duration_parser_fallback():
    # Force the fallback path by pointing to a binary that does not exist.
    duration = probe_video_duration(
        "test_output_fixed.mp4",
        ffmpeg_path="__missing_ffmpeg_binary__",
    )
    assert math.isclose(duration, 23.0, rel_tol=1e-3)


def test_demo_video_duration_matches_metadata():
    duration = probe_video_duration(
        "static/demo_videos/parking_lot_demo.mp4",
        ffmpeg_path="__missing_ffmpeg_binary__",
    )
    assert math.isclose(duration, 15.5, rel_tol=1e-3)
