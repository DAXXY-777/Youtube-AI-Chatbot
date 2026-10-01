"""Curated GGUF downloads that will be offered by the local runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPreset:
    """One explicit Hugging Face GGUF file, not a general model repository."""

    label: str
    repository_id: str
    filename: str

    @property
    def hf_uri(self) -> str:
        return f"hf://{self.repository_id}/{self.filename}"


PRESET_MODELS = (
    ModelPreset(
        label="Qwen 3.5",
        repository_id="unsloth/Qwen3.5-4B-GGUF",
        filename="Qwen3.5-4B-Q4_K_M.gguf",
    ),
    ModelPreset(
        label="Gemma 3 4B",
        repository_id="unsloth/gemma-3-4b-it-GGUF",
        filename="gemma-3-4b-it-Q4_K_M.gguf",
    ),
)
