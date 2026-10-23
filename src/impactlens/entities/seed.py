"""Load the synthetic/public demo security master, relationships and factor exposures."""

from __future__ import annotations

import json
from pathlib import Path

from impactlens.entities.models import FactorExposure, Security, SecurityRelationship
from impactlens.storage.repositories import RelationshipRepository, SecurityRepository


def load_reference_data(
    samples_dir: str | Path, securities: SecurityRepository, relationships: RelationshipRepository
) -> dict[str, int]:
    folder = Path(samples_dir)
    counts = {"securities": 0, "relationships": 0, "factor_exposures": 0}
    sec_path = folder / "securities.json"
    if sec_path.is_file():
        for row in json.loads(sec_path.read_text("utf-8")):
            securities.upsert(Security.model_validate(row))
            counts["securities"] += 1
    rel_path = folder / "relationships.json"
    if rel_path.is_file():
        for row in json.loads(rel_path.read_text("utf-8")):
            relationships.add_relationship(SecurityRelationship.model_validate(row))
            counts["relationships"] += 1
    fx_path = folder / "factor_exposures.json"
    if fx_path.is_file():
        for row in json.loads(fx_path.read_text("utf-8")):
            relationships.add_factor_exposure(FactorExposure.model_validate(row))
            counts["factor_exposures"] += 1
    return counts
