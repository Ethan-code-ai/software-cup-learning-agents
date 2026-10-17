import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from app.adapters.embedding_provider import (
    EmbeddingProviderError,
    EmbeddingSettings,
    OpenAICompatibleEmbeddingProvider,
    build_embedding_provider,
)


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class EmbeddingProviderTests(unittest.TestCase):
    def test_unconfigured_embedding_provider_returns_none(self) -> None:
        self.assertIsNone(build_embedding_provider(EmbeddingSettings()))

    def test_provider_uses_openai_compatible_embedding_contract(self) -> None:
        settings = EmbeddingSettings(
            enabled=True,
            provider="openai_compatible",
            base_url="https://example.test/v1",
            api_key="secret-key",
            model="text-embedding-test",
        )
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.headers.get("Authorization")
            return _FakeHttpResponse({"data": [{"embedding": [0.1, 0.2, 0.3]}]})

        with patch("urllib.request.urlopen", fake_urlopen):
            result = OpenAICompatibleEmbeddingProvider(settings).embed("BFS shortest path")

        self.assertEqual(captured["url"], "https://example.test/v1/embeddings")
        self.assertEqual(captured["timeout"], 10.0)
        self.assertEqual(captured["body"]["model"], "text-embedding-test")
        self.assertEqual(captured["body"]["input"], "BFS shortest path")
        self.assertEqual(captured["authorization"], "Bearer secret-key")
        self.assertEqual(result.vector, [0.1, 0.2, 0.3])
        self.assertEqual(result.metadata["dimension"], 3)

    def test_provider_error_summary_does_not_leak_api_key(self) -> None:
        settings = EmbeddingSettings(
            enabled=True,
            provider="openai_compatible",
            base_url="https://example.test/v1",
            api_key="secret-key",
            model="text-embedding-test",
        )

        def fake_urlopen(request, timeout):
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=io.BytesIO(b'{"error":{"message":"invalid key","code":"invalid_api_key"}}'),
            )

        with patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(EmbeddingProviderError) as context:
                OpenAICompatibleEmbeddingProvider(settings).embed("BFS")

        self.assertIn("HTTP 401", str(context.exception))
        self.assertIn("invalid_api_key", str(context.exception))
        self.assertNotIn("secret-key", str(context.exception))


if __name__ == "__main__":
    unittest.main()
