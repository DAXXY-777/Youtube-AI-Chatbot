from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from database import Database
from main import create_public_api_app, create_ui_app
from runtime_service import RuntimeService
from secret_store import MemorySecretStore


class DesktopArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = RuntimeService(
            Database(Path(self.temp_dir.name) / "console.sqlite3"),
            MemorySecretStore(),
        )
        self.service.initialize()

    def tearDown(self) -> None:
        self.service.database.engine.dispose()
        self.temp_dir.cleanup()

    def test_public_api_has_no_activity_or_gradio_routes(self) -> None:
        app = create_public_api_app(self.service)
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/api/activity").status_code, 404)
            self.assertEqual(client.get("/").status_code, 404)

    def test_private_ui_exposes_activity_but_not_the_nightbot_route(self) -> None:
        app = create_ui_app(self.service)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/nightbot/ai?query=hello").status_code, 404)
            self.assertEqual(client.get("/api/activity").status_code, 404)

    def test_initializing_the_shared_service_twice_keeps_one_process_context(self) -> None:
        initial_context = self.service.get_request_context().stream_label
        self.service.initialize()

        self.assertEqual(initial_context, "No stream 1")
        self.assertEqual(self.service.get_request_context().stream_label, initial_context)
