"""Optional multimodal visual evidence collection for features that need images."""

from __future__ import annotations

import json

from ..config import get_config
from ..log import logger
from ..artifacts.image_loader import ImageLoader
from ..artifacts.navigator import ArtifactNavigator
from ..artifacts.reader import ArtifactReader
from ..models import EvidenceItem, FeatureRule
from ..prompts import P
from ..services.llm import get_llm_service
from .json_utils import parse_json_object


class VisualEvidenceCollector:
    """Run a bounded image-inspection pass and convert the observation into evidence."""

    def __init__(self, navigator: ArtifactNavigator, reader: ArtifactReader | None = None) -> None:
        self.navigator = navigator
        self.reader = reader or ArtifactReader(navigator)
        self.cfg = get_config()
        self.images = ImageLoader(navigator, self.reader)

    def collect(self, feature: FeatureRule) -> EvidenceItem | None:
        if not self.cfg.llm_enabled or not self.cfg.llm_vision_enabled:
            return None
        paths = self.images.image_paths(max_images=self.cfg.llm_vision_max_images)
        if not paths:
            return None
        payload = {
            "feature_rule": feature.model_dump(),
            "instruction": "Inspect only visible evidence relevant to the feature. Do not infer hidden product facts.",
            "image_manifest": self.images.image_manifest(),
        }
        try:
            resp = get_llm_service().predict(
                json.dumps(payload, ensure_ascii=False, indent=2),
                system_prompt=P.VISUAL_FEATURE_CODING.system,
                images=[str(p) for p in paths],
                image_detail=self.cfg.llm_vision_detail,
                max_tokens=min(2048, self.cfg.llm_max_tokens),
                temperature=0.0,
                response_format={"type": "json_object"},
                purpose=P.VISUAL_FEATURE_CODING.name,
            )
            data = parse_json_object(resp.content)
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return EvidenceItem(
                evidence_id="EVIS",
                source_file="retailer/images/*",
                evidence_type="visual_llm_observation",
                text=text,
                score=18.0,
                strength="medium",
                evidence_axis=["V"],
                metadata={"image_count": len(paths), "image_paths": [p.name for p in paths], "llm_usage": resp.usage},
            )
        except Exception as exc:
            logger.warning("Visual evidence collection failed for feature={}: {}", feature.feature_name, exc)
            return None


__all__ = ["VisualEvidenceCollector"]
