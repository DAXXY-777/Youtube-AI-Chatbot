from __future__ import annotations

import logging
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import build_router
from database import Database
from inference_control import (
    InferenceBusyError,
    InferenceTimeoutError,
    SingleWorkerInferenceQueue,
)
from logging_config import LOGGER_NAME, configure_logging
from network_safety import validate_cloud_base_url
from runtime_service import RuntimeService, ViewerIdentity
from secret_store import MemorySecretStore


VIEWER = ViewerIdentity(
    identity_key="test:viewer",
    provider="test",
    provider_id="viewer",
    username="viewer",
    display_name="Viewer",
    user_level="regular",
)


class ProductionProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "console.sqlite3"
        self.service = RuntimeService(Database(self.database_path), MemorySecretStore())
        self.service.initialize()

    def tearDown(self) -> None:
        self.service.database.engine.dispose()
        self.temp_dir.cleanup()

    def test_cloud_url_allows_lan_http_but_requires_https_for_public_hosts(self) -> None:
        self.assertEqual(
            validate_cloud_base_url("http://127.0.0.1:8000/v1"),
            "http://127.0.0.1:8000/v1",
        )
        self.assertEqual(
            validate_cloud_base_url("http://10.0.0.8/v1"),
            "http://10.0.0.8/v1",
        )
        with self.assertRaises(ValueError):
            validate_cloud_base_url("http://provider.example/v1")
        self.assertEqual(
            validate_cloud_base_url("https://provider.example/v1"),
            "https://provider.example/v1",
        )

    def test_local_queue_rejects_when_the_single_worker_is_occupied(self) -> None:
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        queue = SingleWorkerInferenceQueue(capacity=1, deadline_seconds=1)

        def slow_action() -> str:
            started.set()
            release.wait(timeout=2)
            completed.set()
            return "done"

        result: list[str] = []
        worker = threading.Thread(target=lambda: result.append(queue.run(slow_action)))
        worker.start()
        self.assertTrue(started.wait(timeout=1))
        with self.assertRaises(InferenceBusyError):
            queue.run(lambda: "second")
        release.set()
        worker.join(timeout=2)
        queue.shutdown()

        self.assertTrue(completed.is_set())
        self.assertEqual(result, ["done"])

    def test_local_queue_times_out_without_reusing_the_running_model_slot(self) -> None:
        started = threading.Event()
        release = threading.Event()
        queue = SingleWorkerInferenceQueue(capacity=1, deadline_seconds=0.01)

        def slow_action() -> str:
            started.set()
            release.wait(timeout=2)
            return "done"

        with self.assertRaises(InferenceTimeoutError):
            queue.run(slow_action)
        self.assertTrue(started.is_set())
        with self.assertRaises(InferenceBusyError):
            queue.run(lambda: "second")
        release.set()
        queue.shutdown()

    def test_local_queue_can_restart_after_the_servers_stop(self) -> None:
        queue = SingleWorkerInferenceQueue(capacity=1, deadline_seconds=1)

        self.assertEqual(queue.run(lambda: "first"), "first")
        queue.shutdown()
        self.assertEqual(queue.run(lambda: "second"), "second")
        queue.shutdown()

    def test_activity_api_requires_an_explicit_private_token(self) -> None:
        app = FastAPI()
        app.include_router(build_router(self.service))
        client = TestClient(app)

        self.assertEqual(client.get("/api/activity").status_code, 404)
        with patch.dict(os.environ, {"NIGHTBOT_ACTIVITY_TOKEN": "private-token"}):
            self.assertEqual(client.get("/api/activity").status_code, 404)
            authorized = client.get(
                "/api/activity", headers={"X-Activity-Token": "private-token"}
            )
        self.assertEqual(authorized.status_code, 200)

    def test_unwritable_log_directory_does_not_block_runtime_fallback(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        original_handlers = list(logger.handlers)
        for handler in original_handlers:
            logger.removeHandler(handler)
        blocked_path = Path(self.temp_dir.name) / "not-a-directory"
        blocked_path.write_text("blocked", encoding="utf-8")
        try:
            with patch("logging_config.LOG_DIRECTORY", blocked_path):
                configured = configure_logging()
            self.assertTrue(
                any(isinstance(handler, logging.NullHandler) for handler in configured.handlers)
            )
        finally:
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            for handler in original_handlers:
                logger.addHandler(handler)
