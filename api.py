"""The narrow HTTP surface used by Nightbot and a future standalone frontend."""

from __future__ import annotations

import os
import secrets
from dataclasses import asdict
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

from chat_service import ChatService
from logging_config import get_logger, log_event
from responders import AI_UNAVAILABLE_RESPONSE
from runtime_service import RuntimeService, ViewerIdentity, runtime_service


ASK_A_QUESTION_RESPONSE = "Ask me a question."
COOLDOWN_RESPONSE = "Please wait before asking again."
NOT_FOUND_RESPONSE = "Not found"
NO_STORE_HEADERS = {"Cache-Control": "no-store"}
logger = get_logger("api")


def viewer_from_header(nightbot_user: str | None) -> ViewerIdentity | None:
    """Parse Nightbot's documented ampersand-separated user header."""
    user = _header_values(nightbot_user)
    if user is None:
        return None
    provider = user.get("provider")
    provider_id = user.get("providerId")
    if not provider or not provider_id:
        return None
    return ViewerIdentity(
        identity_key=f"{provider}:{provider_id}",
        provider=provider,
        provider_id=provider_id,
        username=user.get("name"),
        display_name=user.get("displayName"),
        user_level=user.get("userLevel"),
    )


def viewer_from_command(
    viewer_id: str | None, viewer_name: str | None
) -> ViewerIdentity | None:
    """Build a fallback identity from explicitly supplied Nightbot variables."""
    normalized_id = _command_value(viewer_id, maximum_length=128)
    if normalized_id is None:
        return None

    normalized_name = _command_value(viewer_name, maximum_length=128)
    return ViewerIdentity(
        identity_key=f"nightbot-command:{normalized_id}",
        provider="nightbot-command",
        provider_id=normalized_id,
        username=normalized_name,
        display_name=normalized_name,
        user_level=None,
    )


def build_router(
    service: RuntimeService,
    *,
    include_nightbot: bool = True,
    include_private_activity: bool = True,
) -> APIRouter:
    """Build the Nightbot route and the optional protected local activity route."""
    router = APIRouter()
    chat_service = ChatService(service)

    @router.get("/health")
    def health() -> dict[str, str]:
        context = service.get_request_context()
        return {
            "status": "ok",
            "mode": context.mode,
            "runtime": service.runtime_status().lower().replace(" ", "_"),
        }

    if include_nightbot:

        @router.get("/api/nightbot/ai", response_class=PlainTextResponse)
        def nightbot_ai(
            query: Annotated[str | None, Query(max_length=1_500)] = None,
            nightbot_user: Annotated[str | None, Header(alias="Nightbot-User")] = None,
            viewer_id: Annotated[str | None, Query(max_length=128)] = None,
            viewer_name: Annotated[str | None, Query(max_length=128)] = None,
        ) -> PlainTextResponse:
            """Accept one viewer-run URLFetch prompt and return a small, no-cache reply."""
            viewer = viewer_from_header(nightbot_user)
            identity_source = "header"
            if viewer is None:
                viewer = viewer_from_command(viewer_id, viewer_name)
                identity_source = "command_fallback"
            if viewer is None:
                log_event(logger, "nightbot_request_rejected", reason="missing_viewer_identity")
                return PlainTextResponse(
                    NOT_FOUND_RESPONSE, status_code=404, headers=NO_STORE_HEADERS
                )

            prompt = (query or "").strip()
            if not prompt:
                return PlainTextResponse(ASK_A_QUESTION_RESPONSE, headers=NO_STORE_HEADERS)

            try:
                if not service.claim_viewer_cooldown(viewer):
                    return PlainTextResponse(COOLDOWN_RESPONSE, headers=NO_STORE_HEADERS)
                request_context = service.get_request_context()
                response = chat_service.respond(request_context, viewer, prompt)
            except Exception as error:
                log_event(logger, "nightbot_request_failed", error_type=type(error).__name__)
                return PlainTextResponse(AI_UNAVAILABLE_RESPONSE, headers=NO_STORE_HEADERS)

            try:
                request_id = service.record_request(
                    request_context=request_context,
                    viewer_identity=viewer,
                    prompt=prompt,
                    response=response,
                )
            except Exception as error:
                log_event(logger, "activity_record_failed", error_type=type(error).__name__)
                request_id = None
            log_event(
                logger,
                "nightbot_request_completed",
                request_id=request_id,
                identity_source=identity_source,
                mode=request_context.mode,
                stream_context_id=request_context.stream_context_id,
                response_characters=len(response),
            )
            return PlainTextResponse(response, headers=NO_STORE_HEADERS)

    if include_private_activity:

        @router.get("/api/activity")
        def activity(
            activity_token: Annotated[
                str | None, Header(alias="X-Activity-Token")
            ] = None,
        ) -> dict[str, object]:
            """Return local history only when an explicit private token is configured."""
            configured_token = os.environ.get("NIGHTBOT_ACTIVITY_TOKEN")
            if not configured_token or not activity_token or not secrets.compare_digest(
                activity_token, configured_token
            ):
                log_event(logger, "activity_request_denied")
                raise HTTPException(status_code=404, detail="Not found")
            stream, entries = service.list_activity()
            return {"stream": stream, "messages": [asdict(entry) for entry in entries]}

    return router


def _header_values(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    try:
        pairs = parse_qsl(value, keep_blank_values=False, strict_parsing=True)
    except ValueError:
        return None
    if not pairs:
        return None
    values: dict[str, str] = {}
    for key, item in pairs:
        normalized_key = key.strip()
        normalized_item = item.strip()
        if not normalized_key or not normalized_item or normalized_key in values:
            return None
        values[normalized_key] = normalized_item
    return values


def _command_value(value: str | None, *, maximum_length: int) -> str | None:
    """Normalize short query values without accepting control characters."""
    if not value:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > maximum_length:
        return None
    if any(character.isspace() and character not in {" ", "\t"} for character in normalized):
        return None
    return normalized


router = build_router(runtime_service)
