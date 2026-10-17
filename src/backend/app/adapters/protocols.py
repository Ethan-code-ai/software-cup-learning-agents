from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMResult:
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorSearchResult:
    content: str
    score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ImageGenerationResult:
    image_url: str | None
    image_bytes: bytes | None
    mime_type: str
    metadata: dict[str, Any]


class LLMProvider(Protocol):
    def generate(
        self,
        messages: list[dict[str, str]],
        response_schema: type[Any] | None = None,
    ) -> LLMResult:
        raise NotImplementedError


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> EmbeddingResult:
        raise NotImplementedError


class VectorStore(Protocol):
    def search(
        self,
        collection: str,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError


class ImageGenerationProvider(Protocol):
    def generate_image(
        self,
        prompt: str,
        visual_spec: dict[str, Any],
        size: str = "1024x1024",
    ) -> ImageGenerationResult:
        raise NotImplementedError


class TaskQueue(Protocol):
    def enqueue(self, task_type: str, payload: dict[str, Any]) -> str:
        raise NotImplementedError


class DocumentParser(Protocol):
    def parse(self, source_ref: str) -> list[str]:
        raise NotImplementedError
