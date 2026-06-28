"""Artifact navigation utilities."""

from __future__ import annotations

from pathlib import Path

from ..log import logger
from ..models import ArtifactFile, ArtifactInventory
from .contract import EXPECTED_RETAILER_FILES, file_type_for, priority_for


class ArtifactNavigator:
    """Resolve and inventory one scrape artifact.

    Accepts either the scrape root:
        data/scraped/scrape_.../
    or the retailer subfolder:
        data/scraped/scrape_.../retailer/
    """

    def __init__(self, artifact_dir: str | Path) -> None:
        raw = Path(artifact_dir).expanduser().resolve()
        if not raw.exists():
            raise FileNotFoundError(f"Artifact directory does not exist: {raw}")
        self.artifact_root, self.retailer_dir = self._resolve_roots(raw)
        self.artifact_id = self.artifact_root.name

    @staticmethod
    def _resolve_roots(path: Path) -> tuple[Path, Path]:
        if path.name == "retailer":
            root = path.parent
            retailer = path
        elif (path / "retailer").is_dir():
            root = path
            retailer = path / "retailer"
        else:
            # Support degraded custom artifacts with files directly under root.
            root = path
            retailer = path
        if not retailer.exists():
            raise FileNotFoundError(f"Retailer artifact folder not found under: {path}")
        return root, retailer

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.artifact_root).as_posix()

    def abs(self, relative_path: str) -> Path:
        rel = relative_path.replace("\\", "/").lstrip("/")
        return (self.artifact_root / rel).resolve()

    def inventory(self) -> ArtifactInventory:
        files: list[ArtifactFile] = []
        for p in sorted(self.artifact_root.rglob("*")):
            if not p.is_file():
                continue
            rel = self.rel(p)
            files.append(
                ArtifactFile(
                    relative_path=rel,
                    absolute_path=p,
                    file_type=file_type_for(rel),
                    bytes_size=p.stat().st_size,
                    priority=priority_for(rel),
                )
            )
        present = [f for f in EXPECTED_RETAILER_FILES if (self.artifact_root / f).exists()]
        missing = [f for f in EXPECTED_RETAILER_FILES if f not in present]
        logger.info("Artifact inventory: {} files, missing_expected={}", len(files), len(missing))
        return ArtifactInventory(
            artifact_id=self.artifact_id,
            artifact_root=self.artifact_root,
            retailer_dir=self.retailer_dir,
            files=files,
            present_expected_files=present,
            missing_expected_files=missing,
        )

    def glob(self, pattern: str) -> list[Path]:
        return sorted(self.artifact_root.glob(pattern))


__all__ = ["ArtifactNavigator"]
