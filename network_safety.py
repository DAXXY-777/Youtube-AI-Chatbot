"""Validation for user-configured OpenAI-compatible Cloud base URLs."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse


LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}


def validate_cloud_base_url(raw_url: str) -> str:
    """Allow HTTPS providers and explicit local/LAN HTTP OpenAI-compatible servers."""
    value = raw_url.strip().rstrip("/")
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if not hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("Cloud API URL must be a complete http(s) URL.")

    is_local_or_lan = (
        hostname in LOCAL_HOSTNAMES
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
        or (_is_ip_address(hostname) and not _is_public_ip(hostname))
    )
    if parsed.scheme == "http" and not is_local_or_lan:
        raise ValueError("Public Cloud API URLs must use HTTPS.")
    return value


def _is_ip_address(hostname: str) -> bool:
    try:
        ip_address(hostname)
    except ValueError:
        return False
    return True


def _is_public_ip(hostname: str) -> bool:
    try:
        return ip_address(hostname).is_global
    except ValueError:
        return False
