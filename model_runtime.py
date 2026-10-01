"""Download and in-process lifecycle management for curated local GGUF models."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import RLock, Thread
from typing import Any

from huggingface_hub import hf_hub_download

from app_paths import MODELS_DIRECTORY
from logging_config import get_logger, log_event
from model_presets import PRESET_MODELS, ModelPreset
from prompting import MAX_OUTPUT_TOKENS


logger = get_logger("model_runtime")
LOCAL_CONTEXT_TOKENS = 8_192


class ModelRuntimeError(RuntimeError):
    pass


class LocalModelRuntime:
    """Keep one loaded GGUF while downloads and replacements happen in the background."""

    def __init__(
        self,
        models_directory: Path = MODELS_DIRECTORY,
        *,
        downloader: Callable[..., str] = hf_hub_download,
        llama_factory: Callable[..., Any] | None = None,
        gpu_support: Callable[[], bool] | None = None,
    ) -> None:
        self.models_directory = models_directory
        self._downloader = downloader
        self._llama_factory = llama_factory
        self._gpu_support = gpu_support
        self._lock = RLock()
        self._generation_lock = RLock()
        self._model: Any | None = None
        self._loaded_preset_label: str | None = None
        self._loaded_path: Path | None = None
        self._operation_state = "idle"
        self._operation_label: str | None = None
        self._failed_label: str | None = None

    def start_download_and_load(self, preset_label: str) -> bool:
        """Start an operation without tying up the Gradio request or Nightbot checks."""
        self._find_preset(preset_label)
        with self._lock:
            if self._operation_state != "idle":
                return False
            if self._loaded_preset_label == preset_label and self._model is not None:
                return False
            self._begin_operation(preset_label)
            worker = Thread(
                target=self._run_background_operation,
                args=(preset_label,),
                name="local-model-loader",
                daemon=True,
            )
        worker.start()
        return True

    def download_and_load(self, preset_label: str) -> Path:
        """Synchronously download and load a preset for direct callers and tests."""
        preset = self._find_preset(preset_label)
        with self._lock:
            if self._operation_state != "idle":
                raise ModelRuntimeError("Another model operation is already running.")
            self._begin_operation(preset_label)
        try:
            model_path = self._download_and_load(preset)
        except ModelRuntimeError as error:
            self._finish_operation_failure(preset_label)
            raise
        else:
            self._finish_operation_success(preset_label)
            return model_path

    def is_loaded(self, preset_label: str) -> bool:
        with self._lock:
            return self._model is not None and self._loaded_preset_label == preset_label

    def loaded_label(self) -> str | None:
        with self._lock:
            return self._loaded_preset_label

    def status_for(self, preset_label: str) -> str:
        """Return a compact state suitable for the one visible Status field."""
        with self._lock:
            if self._operation_label == preset_label:
                if self._operation_state == "downloading":
                    return f"Downloading model: {preset_label}"
                if self._operation_state == "loading":
                    return f"Loading model: {preset_label}"
            if self._model is not None and self._loaded_preset_label == preset_label:
                return f"Model loaded: {preset_label}"
            if self._failed_label == preset_label:
                if self._loaded_preset_label:
                    return f"Model failed; {self._loaded_preset_label} restored."
                return "Model failed to load."
            return "No model loaded"

    def generate(self, preset_label: str, messages: list[dict[str, str]]) -> str:
        """Generate while preventing the loader from closing the active model mid-reply."""
        with self._generation_lock:
            with self._lock:
                if self._model is None or self._loaded_preset_label != preset_label:
                    raise ModelRuntimeError("The selected model is not loaded.")
                model = self._model
            try:
                completion = model.create_chat_completion(
                    messages=messages,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    temperature=0.5,
                    top_p=0.9,
                    stream=False,
                )
                choices = completion.get("choices", [])
                message = choices[0].get("message", {}) if choices else {}
                content = message.get("content") if isinstance(message, dict) else None
            except Exception as error:
                raise ModelRuntimeError("The local model could not generate a reply.") from error

            if not isinstance(content, str) or not content.strip():
                raise ModelRuntimeError("The local model returned an empty reply.")
            return content

    def _load_model(self, preset_label: str, model_path: Path) -> None:
        """Synchronous helper retained for focused runtime tests and recovery code."""
        self._replace_loaded_model(preset_label, model_path)

    def _run_background_operation(self, preset_label: str) -> None:
        try:
            preset = self._find_preset(preset_label)
            self._download_and_load(preset)
        except Exception as error:
            log_event(
                logger,
                "model_operation_failed",
                preset=preset_label,
                error_type=type(error).__name__,
            )
            self._finish_operation_failure(preset_label)
        else:
            self._finish_operation_success(preset_label)

    def _download_and_load(self, preset: ModelPreset) -> Path:
        destination = self._destination_for(preset)
        model_path = destination / preset.filename
        try:
            if not model_path.is_file():
                destination.mkdir(parents=True, exist_ok=True)
                log_event(logger, "model_download_started", preset=preset.label)
                model_path = Path(
                    self._downloader(
                        repo_id=preset.repository_id,
                        filename=preset.filename,
                        local_dir=destination,
                    )
                )
                log_event(logger, "model_download_completed", preset=preset.label)
        except Exception as error:
            log_event(
                logger,
                "model_download_failed",
                preset=preset.label,
                error_type=type(error).__name__,
            )
            raise ModelRuntimeError("Could not download the selected GGUF model.") from error

        with self._lock:
            self._operation_state = "loading"
        self._replace_loaded_model(preset.label, model_path)
        return model_path

    def _replace_loaded_model(self, preset_label: str, model_path: Path) -> None:
        with self._generation_lock:
            with self._lock:
                if (
                    self._model is not None
                    and self._loaded_preset_label == preset_label
                    and self._loaded_path == model_path
                ):
                    return
                previous_label = self._loaded_preset_label
                previous_path = self._loaded_path
                previous_model = self._model
                self._model = None
                self._loaded_preset_label = None
                self._loaded_path = None

            self._close_model(previous_model)
            try:
                model, gpu_offload = self._create_model(model_path)
            except ModelRuntimeError as load_error:
                if self._restore_previous_model(previous_label, previous_path):
                    raise ModelRuntimeError("The selected GGUF model could not be loaded.") from load_error
                raise

            with self._lock:
                self._model = model
                self._loaded_preset_label = preset_label
                self._loaded_path = model_path
            log_event(logger, "model_loaded", preset=preset_label, gpu_offload=gpu_offload)

    def _restore_previous_model(self, label: str | None, model_path: Path | None) -> bool:
        if not label or model_path is None or not model_path.is_file():
            return False
        try:
            model, gpu_offload = self._create_model(model_path)
        except ModelRuntimeError:
            log_event(logger, "previous_model_restore_failed", preset=label)
            return False
        with self._lock:
            self._model = model
            self._loaded_preset_label = label
            self._loaded_path = model_path
        log_event(logger, "previous_model_restored", preset=label, gpu_offload=gpu_offload)
        return True

    def _create_model(self, model_path: Path) -> tuple[Any, bool]:
        try:
            llama_factory = self._llama_factory or _default_llama_factory
            gpu_offload = self._supports_gpu_offload()
            model = llama_factory(
                model_path=str(model_path),
                n_ctx=LOCAL_CONTEXT_TOKENS,
                n_gpu_layers=-1 if gpu_offload else 0,
                verbose=False,
            )
        except Exception as error:
            log_event(logger, "model_load_failed", error_type=type(error).__name__)
            raise ModelRuntimeError("The selected GGUF model could not be loaded.") from error
        return model, gpu_offload

    def _begin_operation(self, preset_label: str) -> None:
        self._operation_state = "downloading"
        self._operation_label = preset_label
        self._failed_label = None

    def _finish_operation_success(self, preset_label: str) -> None:
        with self._lock:
            self._operation_state = "idle"
            self._operation_label = None
            self._failed_label = None
        log_event(logger, "model_operation_completed", preset=preset_label)

    def _finish_operation_failure(self, preset_label: str) -> None:
        with self._lock:
            self._operation_state = "idle"
            self._operation_label = None
            self._failed_label = preset_label
        log_event(logger, "model_operation_failed", preset=preset_label)

    @staticmethod
    def _close_model(model: Any | None) -> None:
        close = getattr(model, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _supports_gpu_offload(self) -> bool:
        if self._gpu_support is not None:
            return self._gpu_support()
        from llama_cpp import llama_supports_gpu_offload

        return bool(llama_supports_gpu_offload())

    @staticmethod
    def _find_preset(preset_label: str) -> ModelPreset:
        for preset in PRESET_MODELS:
            if preset.label == preset_label:
                return preset
        raise ModelRuntimeError("Choose one of the listed local model presets.")

    def _destination_for(self, preset: ModelPreset) -> Path:
        safe_name = preset.repository_id.replace("/", "--")
        return self.models_directory / safe_name


def _default_llama_factory(**kwargs: Any) -> Any:
    from llama_cpp import Llama

    return Llama(**kwargs)


local_model_runtime = LocalModelRuntime()
