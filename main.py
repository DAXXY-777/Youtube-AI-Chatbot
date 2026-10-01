"""Compose the private desktop UI and the separately tunnelable Nightbot API."""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

import gradio as gr
import uvicorn
from fastapi import FastAPI

from api import build_router
from chat_service import chat_service
from frontend_gr import APP_TITLE, CSS, build_ui
from inference_control import local_inference_queue
from logging_config import configure_logging, get_logger, log_event
from runtime_service import RuntimeService, runtime_service


LOCAL_HOST = "127.0.0.1"
UI_PORT = int(os.environ.get("YT_LIVESTREAM_CHATBOT_UI_PORT", "7860"))
PUBLIC_API_PORT = int(os.environ.get("YT_LIVESTREAM_CHATBOT_API_PORT", "7861"))
UI_URL = f"http://{LOCAL_HOST}:{UI_PORT}"
PUBLIC_API_URL = f"http://{LOCAL_HOST}:{PUBLIC_API_PORT}"
logger = get_logger("servers")


class ServerStartError(RuntimeError):
    """Raised when a loopback listener cannot be opened for the desktop app."""


def _application_lifespan(service: RuntimeService):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        configure_logging()
        service.initialize()
        if service is runtime_service:
            chat_service.set_active_stream(service.get_settings().active_stream_url)
        try:
            yield
        finally:
            log_event(logger, "application_server_stopping")

    return lifespan


def create_ui_app(service: RuntimeService = runtime_service) -> FastAPI:
    """Build the private loopback-only Gradio application used by the desktop UI."""

    app = FastAPI(
        title=APP_TITLE,
        docs_url=None,
        redoc_url=None,
        lifespan=_application_lifespan(service),
    )
    app.include_router(build_router(service, include_nightbot=False))
    return gr.mount_gradio_app(app, build_ui(), path="/", css=CSS, footer_links=[])


def create_public_api_app(service: RuntimeService = runtime_service) -> FastAPI:
    """Build the narrow loopback API that a tunnel may safely expose.

    The private UI, Gradio endpoints, configuration controls, and activity route
    are deliberately absent from this application.
    """
    app = FastAPI(
        title=f"{APP_TITLE} Nightbot API",
        docs_url=None,
        redoc_url=None,
        lifespan=_application_lifespan(service),
    )
    app.include_router(build_router(service, include_private_activity=False))
    return app


class ServerGroup:
    """Own both local servers so the desktop window and terminal share one runtime."""

    def __init__(self, service: RuntimeService = runtime_service) -> None:
        self.service = service
        self._servers: list[uvicorn.Server] = []
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Start the private UI first, then the API that may be tunneled externally."""
        if self._servers:
            return
        try:
            self._start_server(create_ui_app(self.service), UI_PORT, "yt-ui-server")
            self._start_server(
                create_public_api_app(self.service), PUBLIC_API_PORT, "yt-api-server"
            )
        except ServerStartError:
            self.stop()
            raise
        log_event(
            logger,
            "server_group_started",
            ui_port=UI_PORT,
            public_api_port=PUBLIC_API_PORT,
        )

    def stop(self) -> None:
        """Ask both loopback servers to exit and release the local inference worker."""
        for server in self._servers:
            server.should_exit = True
        for thread in self._threads:
            thread.join(timeout=10)
        local_inference_queue.shutdown()
        if self.service is runtime_service:
            chat_service.memory.stop()
        self._servers.clear()
        self._threads.clear()
        log_event(logger, "server_group_stopped")

    def _start_server(self, app: FastAPI, port: int, thread_name: str) -> None:
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=LOCAL_HOST,
                port=port,
                log_level="info",
                access_log=False,
            )
        )
        thread = threading.Thread(target=server.run, name=thread_name, daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive():
                raise ServerStartError(f"Port {port} is unavailable.")
            if time.monotonic() >= deadline:
                server.should_exit = True
                raise ServerStartError(f"Timed out starting local port {port}.")
            time.sleep(0.05)
        self._servers.append(server)
        self._threads.append(thread)


def run_terminal_servers() -> None:
    """Run both services without a WebView for terminal and VPS-style use."""
    servers = ServerGroup()
    servers.start()
    print(f"Private UI: {UI_URL}")
    print(f"Nightbot API: {PUBLIC_API_URL}/api/nightbot/ai")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        servers.stop()


# Supports `uvicorn main:app` for local UI-only development.
app = create_ui_app()


if __name__ == "__main__":
    run_terminal_servers()
