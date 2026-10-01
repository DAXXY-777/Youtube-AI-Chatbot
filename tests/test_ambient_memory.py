from __future__ import annotations

import unittest

from memory import AmbientMemory, extract_youtube_video_id
from prompting import (
    MAX_AMBIENT_CONTEXT_CHARACTERS,
    MAX_AMBIENT_MESSAGES,
    AmbientChatMessage,
    build_chat_messages,
)
from pytchat.exceptions import InvalidVideoIdException


class AmbientMemoryTests(unittest.TestCase):
    def test_background_collector_ingests_documented_text_message_shape(self) -> None:
        class Author:
            name = "Viewer A"

        class Item:
            type = "textMessage"
            id = "message-1"
            author = Author()
            message = "Bananas are weird"

        class Batch:
            def sync_items(self):
                return [Item()]

        class Chat:
            def __init__(self) -> None:
                self.alive = True

            def is_alive(self) -> bool:
                return self.alive

            def get(self) -> Batch:
                self.alive = False
                return Batch()

            def terminate(self) -> None:
                return None

        create_arguments: dict[str, object] = {}

        def create_chat(**kwargs: object) -> Chat:
            create_arguments.update(kwargs)
            return Chat()

        memory = AmbientMemory(chat_factory=create_chat)
        memory.set_active_stream("https://www.youtube.com/watch?v=abc_DEF-123")
        worker = memory._worker
        self.assertIsNotNone(worker)
        worker.join(timeout=1)

        self.assertEqual(
            [
                (message.viewer, message.message)
                for message in memory.snapshot(
                    "https://www.youtube.com/watch?v=abc_DEF-123"
                )
            ],
            [("Viewer A", "Bananas are weird")],
        )
        self.assertEqual(create_arguments["interruptable"], False)
        memory.stop()

    def test_invalid_video_stops_retrying_and_reports_unavailable(self) -> None:
        def unavailable_chat(**_kwargs: object):
            raise InvalidVideoIdException("No channel information")

        memory = AmbientMemory(chat_factory=unavailable_chat)
        memory.set_active_stream("https://www.youtube.com/watch?v=abc_DEF-123")
        worker = memory._worker
        self.assertIsNotNone(worker)
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(memory.listener_status(), "Unavailable for this stream")
        memory.stop()

    def test_retains_the_latest_messages_and_ignores_ai_commands(self) -> None:
        memory = AmbientMemory(capacity=3)

        self.assertTrue(memory.ingest("A", "first", message_id="1"))
        self.assertTrue(memory.ingest("B", "second", message_id="2"))
        self.assertFalse(memory.ingest("Command", "!AI duplicate me", message_id="3"))
        self.assertTrue(memory.ingest("C", "third", message_id="4"))
        self.assertTrue(memory.ingest("D", "fourth", message_id="5"))
        self.assertFalse(memory.ingest("D", "fourth", message_id="5"))

        self.assertEqual(
            [(message.viewer, message.message) for message in memory.snapshot(None)],
            [("B", "second"), ("C", "third"), ("D", "fourth")],
        )

    def test_extracts_only_the_supported_watch_url(self) -> None:
        self.assertEqual(
            extract_youtube_video_id("https://www.youtube.com/watch?v=abc_DEF-123"),
            "abc_DEF-123",
        )
        self.assertIsNone(extract_youtube_video_id("https://youtu.be/abc_DEF-123?t=8"))
        self.assertIsNone(extract_youtube_video_id("https://www.youtube.com/live/abc_DEF-123"))
        self.assertIsNone(extract_youtube_video_id("https://example.com/watch?v=abc_DEF-123"))

    def test_prompt_keeps_ambient_chat_as_untrusted_background_context(self) -> None:
        messages = build_chat_messages(
            viewer="D",
            prompt="Which fruit is best?",
            ambient_messages=[
                AmbientChatMessage(viewer="A", message="Bananas are weird"),
                AmbientChatMessage(viewer="B", message="Apples are better"),
            ],
        )

        ambient_message = messages[1]
        self.assertEqual(ambient_message["role"], "user")
        self.assertIn("background context only", ambient_message["content"])
        self.assertIn("A: Bananas are weird", ambient_message["content"])
        self.assertIn("B: Apples are better", ambient_message["content"])
        self.assertIn("Current viewer D says", messages[-1]["content"])

    def test_prompt_uses_the_latest_eighty_five_messages_within_its_budget(self) -> None:
        ambient_messages = [
            AmbientChatMessage(viewer=f"Viewer {index}", message=f"message {index}")
            for index in range(86)
        ]

        messages = build_chat_messages(
            viewer="D", prompt="What did chat say?", ambient_messages=ambient_messages
        )

        transcript = messages[1]["content"]
        self.assertNotIn("Viewer 0: message 0", transcript)
        self.assertIn("Viewer 1: message 1", transcript)
        self.assertIn("Viewer 85: message 85", transcript)
        self.assertLessEqual(len(transcript), MAX_AMBIENT_CONTEXT_CHARACTERS + 100)
        self.assertEqual(MAX_AMBIENT_MESSAGES, 85)
