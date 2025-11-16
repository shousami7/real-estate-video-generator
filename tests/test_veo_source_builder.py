import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image
from google.genai import types

import veo_generator


class _StubClient:
    def __init__(self, *args, **kwargs):
        self.files = None
        self.models = None
        self.operations = None


def _stub_client(monkeypatch):
    monkeypatch.setattr(veo_generator.genai, "Client", lambda **_: _StubClient())


def test_source_builder_uses_image_when_available(monkeypatch, tmp_path):
    _stub_client(monkeypatch)
    image_path = tmp_path / "frame.png"
    Image.new("RGB", (2, 2), color=(255, 255, 255)).save(image_path)

    generator = veo_generator.VeoVideoGenerator(api_key="demo-key")

    source = generator._build_generate_videos_source(
        prompt="luxury skyline",
        image_path=str(image_path),
        previous_video=None,
    )

    assert source.prompt == "luxury skyline"
    assert source.image is not None
    assert source.video is None


def test_source_builder_prefers_previous_video(monkeypatch):
    _stub_client(monkeypatch)
    generator = veo_generator.VeoVideoGenerator(api_key="demo-key")

    prior_video = types.Video(uri="gs://bucket/video.mp4", mime_type="video/mp4")

    source = generator._build_generate_videos_source(
        prompt="extend scene",
        image_path=None,
        previous_video=prior_video,
    )

    assert source.prompt == "extend scene"
    assert source.video is not None
    assert source.video.uri == "gs://bucket/video.mp4"
    assert source.image is None
