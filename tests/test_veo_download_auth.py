import veo_generator


class _DummyClient:
    """Minimal stub to satisfy VeoVideoGenerator client creation in tests."""

    def __init__(self, *args, **kwargs):
        pass


class _FakeResponse:
    def __init__(self, captured):
        self.status_code = 200
        self._captured = captured

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        self._captured["chunk_size"] = chunk_size
        yield b"payload"


def _make_fake_get(captured: dict):
    """Return a requests.get stub that captures headers and url."""

    def _fake_get(url, headers=None, timeout=None, stream=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["timeout"] = timeout
        captured["stream"] = stream
        return _FakeResponse(captured)

    return _fake_get


def _stub_client(monkeypatch):
    monkeypatch.setattr(veo_generator.genai, "Client", lambda **_: _DummyClient())


def test_vertex_ai_refreshes_credentials(monkeypatch, tmp_path):
    _stub_client(monkeypatch)
    monkeypatch.setattr(veo_generator, "HAS_GOOGLE_AUTH", True)

    captured = {}
    monkeypatch.setattr(veo_generator.requests, "get", _make_fake_get(captured))

    class _FakeCredentials:
        def __init__(self):
            self.token = None
            self.expired = True
            self.refresh_called = False

        def refresh(self, _request):
            self.refresh_called = True
            self.expired = False
            self.token = "refreshed-token"

    fake_creds = _FakeCredentials()
    monkeypatch.setattr(
        veo_generator,
        "get_default_credentials",
        lambda: (fake_creds, "demo-project"),
    )

    generator = veo_generator.VeoVideoGenerator(
        project_id="demo-project",
        api_key="unused",
        use_vertex_ai=True,
    )

    output_path = tmp_path / "video.mp4"
    generator._download_from_uri("gs://bucket/object.mp4", output_path)

    assert fake_creds.refresh_called is True
    assert captured["headers"].get("Authorization") == "Bearer refreshed-token"
    assert output_path.exists()
    assert output_path.read_bytes() == b"payload"


def test_studio_mode_uses_api_key(monkeypatch, tmp_path):
    _stub_client(monkeypatch)
    monkeypatch.setattr(veo_generator, "HAS_GOOGLE_AUTH", False)

    captured = {}
    monkeypatch.setattr(veo_generator.requests, "get", _make_fake_get(captured))

    generator = veo_generator.VeoVideoGenerator(
        api_key="studio-api-key",
        use_vertex_ai=False,
        project_id=None,
    )

    output_path = tmp_path / "studio.mp4"
    generator._download_from_uri("https://example.com/video.mp4", output_path)

    assert captured["headers"].get("X-Goog-API-Key") == "studio-api-key"
    assert "Authorization" not in captured["headers"]
    assert output_path.exists()
    assert output_path.read_bytes() == b"payload"
