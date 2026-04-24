"""
Campus Eye — Smoke Tests
Run: pytest tests/ -v
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock, AsyncMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def client():
    """
    Provides an HTTPX async test client.
    Patches heavy ML models so tests run without GPU/model files.
    """
    mock_recognizer = MagicMock()
    mock_recognizer.detect_faces.return_value = []
    mock_recognizer.generate_embedding.return_value = None
    mock_recognizer.generate_embedding_from_file.return_value = None

    mock_detector = MagicMock()
    mock_detector.detect_persons.return_value = []
    mock_detector.detect_exam_objects.return_value = []
    mock_detector.get_pose_keypoints.return_value = []

    with patch("app.pipeline.face_recognition.get_face_recognizer", return_value=mock_recognizer), \
         patch("app.pipeline.object_detector.get_object_detector", return_value=mock_detector), \
         patch("app.pipeline.processor.FrameProcessor.run", new_callable=AsyncMock):

        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ── Faces API ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_faces_empty(client):
    resp = await client.get("/api/faces/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_register_face_no_photo(client):
    """Registration without a photo should return 422."""
    resp = await client.post("/api/faces/register", data={"name": "Test User", "role": "student"})
    assert resp.status_code == 422


# ── Events API ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_events(client):
    resp = await client.get("/api/events/")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data


@pytest.mark.anyio
async def test_get_nonexistent_event(client):
    resp = await client.get("/api/events/99999")
    assert resp.status_code == 404


# ── Settings API ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_mode(client):
    resp = await client.get("/api/settings/mode")
    assert resp.status_code == 200
    assert resp.json()["mode"] in ("normal", "exam")


@pytest.mark.anyio
async def test_set_mode_normal(client):
    resp = await client.post("/api/settings/mode", json={"mode": "normal"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "normal"


@pytest.mark.anyio
async def test_set_mode_exam(client):
    resp = await client.post("/api/settings/mode", json={"mode": "exam"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "exam"


@pytest.mark.anyio
async def test_set_mode_invalid(client):
    resp = await client.post("/api/settings/mode", json={"mode": "invalid_mode"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_get_schedule(client):
    resp = await client.get("/api/settings/schedule")
    assert resp.status_code == 200
    assert "schedule" in resp.json()


# ── Stream ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_snapshot_returns_image(client):
    resp = await client.get("/api/stream/snapshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
