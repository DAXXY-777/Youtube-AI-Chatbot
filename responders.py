"""The Local and OpenAI-compatible Cloud reply paths."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import BoundedSemaphore
from typing import Any

import httpx

from inference_control import (
    InferenceBusyError,
    InferenceTimeoutError,
    SingleWorkerInferenceQueue,
    local_inference_queue,
)
from logging_config import get_logger, log_event
from memory import AmbientChatMessage
from model_runtime import ModelRuntimeError, local_model_runtime
from network_safety import validate_cloud_base_url
from prompting import MAX_OUTPUT_TOKENS, build_chat_messages, clean_reply
from runtime_service import RequestContext, ViewerIdentity
from secret_store import SecretStore


MODEL_NOT_LOADED_RESPONSE = "Model not loaded."
CLOUD_NOT_CONFIGURED_RESPONSE = "Cloud provider not configured."
AI_UNAVAILABLE_RESPONSE = "AI is unavailable right now."
CLOUD_REQUEST_TIMEOUT_SECONDS = 15.0
CLOUD_REQUEST_CAPACITY = 4
logger = get_logger("responders")
cloud_request_slots = BoundedSemaphore(CLOUD_REQUEST_CAPACITY)


class LocalResponder:
    def __init__(
        self,
        model_runtime: Any = local_model_runtime,
        inference_queue: SingleWorkerInferenceQueue = local_inference_queue,
    ) -> None:
        self.model_runtime = model_runtime
        self.inference_queue = inference_queue

    def respond(
        self,
        context: RequestContext,
        viewer: ViewerIdentity,
        prompt: str,
        ambient_messages: Sequence[AmbientChatMessage] = (),
    ) -> str:
        try:
            if not self.model_runtime.is_loaded(context.local_preset_label):
                return MODEL_NOT_LOADED_RESPONSE
            messages = build_chat_messages(
                viewer=viewer.label,
                prompt=prompt,
                ambient_messages=ambient_messages,
            )
            reply = clean_reply(
                self.inference_queue.run(
                    lambda: self.model_runtime.generate(context.local_preset_label, messages)
                )
            )
        except InferenceBusyError:
            log_event(logger, "local_generation_rejected", reason="queue_full_or_expired")
            return AI_UNAVAILABLE_RESPONSE
        except InferenceTimeoutError:
            log_event(logger, "local_generation_timed_out")
            return AI_UNAVAILABLE_RESPONSE
        except Exception as error:
            log_event(logger, "local_generation_failed", error_type=type(error).__name__)
            return AI_UNAVAILABLE_RESPONSE
        return reply or AI_UNAVAILABLE_RESPONSE


class CloudResponder:
    def __init__(
        self,
        secret_store: SecretStore,
        *,
        post: Callable[..., httpx.Response] = httpx.post,
        request_slots: BoundedSemaphore = cloud_request_slots,
    ) -> None:
        self.secret_store = secret_store
        self._post = post
        self._request_slots = request_slots

    def respond(
        self,
        context: RequestContext,
        viewer: ViewerIdentity,
        prompt: str,
        ambient_messages: Sequence[AmbientChatMessage] = (),
    ) -> str:
        acquired_slot = False
        try:
            api_key = self.secret_store.get_cloud_api_key()
            if (
                not context.cloud_ready
                or not context.cloud_base_url
                or not context.cloud_model_id
                or not api_key
            ):
                return CLOUD_NOT_CONFIGURED_RESPONSE
            acquired_slot = self._request_slots.acquire(blocking=False)
            if not acquired_slot:
                log_event(logger, "cloud_request_rejected", reason="capacity")
                return AI_UNAVAILABLE_RESPONSE
            messages = build_chat_messages(
                viewer=viewer.label,
                prompt=prompt,
                ambient_messages=ambient_messages,
            )
            validate_cloud_base_url(context.cloud_base_url)
            response = self._post(
                f"{context.cloud_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": context.cloud_model_id,
                    "messages": messages,
                    "temperature": 0.5,
                    "max_tokens": MAX_OUTPUT_TOKENS,
                },
                timeout=CLOUD_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = _completion_content(response.json())
        except Exception as error:
            log_event(logger, "cloud_request_failed", error_type=type(error).__name__)
            return AI_UNAVAILABLE_RESPONSE
        finally:
            if acquired_slot:
                self._request_slots.release()
        return clean_reply(content) or AI_UNAVAILABLE_RESPONSE


def _completion_content(payload: Any) -> object:
    if not isinstance(payload, dict):
        raise ValueError("Cloud response was not an object.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Cloud response had no choices.")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("Cloud response choice was invalid.")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("Cloud response message was invalid.")
    return message.get("content")
