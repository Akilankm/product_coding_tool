"""Execution of the artifact evidence collection plan."""

from __future__ import annotations

from ..models import ArtifactInventory, EvidencePacket, EvidencePlan, FeatureRule
from ..artifacts.evidence_packet import EvidencePacketBuilder
from ..artifacts.navigator import ArtifactNavigator
from ..artifacts.reader import ArtifactReader
from .visual import VisualEvidenceCollector


class EvidenceRetriever:
    def __init__(self, navigator: ArtifactNavigator, reader: ArtifactReader | None = None) -> None:
        self.navigator = navigator
        self.reader = reader or ArtifactReader(navigator)
        self.builder = EvidencePacketBuilder(navigator, self.reader)
        self.visual = VisualEvidenceCollector(navigator, self.reader)

    def retrieve(self, feature: FeatureRule, inventory: ArtifactInventory, plan: EvidencePlan) -> EvidencePacket:
        packet = self.builder.build(feature, inventory, plan)
        if feature.requires_visual or plan.needs_images:
            visual_item = self.visual.collect(feature)
            if visual_item is not None:
                existing = list(packet.evidence)
                visual_item = visual_item.model_copy(update={"evidence_id": f"E{len(existing)+1:03d}"})
                packet = packet.model_copy(update={"evidence": [*existing, visual_item]})
        return packet


__all__ = ["EvidenceRetriever"]
