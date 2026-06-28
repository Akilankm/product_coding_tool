"""Image discovery for visual coding checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import get_config
from .navigator import ArtifactNavigator
from .reader import ArtifactReader


class ImageLoader:
    def __init__(self, navigator: ArtifactNavigator, reader: ArtifactReader | None = None) -> None:
        self.navigator = navigator
        self.reader = reader or ArtifactReader(navigator)
        self.cfg = get_config()

    def image_paths(self, *, max_images: int | None = None) -> list[Path]:
        max_images = max_images or self.cfg.llm_vision_max_images
        image_dir = self.navigator.artifact_root / "retailer" / "images"
        if not image_dir.exists():
            return []
        paths = [p for p in sorted(image_dir.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        # Prefer files that are non-empty and reasonably likely product images.
        paths = [p for p in paths if p.is_file() and p.stat().st_size > 0]
        return paths[:max_images]

    def image_manifest(self) -> dict[str, Any]:
        rel = "retailer/manifests/image_manifest.json"
        if not self.reader.exists(rel):
            return {}
        try:
            data = self.reader.read_json(rel)
            return data if isinstance(data, dict) else {"items": data}
        except Exception as exc:
            return {"_read_error": str(exc)}


__all__ = ["ImageLoader"]
