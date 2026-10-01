"""One responder selection path shared by Nightbot and the Gradio test control."""

from __future__ import annotations

from memory import AmbientMemory, ambient_memory
from responders import CloudResponder, LocalResponder
from runtime_service import CLOUD_MODE, RequestContext, RuntimeService, ViewerIdentity, runtime_service


class ChatService:
    def __init__(
        self, service: RuntimeService, memory: AmbientMemory = ambient_memory
    ) -> None:
        self.service = service
        self.memory = memory
        self.local_responder = LocalResponder()
        self.cloud_responder = CloudResponder(service.secret_store)

    def set_active_stream(self, youtube_url: str | None, *, force: bool = False) -> None:
        """Route the persisted YouTube selection to the in-memory listener."""
        self.memory.set_active_stream(youtube_url, force=force)

    def respond(
        self, request_context: RequestContext, viewer: ViewerIdentity, prompt: str
    ) -> str:
        ambient_messages = self.memory.snapshot(request_context.stream_url)
        responder = (
            self.cloud_responder
            if request_context.mode == CLOUD_MODE
            else self.local_responder
        )
        return responder.respond(request_context, viewer, prompt, ambient_messages)


chat_service = ChatService(runtime_service)
