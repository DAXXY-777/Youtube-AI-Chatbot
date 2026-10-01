from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from api import build_router
from database import Database
from orm_models import NightbotRequest, RuntimeConfiguration, Viewer, utc_now
from runtime_service import CLOUD_MODE, VIEWER_COOLDOWN, RuntimeService, ViewerIdentity
from secret_store import MemorySecretStore


VIEWER = ViewerIdentity(
    identity_key="youtube:1234",
    provider="youtube",
    provider_id="1234",
    username="stream_viewer",
    display_name="Stream Viewer",
    user_level="regular",
)

NIGHTBOT_HEADERS = {
    "Nightbot-User": (
        "name=stream_viewer&displayName=Stream+Viewer&provider=youtube&"
        "providerId=1234&userLevel=regular"
    ),
    "Nightbot-Channel": (
        "name=channel&displayName=Channel&provider=youtube&providerId=channel-1"
    ),
}

COMMAND_FALLBACK = "&viewer_id=youtube-viewer-1234&viewer_name=Stream+Viewer"


class RuntimeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "console.sqlite3"
        self.secret_store = MemorySecretStore()
        self.service = RuntimeService(Database(database_path), self.secret_store)
        self.service.initialize()

    def tearDown(self) -> None:
        self.service.database.engine.dispose()
        self.temp_dir.cleanup()

    def test_nightbot_route_persists_viewer_and_local_reply(self) -> None:
        app = FastAPI()
        app.include_router(build_router(self.service))
        client = TestClient(app)
        response = client.get(
            "/api/nightbot/ai?query=hello+there",
            headers=NIGHTBOT_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "Model not loaded.")
        stream, entries = self.service.list_activity()
        self.assertEqual(stream, "No stream 1")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].viewer, "Stream Viewer")
        self.assertEqual(entries[0].prompt, "hello there")

        with self.service.database.session_factory() as session:
            viewer = session.scalar(select(Viewer).where(Viewer.identity_key == "youtube:1234"))
            self.assertIsNotNone(viewer)
            self.assertEqual(viewer.user_level, "regular")

    def test_nightbot_route_accepts_a_valid_viewer_header_without_channel_metadata(
        self,
    ) -> None:
        app = FastAPI()
        app.include_router(build_router(self.service))

        response = TestClient(app).get(
            "/api/nightbot/ai?query=hello",
            headers={"Nightbot-User": NIGHTBOT_HEADERS["Nightbot-User"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "Model not loaded.")

    def test_nightbot_route_accepts_command_identity_when_header_is_missing(self) -> None:
        app = FastAPI()
        app.include_router(build_router(self.service))
        client = TestClient(app)

        response = client.get(f"/api/nightbot/ai?query=hello{COMMAND_FALLBACK}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "Model not loaded.")
        _stream, entries = self.service.list_activity()
        self.assertEqual(entries[0].viewer, "Stream Viewer")

        with self.service.database.session_factory() as session:
            viewer = session.scalar(
                select(Viewer).where(
                    Viewer.identity_key == "nightbot-command:youtube-viewer-1234"
                )
            )
            self.assertIsNotNone(viewer)

    def test_nightbot_route_rejects_missing_identity_and_handles_blank_prompts(self) -> None:
        app = FastAPI()
        app.include_router(build_router(self.service))
        client = TestClient(app)

        self.assertEqual(client.get("/api/nightbot/ai?query=hello").status_code, 404)
        blank = client.get("/api/nightbot/ai?query=", headers=NIGHTBOT_HEADERS)
        self.assertEqual(blank.status_code, 200)
        self.assertEqual(blank.text, "Ask me a question.")
        self.assertEqual(blank.headers["cache-control"], "no-store")

    def test_nightbot_route_enforces_a_one_minute_viewer_cooldown(self) -> None:
        app = FastAPI()
        app.include_router(build_router(self.service))
        client = TestClient(app)

        first = client.get(f"/api/nightbot/ai?query=first{COMMAND_FALLBACK}")
        second = client.get(f"/api/nightbot/ai?query=second{COMMAND_FALLBACK}")

        self.assertEqual(first.text, "Model not loaded.")
        self.assertEqual(second.text, "Please wait before asking again.")
        self.assertEqual(VIEWER_COOLDOWN, timedelta(minutes=1))

    def test_cloud_mode_persists_and_uses_the_same_public_route(self) -> None:
        self.service.save_mode("Cloud")
        restarted = RuntimeService(self.service.database, self.secret_store)
        restarted.initialize()

        self.assertEqual(restarted.get_settings().active_mode, CLOUD_MODE)
        app = FastAPI()
        app.include_router(build_router(restarted))
        response = TestClient(app).get("/api/nightbot/ai?query=hello", headers=NIGHTBOT_HEADERS)

        self.assertEqual(response.text, "Cloud provider not configured.")
        self.assertNotIn("/local", [route.path for route in app.routes])
        self.assertNotIn("/cloud", [route.path for route in app.routes])

    def test_cloud_secret_is_not_a_database_column_or_returned_setting(self) -> None:
        self.service.save_cloud_settings(
            "https://provider.example/v1", "top-secret", "chat-model"
        )
        settings = self.service.get_settings()

        self.assertTrue(settings.cloud_api_key_configured)
        self.assertEqual(self.secret_store.get_cloud_api_key(), "top-secret")
        self.assertNotIn("cloud_api_key", RuntimeConfiguration.__table__.columns.keys())
        self.assertNotIn("top-secret", repr(settings))

    def test_invalid_cloud_edit_preserves_the_last_working_setup_and_key(self) -> None:
        self.service.save_cloud_settings(
            "https://provider.example/v1", "first-secret", "first-model"
        )

        with self.assertRaises(ValueError):
            self.service.save_cloud_settings(
                "http://provider.example/v1", "replacement-secret", "second-model"
            )

        settings = self.service.get_settings()
        self.assertEqual(settings.cloud_base_url, "https://provider.example/v1")
        self.assertEqual(settings.cloud_model_id, "first-model")
        self.assertEqual(self.secret_store.get_cloud_api_key(), "first-secret")

    def test_activity_is_filtered_to_the_active_stream_and_clear_uses_no_stream(self) -> None:
        self.service.set_active_stream("https://www.youtube.com/watch?v=first01")
        first_context = self.service.get_request_context()
        self.service.record_request(first_context, VIEWER, "first", "Model not loaded.")

        self.service.set_active_stream("https://www.youtube.com/watch?v=second02")
        second_context = self.service.get_request_context()
        self.service.record_request(second_context, VIEWER, "second", "Model not loaded.")
        active_stream, active_entries = self.service.list_activity()

        self.assertEqual(active_stream, "https://www.youtube.com/watch?v=second02")
        self.assertEqual([entry.prompt for entry in active_entries], ["second"])

        self.service.set_active_stream("")
        no_stream, no_stream_entries = self.service.list_activity()
        self.assertEqual(no_stream, "No stream 1")
        self.assertEqual(no_stream_entries, [])

    def test_prunes_requests_older_than_thirty_days_before_recording(self) -> None:
        context = self.service.get_request_context()
        self.service.record_request(context, VIEWER, "current", "Model not loaded.")

        with self.service.database.session_factory() as session:
            viewer = session.scalar(select(Viewer).where(Viewer.identity_key == VIEWER.identity_key))
            self.assertIsNotNone(viewer)
            session.add(
                NightbotRequest(
                    viewer_id=viewer.id,
                    stream_context_id=context.stream_context_id,
                    mode="local",
                    prompt="expired",
                    response="expired",
                    received_at=utc_now() - timedelta(days=31),
                )
            )
            session.commit()

        self.service.record_request(context, VIEWER, "new", "Model not loaded.")
        _stream, entries = self.service.list_activity()

        self.assertEqual([entry.prompt for entry in entries], ["current", "new"])

    def test_each_restart_creates_a_new_no_stream_context(self) -> None:
        initial_context = self.service.get_request_context()
        self.assertEqual(initial_context.stream_label, "No stream 1")

        restarted = RuntimeService(self.service.database, self.secret_store)
        restarted.initialize()

        self.assertEqual(restarted.get_request_context().stream_label, "No stream 2")

    def test_viewer_cooldown_survives_a_service_restart(self) -> None:
        self.assertTrue(self.service.claim_viewer_cooldown(VIEWER))

        restarted = RuntimeService(self.service.database, self.secret_store)
        restarted.initialize()

        self.assertFalse(restarted.claim_viewer_cooldown(VIEWER))

    def test_recording_an_older_request_keeps_its_stream_context_after_a_switch(self) -> None:
        self.service.set_active_stream("https://www.youtube.com/watch?v=first01")
        first_context = self.service.get_request_context()
        self.service.set_active_stream("https://www.youtube.com/watch?v=second02")

        request_id = self.service.record_request(
            first_context, VIEWER, "still finishing", "Model not loaded."
        )

        self.assertIsNotNone(request_id)
        self.service.set_active_stream("https://www.youtube.com/watch?v=first01")
        _stream, activity = self.service.list_activity()
        self.assertEqual([entry.prompt for entry in activity], ["still finishing"])

    def test_database_startup_failure_uses_temporary_memory_mode(self) -> None:
        class UnavailableDatabase:
            def initialize(self) -> None:
                raise OSError("disk unavailable")

        service = RuntimeService(UnavailableDatabase(), MemorySecretStore())
        service.initialize()

        self.assertTrue(service.get_settings().temporary_memory_mode)
        self.assertTrue(service.claim_viewer_cooldown(VIEWER))
        self.assertFalse(service.claim_viewer_cooldown(VIEWER))
        self.assertIsNone(
            service.record_request(
                service.get_request_context(), VIEWER, "hello", "Model not loaded."
            )
        )
