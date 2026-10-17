import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.adapters.protocols import EmbeddingProvider, EmbeddingResult


class EmbeddingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingSettings:
    enabled: bool = False
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 10.0
    max_retries: int = 0
    bypass_proxy: bool = False

    @classmethod
    def from_env(cls) -> "EmbeddingSettings":
        return cls(
            enabled=_bool_from_env("RAG_EMBEDDING_ENABLED", False),
            provider=os.getenv("EMBEDDING_PROVIDER", "").strip(),
            base_url=os.getenv("EMBEDDING_BASE_URL", "").strip(),
            api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
            model=os.getenv("EMBEDDING_MODEL", "").strip(),
            timeout_seconds=_float_from_env("EMBEDDING_TIMEOUT_SECONDS", 10.0),
            max_retries=max(0, _int_from_env("EMBEDDING_MAX_RETRIES", 0)),
            bypass_proxy=_bool_from_env("EMBEDDING_BYPASS_PROXY", False),
        )

    def can_call_remote(self) -> bool:
        return (
            self.enabled
            and self.provider == "openai_compatible"
            and bool(self.base_url)
            and bool(self.api_key)
            and bool(self.model)
        )


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, settings: EmbeddingSettings) -> None:
        if not settings.can_call_remote():
            raise EmbeddingProviderError("Embedding provider is not fully configured.")
        self.settings = settings
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if settings.bypass_proxy else None

    def embed(self, text: str) -> EmbeddingResult:
        payload = {"model": self.settings.model, "input": text}
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            _embeddings_url(self.settings.base_url),
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                if self._opener is None:
                    response_context = urllib.request.urlopen(request, timeout=self.settings.timeout_seconds)
                else:
                    response_context = self._opener.open(request, timeout=self.settings.timeout_seconds)
                with response_context as response:
                    raw = response.read().decode("utf-8")
                vector = _extract_embedding(json.loads(raw))
                return EmbeddingResult(
                    vector=vector,
                    metadata={
                        "provider": self.settings.provider,
                        "model": self.settings.model,
                        "dimension": len(vector),
                        "attempt": attempt + 1,
                    },
                )
            except urllib.error.HTTPError as exc:
                last_error = EmbeddingProviderError(_http_error_summary(exc))
                if attempt < self.settings.max_retries:
                    time.sleep(0.2)
            except urllib.error.URLError as exc:
                last_error = EmbeddingProviderError(_url_error_summary(exc))
                if attempt < self.settings.max_retries:
                    time.sleep(0.2)
            except (TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                last_error = exc
                if attempt < self.settings.max_retries:
                    time.sleep(0.2)

        if isinstance(last_error, EmbeddingProviderError):
            raise last_error
        raise EmbeddingProviderError(f"Embedding provider request failed: {type(last_error).__name__}") from last_error


def build_embedding_provider(settings: EmbeddingSettings | None = None) -> EmbeddingProvider | None:
    resolved = settings or EmbeddingSettings.from_env()
    if resolved.provider != "openai_compatible" or not resolved.can_call_remote():
        return None
    return OpenAICompatibleEmbeddingProvider(resolved)


def _embeddings_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/embeddings"):
        return normalized
    return f"{normalized}/embeddings"


def _extract_embedding(payload: dict[str, Any]) -> list[float]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("Embedding response has no data.")
    embedding = data[0].get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("Embedding response has no embedding.")
    vector = [float(value) for value in embedding]
    if not vector:
        raise ValueError("Embedding response vector is empty.")
    return vector


def _http_error_summary(error: urllib.error.HTTPError) -> str:
    raw = ""
    try:
        raw = error.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    detail = _sanitize_error_body(raw)
    if detail:
        return f"Embedding provider request failed: HTTP {error.code}: {detail}"
    return f"Embedding provider request failed: HTTP {error.code}"


def _sanitize_error_body(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()[:240]
    error = parsed.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("type") or error)
        code = error.get("code")
        if code:
            message = f"{message} (code={code})"
        return message[:240]
    return str(parsed)[:240]


def _url_error_summary(error: urllib.error.URLError) -> str:
    reason = getattr(error, "reason", error)
    reason_text = str(reason) or type(reason).__name__
    return f"Embedding provider request failed: URLError: {reason_text[:240]}"


def _bool_from_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
