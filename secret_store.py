"""Secret-store adapters. Cloud API keys never enter the SQLite database."""

from __future__ import annotations

from typing import Protocol

import keyring


class SecretStore(Protocol):
    def get_cloud_api_key(self) -> str | None: ...

    def set_cloud_api_key(self, value: str) -> None: ...

    def clear_cloud_api_key(self) -> None: ...


class WindowsCredentialStore:
    """Uses Keyring's Windows Credential Manager backend on this application host."""

    service_name = "YT Livestream Chatbot"
    account_name = "cloud-api-key"

    def get_cloud_api_key(self) -> str | None:
        return keyring.get_password(self.service_name, self.account_name)

    def set_cloud_api_key(self, value: str) -> None:
        keyring.set_password(self.service_name, self.account_name, value)

    def clear_cloud_api_key(self) -> None:
        try:
            keyring.delete_password(self.service_name, self.account_name)
        except keyring.errors.PasswordDeleteError:
            pass


class MemorySecretStore:
    """Small test adapter that keeps credentials out of test databases too."""

    def __init__(self) -> None:
        self.value: str | None = None

    def get_cloud_api_key(self) -> str | None:
        return self.value

    def set_cloud_api_key(self, value: str) -> None:
        self.value = value

    def clear_cloud_api_key(self) -> None:
        self.value = None
