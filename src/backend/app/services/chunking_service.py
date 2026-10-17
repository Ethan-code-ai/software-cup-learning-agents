import os
from dataclasses import dataclass


DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 80


@dataclass(frozen=True)
class TextChunk:
    content: str
    char_start: int
    char_end: int


class ChunkingService:
    def __init__(self, chunk_size: int | None = None, chunk_overlap: int | None = None) -> None:
        self.chunk_size = chunk_size or self._read_int("RAG_CHUNK_SIZE", DEFAULT_CHUNK_SIZE)
        self.chunk_overlap = chunk_overlap if chunk_overlap is not None else self._read_int("RAG_CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP)
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0.")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size.")

    def chunk(self, sections: list[str]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        cursor = 0
        for section in sections:
            normalized = section.strip()
            if not normalized:
                cursor += len(section)
                continue
            section_start = cursor + section.find(normalized)
            chunks.extend(self._chunk_section(normalized, section_start))
            cursor += len(section) + 1
        return chunks

    def _chunk_section(self, text: str, base_start: int) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end), text.rfind(".", start, end))
                if boundary > start + int(self.chunk_size * 0.5):
                    end = boundary + 1
            chunk_text = text[start:end].strip()
            if chunk_text:
                leading_trim = len(text[start:end]) - len(text[start:end].lstrip())
                chunks.append(
                    TextChunk(
                        content=chunk_text,
                        char_start=base_start + start + leading_trim,
                        char_end=base_start + end,
                    )
                )
            if end >= len(text):
                break
            start = max(end - self.chunk_overlap, start + 1)
        return chunks

    def _read_int(self, name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default
