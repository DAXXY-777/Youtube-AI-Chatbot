"""Stable writable paths for source runs and PyInstaller one-folder releases."""

from __future__ import annotations

import sys
from pathlib import Path


def application_directory() -> Path:
    """Return the folder selected by the installer when the app is frozen.

    PyInstaller stores Python modules beneath its internal runtime directory, so
    module ``__file__`` paths are not suitable for user data in a packaged app.
    ``sys.executable`` remains the desktop executable selected by the user.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APPLICATION_DIRECTORY = application_directory()
DATA_DIRECTORY = APPLICATION_DIRECTORY / "data"
MODELS_DIRECTORY = APPLICATION_DIRECTORY / "models"
LOGS_DIRECTORY = APPLICATION_DIRECTORY / "logs"
