"""Small Windows mutex wrapper used by the packaged desktop launcher."""

from __future__ import annotations

import ctypes
import sys


ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\YT_Livestream_Chatbot_8D113D2C_1DE5_48B8_8D4B_2C5694CE0316"


class SingleInstanceGuard:
    """Keep accidental second desktop launches from fighting for the same ports."""

    def __init__(self) -> None:
        self._handle: int | None = None
        self.already_running = False

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not handle:
            return True
        self._handle = int(handle)
        self.already_running = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
        return not self.already_running

    def release(self) -> None:
        if self._handle is None or sys.platform != "win32":
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.ReleaseMutex(self._handle)
        kernel32.CloseHandle(self._handle)
        self._handle = None

