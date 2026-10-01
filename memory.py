"""Rolling, in-memory context collected from the selected public YouTube live chat."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, RLock, Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytchat
from pytchat.exceptions import InvalidVideoIdException

from logging_config import get_logger, log_event


AMBIENT_MEMORY_LIMIT = 85
AMBIENT_RETRY_SECONDS = 30
MAX_AMBIENT_VIEWER_CHARACTERS = 80
MAX_AMBIENT_MESSAGE_CHARACTERS = 180
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,}$")
logger = get_logger("ambient_memory")


@dataclass(frozen=True)
class AmbientChatMessage:
    """One normalized public viewer message retained only in process memory."""

    viewer: str
    message: str


class AmbientMemory:
    """Collect recent chat in a best-effort worker that reconnects after failures."""

    def __init__(
        self,
        *,
        chat_factory: Callable[..., Any] = pytchat.create,
        capacity: int = AMBIENT_MEMORY_LIMIT,
    ) -> None:
        if capacity < 1:
            raise ValueError("Ambient memory capacity must be at least one.")
        self._chat_factory = chat_factory
        self._capacity = capacity
        self._lock = RLock()
        self._messages: deque[AmbientChatMessage] = deque(maxlen=capacity)
        self._seen_ids: deque[str] = deque(maxlen=capacity * 4)
        self._seen_id_set: set[str] = set()
        self._stream_url: str | None = None
        self._video_id: str | None = None
        self._stop_event: Event | None = None
        self._worker: Thread | None = None
        self._generation = 0
        self._listener_status = "No stream selected"

    def set_active_stream(self, youtube_url: str | None, *, force: bool = False) -> None:
        """Attach to a stream, or deliberately restart its listener without losing safety."""
        normalized_url = (youtube_url or "").strip() or None
        video_id = extract_youtube_video_id(normalized_url) if normalized_url else None

        with self._lock:
            unchanged = normalized_url == self._stream_url and video_id == self._video_id
            worker_alive = self._worker is not None and self._worker.is_alive()
            if unchanged and worker_alive and not force:
                return

            previous_stop_event = self._stop_event
            if previous_stop_event is not None:
                previous_stop_event.set()

            self._generation += 1
            generation = self._generation
            self._stream_url = normalized_url
            self._video_id = video_id
            self._messages.clear()
            self._seen_ids.clear()
            self._seen_id_set.clear()
            self._stop_event = None
            self._worker = None

            if video_id is None:
                self._listener_status = "No stream selected"
                log_event(logger, "ambient_memory_cleared", stream_configured=bool(normalized_url))
                return

            stop_event = Event()
            worker = Thread(
                target=self._collect,
                args=(video_id, generation, stop_event),
                name="youtube-ambient-memory",
                daemon=True,
            )
            self._stop_event = stop_event
            self._worker = worker
            self._listener_status = "Listening"

        log_event(logger, "ambient_memory_listener_started")
        worker.start()

    def snapshot(self, youtube_url: str | None) -> list[AmbientChatMessage]:
        """Return immediately; collecting chat must never delay an AI request."""
        if youtube_url is not None:
            self.set_active_stream(youtube_url)
        with self._lock:
            return list(self._messages)

    def listener_status(self) -> str:
        with self._lock:
            return self._listener_status

    def stop(self) -> None:
        """Stop collection during application shutdown without waiting on network I/O."""
        with self._lock:
            self._generation += 1
            if self._stop_event is not None:
                self._stop_event.set()
            self._stream_url = None
            self._video_id = None
            self._stop_event = None
            self._worker = None
            self._listener_status = "No stream selected"

    def ingest(
        self, viewer: str, message: str, *, message_id: str | None = None
    ) -> bool:
        """Add one eligible chat message and return whether it entered the rolling buffer."""
        normalized_viewer = _shorten(viewer, MAX_AMBIENT_VIEWER_CHARACTERS)
        normalized_message = _shorten(message, MAX_AMBIENT_MESSAGE_CHARACTERS)
        if not normalized_viewer or not normalized_message:
            return False
        if normalized_message.casefold().startswith("!ai"):
            return False

        dedupe_key = message_id or f"{normalized_viewer}\n{normalized_message}"
        with self._lock:
            if dedupe_key in self._seen_id_set:
                return False
            if len(self._seen_ids) == self._seen_ids.maxlen:
                expired_key = self._seen_ids.popleft()
                self._seen_id_set.discard(expired_key)
            self._seen_ids.append(dedupe_key)
            self._seen_id_set.add(dedupe_key)
            self._messages.append(
                AmbientChatMessage(viewer=normalized_viewer, message=normalized_message)
            )
        return True

    def _collect(self, video_id: str, generation: int, stop_event: Event) -> None:
        while self._is_current(generation, stop_event):
            chat: Any | None = None
            failed = False
            try:
                # This collector runs in a worker thread. pytchat's default
                # signal registration is only valid in Python's main thread.
                chat = self._chat_factory(video_id=video_id, interruptable=False)
                while self._is_current(generation, stop_event) and chat.is_alive():
                    data = chat.get()
                    sync_items = getattr(data, "sync_items", None)
                    if not callable(sync_items):
                        continue
                    for item in sync_items():
                        if not self._is_current(generation, stop_event):
                            return
                        self._ingest_pytchat_item(item)
            except InvalidVideoIdException:
                with self._lock:
                    if self._is_current(generation, stop_event):
                        self._listener_status = "Unavailable for this stream"
                log_event(logger, "ambient_memory_listener_unavailable")
                return
            except Exception as error:
                failed = True
                log_event(
                    logger,
                    "ambient_memory_listener_failed",
                    error_type=type(error).__name__,
                )
            finally:
                close = getattr(chat, "terminate", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

            if not self._is_current(generation, stop_event):
                return
            with self._lock:
                if self._is_current(generation, stop_event):
                    self._listener_status = "Reconnecting"
            log_event(
                logger,
                "ambient_memory_listener_reconnecting",
                reason="failure" if failed else "chat_ended",
            )
            if stop_event.wait(AMBIENT_RETRY_SECONDS):
                return

    def _ingest_pytchat_item(self, item: object) -> None:
        if getattr(item, "type", None) != "textMessage":
            return
        author = getattr(item, "author", None)
        viewer = getattr(author, "name", "")
        message = getattr(item, "message", "")
        identifier = getattr(item, "id", None)
        self.ingest(
            str(viewer) if viewer is not None else "",
            str(message) if message is not None else "",
            message_id=str(identifier) if identifier else None,
        )

    def _is_current(self, generation: int, stop_event: Event) -> bool:
        with self._lock:
            return (
                generation == self._generation
                and self._stop_event is stop_event
                and not stop_event.is_set()
            )


def extract_youtube_video_id(youtube_url: str | None) -> str | None:
    """Read a video identifier from the one public watch URL format the UI accepts."""
    if not youtube_url:
        return None
    parsed = urlparse(youtube_url)
    if parsed.scheme != "https" or parsed.hostname != "www.youtube.com":
        return None
    if parsed.path != "/watch":
        return None
    candidate = parse_qs(parsed.query).get("v", [None])[0]
    if candidate and YOUTUBE_VIDEO_ID_PATTERN.fullmatch(candidate):
        return candidate
    return None


def _shorten(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit - 3].rstrip()}..."


ambient_memory = AmbientMemory()
