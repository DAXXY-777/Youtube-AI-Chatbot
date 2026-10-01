"""Windows desktop launcher: start local services, then host Gradio in WebView2."""

from __future__ import annotations

import os
import ctypes

import webview

from frontend_gr import APP_TITLE
from instance_guard import SingleInstanceGuard
from main import ServerGroup, ServerStartError, UI_URL, run_terminal_servers


def _show_error(message: str) -> None:
    """Show a useful message in the windowed executable, with a terminal fallback."""
    try:
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
    except Exception:
        print(f"{APP_TITLE}: {message}")


def main() -> None:
    """Open the private local UI after both loopback services are available."""
    if os.environ.get("YT_LIVESTREAM_CHATBOT_HEADLESS") == "1":
        run_terminal_servers()
        return

    instance_guard = SingleInstanceGuard()
    if not instance_guard.acquire():
        _show_error("YT Livestream Chatbot is already running.")
        return

    servers = ServerGroup()
    try:
        try:
            servers.start()
        except ServerStartError as error:
            _show_error(str(error))
            return
        webview.create_window(
            APP_TITLE,
            UI_URL,
            width=1360,
            height=900,
            min_size=(960, 640),
        )
        webview.start(gui="edgechromium")
    finally:
        servers.stop()
        instance_guard.release()


if __name__ == "__main__":
    main()
