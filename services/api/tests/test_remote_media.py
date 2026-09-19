import hashlib
import importlib.util
from email.message import Message
from io import BytesIO
from pathlib import Path

import pytest

from app.remote_media import download_image, linkedin_image_url, merge_media


def test_only_linkedin_cdn_can_be_downloaded():
    assert linkedin_image_url("https://media.licdn.com/dms/image/test")
    for url in ("http://media.licdn.com/a", "https://127.0.0.1/a", "https://media.licdn.com.evil.test/a",
                "https://user:pass@media.licdn.com/a", "file:///etc/passwd"):
        assert linkedin_image_url(url) is None


def test_download_is_bounded_atomic_and_content_addressed(tmp_path, monkeypatch):
    payload = b"test-image-bytes"

    class Response(BytesIO):
        headers = Message()
        headers["Content-Type"] = "image/jpeg"

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response(payload)

    monkeypatch.setattr("urllib.request.build_opener", lambda *_args: Opener())
    first = download_image("https://media.licdn.com/a", tmp_path)
    second = download_image("https://media.licdn.com/b", tmp_path)
    assert first == second
    assert first[0] == hashlib.sha256(payload).hexdigest()
    assert Path(first[1]).read_bytes() == payload
    assert len(list((tmp_path / "sha256").rglob("*"))) == 3
    with pytest.raises(ValueError, match="limit"):
        download_image("https://media.licdn.com/c", tmp_path, max_bytes=2)
    assert list((tmp_path / ".staging").iterdir()) == []


def test_timeline_prefers_local_media_and_preserves_pending_media():
    result = merge_media([
        {"source_url": "https://media.licdn.com/a", "role": "media-1"},
        {"source_url": "https://media.licdn.com/b", "role": "media-2"},
    ], [{"source_url": "https://media.licdn.com/a", "id": "asset-1", "role": "media-1"}])
    assert len(result) == 2
    assert result[0]["id"] == "asset-1"
    assert result[1]["source_url"].endswith("/b")


def test_collector_avatar_belongs_to_target_and_uses_largest_photo():
    path = Path(__file__).parents[3] / "infra/linkedin/profile_media.py"
    spec = importlib.util.spec_from_file_location("profile_media", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = {"included": [
        {"publicIdentifier": "someone-else", "picture": {
            "rootUrl": "https://media.licdn.com/", "artifacts": [
                {"width": 1000, "fileIdentifyingUrlPathSegment": "wrong.jpg"}]}},
        {"publicIdentifier": "target", "profilePicture": {"displayImageReference": {
            "vectorImage": {"rootUrl": "https://media.licdn.com/", "artifacts": [
                {"width": 100, "fileIdentifyingUrlPathSegment": "small.jpg"},
                {"width": 800, "fileIdentifyingUrlPathSegment": "large.jpg"}]}}}},
    ]}
    assert module.profile_avatar(raw, "target") == "https://media.licdn.com/large.jpg"
    assert module.profile_avatar(raw, "missing") is None
