"""Local artifact evidence locator.

This module performs only in-folder evidence lookup over the already-created
product artifact. It does not call the web, SerpAPI, Crawl4AI, or any scraper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import get_config
from ..models import ArtifactInventory, EvidenceItem
from .contract import priority_for
from .navigator import ArtifactNavigator
from .reader import ArtifactReader

_TOKEN_RE = re.compile(r"[\w\-/+]+", re.UNICODE)


@dataclass(frozen=True)
class LocatorHit:
    source_file: str
    snippet: str
    score: float
    match_terms: tuple[str, ...]


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text or "") if len(m.group(0)) > 1]


def compact_snippet(text: str, terms: list[str], *, context_chars: int) -> str:
    if not text:
        return ""
    lowered = text.lower()
    positions: list[int] = []
    for term in terms:
        idx = lowered.find(term.lower())
        if idx >= 0:
            positions.append(idx)
    if not positions:
        return text[:context_chars].strip()
    pos = min(positions)
    start = max(0, pos - context_chars // 2)
    end = min(len(text), start + context_chars)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


class ArtifactEvidenceLocator:
    def __init__(self, navigator: ArtifactNavigator, reader: ArtifactReader | None = None) -> None:
        self.navigator = navigator
        self.reader = reader or ArtifactReader(navigator)
        self.cfg = get_config()

    def locatable_files(self, inventory: ArtifactInventory | None = None) -> list[str]:
        inv = inventory or self.navigator.inventory()
        allowed_types = {"markdown", "json"}
        files = [f for f in inv.files if f.file_type in allowed_types]
        # Keep tables/source/claims first for stronger page-grounded evidence.
        files.sort(key=lambda f: (f.priority, f.relative_path))
        return [f.relative_path for f in files]

    def locate(
        self,
        queries: list[str],
        *,
        inventory: ArtifactInventory | None = None,
        max_hits: int = 12,
        max_file_chars: int | None = None,
        context_chars: int | None = None,
    ) -> list[LocatorHit]:
        query_terms = []
        for query in queries:
            query_terms.extend(tokenize(query))
        # Preserve multi-word queries as substring signals.
        phrases = [(q or "").strip().lower() for q in queries if (q or "").strip()]
        terms = sorted(set(query_terms + phrases), key=len, reverse=True)
        if not terms:
            return []
        max_file_chars = max_file_chars or self.cfg.coding_read_file_chars
        context_chars = context_chars or self.cfg.coding_evidence_context_chars

        hits: list[LocatorHit] = []
        for rel in self.locatable_files(inventory):
            try:
                text = self.reader.read_any_as_text(rel, max_chars=max_file_chars)
            except Exception:
                continue
            lowered = text.lower()
            matched = [t for t in terms if t and t in lowered]
            if not matched:
                continue
            priority = max(1, priority_for(rel))
            # Score: matched term count and file priority. Lower priority number is stronger.
            score = (len(matched) * 10.0 + sum(min(5, len(t)) for t in matched)) / priority
            hits.append(
                LocatorHit(
                    source_file=rel,
                    snippet=compact_snippet(text, matched, context_chars=context_chars),
                    score=score,
                    match_terms=tuple(matched[:20]),
                )
            )
        hits.sort(key=lambda h: (-h.score, priority_for(h.source_file), h.source_file))
        return hits[:max_hits]

    def locate_as_evidence(
        self,
        queries: list[str],
        *,
        inventory: ArtifactInventory | None = None,
        start_index: int = 1,
        max_hits: int = 12,
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for offset, hit in enumerate(self.locate(queries, inventory=inventory, max_hits=max_hits), start=start_index):
            strength = "strong" if hit.score >= 20 else "medium" if hit.score >= 8 else "weak"
            items.append(
                EvidenceItem(
                    evidence_id=f"E{offset:03d}",
                    source_file=hit.source_file,
                    evidence_type="artifact_snippet",
                    text=hit.snippet,
                    score=hit.score,
                    strength=strength,  # type: ignore[arg-type]
                    metadata={"match_terms": list(hit.match_terms)},
                )
            )
        return items


__all__ = ["ArtifactEvidenceLocator", "LocatorHit", "tokenize"]
