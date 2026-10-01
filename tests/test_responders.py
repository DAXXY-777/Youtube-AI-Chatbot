from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from database import Database
from memory import AmbientChatMessage
from model_runtime import LOCAL_CONTEXT_TOKENS, LocalModelRuntime
from prompting import MAX_OUTPUT_TOKENS, MAX_REPLY_CHARACTERS
from responders import CloudResponder, LocalResponder
from runtime_service import RuntimeService, ViewerIdentity
from secret_store import MemorySecretStore


VIEWER = ViewerIdentity(
    identity_key="youtube:test-viewer",
    provider="youtube",
    provider_id="test-viewer",
    username="test_viewer",
    display_name="Test Viewer",
    user_level="regular",
)


class FakeLlama:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.last_completion: dict[str, Any] | None = None

    def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.last_completion = kwargs
        return {"choices": [{"message": {"content": "  Great   question.  "}}]}


class FakeHttpResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "Cloud answer."}}]}


class ResponderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "console.sqlite3"
        self.secrets = MemorySecretStore()
        self.service = RuntimeService(Database(database_path), self.secrets)
        self.service.initialize()

    def tearDown(self) -> None:
        self.service.database.engine.dispose()
        self.temp_dir.cleanup()

    def test_local_download_loads_selected_gguf_and_limits_generation(self) -> None:
        fake_llama = FakeLlama()
        downloaded: dict[str, Any] = {}

        def downloader(**kwargs: Any) -> str:
            downloaded.update(kwargs)
            target = Path(kwargs["local_dir"]) / kwargs["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake gguf")
            return str(target)

        llama_arguments: dict[str, Any] = {}
        runtime = LocalModelRuntime(
            Path(self.temp_dir.name) / "models",
            downloader=downloader,
            llama_factory=lambda **kwargs: llama_arguments.update(kwargs) or fake_llama,
            gpu_support=lambda: False,
        )
        model_path = runtime.download_and_load("Qwen 3.5")

        self.assertTrue(model_path.is_file())
        self.assertEqual(downloaded["repo_id"], "unsloth/Qwen3.5-4B-GGUF")
        self.assertTrue(runtime.is_loaded("Qwen 3.5"))

        context = self.service.get_request_context()
        response = LocalResponder(runtime).respond(context, VIEWER, "hello", [])

        self.assertEqual(response, "Great question.")
        self.assertEqual(fake_llama.last_completion["max_tokens"], MAX_OUTPUT_TOKENS)
        self.assertEqual(fake_llama.last_completion["stream"], False)
        self.assertEqual(llama_arguments["n_ctx"], LOCAL_CONTEXT_TOKENS)

    def test_local_responder_includes_ambient_stream_chat_in_the_model_payload(self) -> None:
        fake_llama = FakeLlama()
        runtime = LocalModelRuntime(
            Path(self.temp_dir.name) / "models",
            downloader=lambda **_kwargs: "",
            llama_factory=lambda **_kwargs: fake_llama,
            gpu_support=lambda: False,
        )
        model_path = Path(self.temp_dir.name) / "loaded.gguf"
        model_path.write_bytes(b"fake gguf")
        runtime._load_model("Qwen 3.5", model_path)

        response = LocalResponder(runtime).respond(
            self.service.get_request_context(),
            VIEWER,
            "Which fruit is better?",
            [AmbientChatMessage(viewer="A", message="Bananas are weird")],
        )

        self.assertEqual(response, "Great question.")
        payload = fake_llama.last_completion["messages"]
        self.assertTrue(any("A: Bananas are weird" in message["content"] for message in payload))

    def test_background_model_download_does_not_block_runtime_status(self) -> None:
        download_started = threading.Event()
        allow_download = threading.Event()

        def downloader(**kwargs: Any) -> str:
            download_started.set()
            allow_download.wait(timeout=2)
            target = Path(kwargs["local_dir"]) / kwargs["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake gguf")
            return str(target)

        runtime = LocalModelRuntime(
            Path(self.temp_dir.name) / "models",
            downloader=downloader,
            llama_factory=lambda **_kwargs: FakeLlama(),
            gpu_support=lambda: False,
        )
        self.assertTrue(runtime.start_download_and_load("Qwen 3.5"))
        self.assertTrue(download_started.wait(timeout=1))

        started_at = time.monotonic()
        self.assertEqual(runtime.status_for("Qwen 3.5"), "Downloading model: Qwen 3.5")
        self.assertLess(time.monotonic() - started_at, 0.1)

        allow_download.set()
        deadline = time.monotonic() + 2
        while not runtime.is_loaded("Qwen 3.5") and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(runtime.is_loaded("Qwen 3.5"))

    def test_cloud_responder_uses_saved_secret_and_openai_compatible_payload(self) -> None:
        self.service.save_mode("Cloud")
        self.service.save_cloud_settings(
            "https://provider.example/v1", "secret-value", "chat-model"
        )
        request_context = self.service.get_request_context()
        sent: dict[str, Any] = {}

        def post(url: str, **kwargs: Any) -> FakeHttpResponse:
            sent["url"] = url
            sent.update(kwargs)
            return FakeHttpResponse()

        response = CloudResponder(self.secrets, post=post).respond(
            request_context, VIEWER, "hello", []
        )

        self.assertEqual(response, "Cloud answer.")
        self.assertEqual(sent["url"], "https://provider.example/v1/chat/completions")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer secret-value")
        self.assertEqual(sent["json"]["model"], "chat-model")
        self.assertEqual(sent["json"]["max_tokens"], MAX_OUTPUT_TOKENS)

    def test_reply_limit_reserves_room_under_youtube_chat_cap(self) -> None:
        from prompting import clean_reply

        reply = clean_reply("word " * 100)

        self.assertLessEqual(len(reply), MAX_REPLY_CHARACTERS)
        self.assertLess(MAX_REPLY_CHARACTERS, 300)
