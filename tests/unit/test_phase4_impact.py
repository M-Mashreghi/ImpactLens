"""Tasks 4.1–4.5: exposure mapping, deterministic scoring, explanation, orchestration."""

from __future__ import annotations

import json
import sqlite3

import pytest
from pydantic import ValidationError

from impactlens.entities.models import FactorExposure, SecurityRelationship
from impactlens.entities.resolver import ResolutionStatus
from impactlens.impact.explanation import build_explanation
from impactlens.impact.exposure import ExposureEngine, ExposureMatch
from impactlens.impact.scoring import DEFAULT_CONFIG, ScoringConfig, level_for, score_matches
from impactlens.intelligence.entity_pipeline import ResolvedEntity
from impactlens.intelligence.taxonomy import Direction, EntityRole, EntityType
from impactlens.portfolio.models import PortfolioSnapshot, Position, WeightBasis
from tests.conftest import SAMPLES
from tests.unit.test_phase3_intelligence import _ingest


def entity(
    name="NVIDIA",
    kind="security",
    ids=("sec_nvda",),
    factor=None,
    direction=Direction.NEGATIVE,
    role=EntityRole.PRIMARY_SUBJECT,
    etype=EntityType.COMPANY,
) -> ResolvedEntity:
    return ResolvedEntity(
        name=name,
        normalized_name=name.lower(),
        entity_type=etype,
        role=role,
        direction=direction,
        status=ResolutionStatus.RESOLVED,
        kind=kind,
        security_ids=ids,
        factor_key=factor,
        evidence_supported=True,
    )


def snapshot(*positions: tuple[str, str, float]) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id="snap_t",
        portfolio_id="pf_t",
        as_of="2025-01-01T00:00:00Z",
        created_at="2025-01-01T00:00:00Z",
        source="test",
        weight_basis=WeightBasis.WEIGHT,
        content_hash="h",
        positions=tuple(
            Position(line_no=i + 1, security_id=sid, ticker=t, display_name=t, weight=w)
            for i, (sid, t, w) in enumerate(positions)
        ),
    )


@pytest.fixture
def engine(securities):
    rels = [
        (i + 1, SecurityRelationship.model_validate(r))
        for i, r in enumerate(json.loads((SAMPLES / "relationships.json").read_text()))
    ]
    fx = [
        (i + 1, FactorExposure.model_validate(r))
        for i, r in enumerate(json.loads((SAMPLES / "factor_exposures.json").read_text()))
    ]
    return ExposureEngine({s.security_id: s for s in securities}, rels, fx)


# ----------------------------------------------------------------------------- 4.1


def test_direct_held_security_maps_as_direct(engine):
    snap = snapshot(("sec_nvda", "NVDA", 0.15), ("sec_aapl", "AAPL", 0.85))
    matches = engine.match([entity()], snap)
    direct = [m for m in matches if m.family == "direct"]
    assert len(direct) == 1 and direct[0].relationship_type == "direct" and direct[0].position_weight == 0.15


def test_non_held_company_creates_no_direct_match(engine):
    snap = snapshot(("sec_aapl", "AAPL", 1.0))
    assert [m for m in engine.match([entity()], snap) if m.family == "direct"] == []


def test_multiple_share_classes_match_explicitly(engine):
    snap = snapshot(("sec_googl", "GOOGL", 0.06), ("sec_goog", "GOOG", 0.04), ("sec_aapl", "AAPL", 0.9))
    ents = [entity("Alphabet", ids=("sec_goog", "sec_googl"))]
    matches = engine.match(ents, snap)
    assert {m.ticker for m in matches} == {"GOOGL", "GOOG"}
    assert all("Class" in m.path for m in matches)


def test_snapshot_id_is_recorded_on_impacts(container, demo_snapshot):
    record = _ingest(container, "n01_export_controls")
    outcome = container.analysis_service.analyze(record)
    impact = container.impacts.get(
        container.impact_service.score(outcome.analysis_id, demo_snapshot).impact_id
    )
    assert impact["snapshot_id"] == demo_snapshot.snapshot_id == impact["result"]["snapshot_id"]


# ----------------------------------------------------------------------------- 4.2


def test_allowed_indirect_fixtures_create_expected_matches(engine):
    snap = snapshot(
        ("sec_tsm", "TSM", 0.1),
        ("sec_xom", "XOM", 0.1),
        ("sec_dal", "DAL", 0.1),
        ("sec_amd", "AMD", 0.1),
        ("sec_aapl", "AAPL", 0.6),
    )
    supplier = [m for m in engine.match([entity()], snap) if m.ticker == "TSM"]
    assert supplier[0].relationship_type == "supplier" and supplier[0].provenance["source"] == "public_filing"
    competitor = [m for m in engine.match([entity()], snap) if m.ticker == "AMD"][0]
    assert competitor.relationship_type == "competitor" and competitor.direction is Direction.POSITIVE

    oil = entity(
        "crude oil",
        kind="factor",
        ids=(),
        factor="commodity:crude_oil",
        direction=Direction.POSITIVE,
        etype=EntityType.COMMODITY,
    )
    by = {m.ticker: m for m in engine.match([oil], snap)}
    assert by["XOM"].direction is Direction.POSITIVE and by["DAL"].direction is Direction.NEGATIVE
    assert by["DAL"].link_strength == 0.6 and by["DAL"].provenance["factor_exposure_id"]

    sector = entity(
        "Semiconductors", kind="industry", ids=(), factor="industry:Semiconductors", etype=EntityType.INDUSTRY
    )
    assert {m.ticker for m in engine.match([sector], snap)} == {"TSM", "AMD"}


def test_unsupported_relationship_is_blocked():
    with pytest.raises(ValidationError):
        SecurityRelationship(
            source_security_id="a",
            target_security_id="b",
            relationship_type="partner",
            strength=0.5,
            provenance_source="public_filing",
            provenance_ref="ref",
            as_of="2024-01-01",
        )


def test_llm_memory_cannot_create_persisted_relationship(container):
    for source in ("llm", "LLM_memory", "model"):
        with pytest.raises(ValidationError):
            SecurityRelationship(
                source_security_id="sec_aapl",
                target_security_id="sec_tsm",
                relationship_type="customer",
                strength=0.5,
                provenance_source=source,
                provenance_ref="the model said so",
                as_of="2024-01-01",
            )
    before = len(container.relationships.relationships())
    with pytest.raises(sqlite3.IntegrityError):
        container.db.conn.execute(
            "INSERT INTO security_relationships (source_security_id, target_security_id, relationship_type, strength,"
            " provenance_source, provenance_ref, as_of) VALUES ('sec_aapl','sec_tsm','partner',0.5,'x','y','z')"
        )
    assert len(container.relationships.relationships()) == before


def test_indirect_families_can_be_disabled(securities, engine):
    disabled = ExposureEngine(
        engine.securities,
        engine.relationships,
        engine.factor_exposures,
        disabled_families=["relationship", "commodity"],
    )
    snap = snapshot(("sec_tsm", "TSM", 0.5), ("sec_xom", "XOM", 0.5))
    assert disabled.match([entity()], snap) == []
    oil = entity("oil", kind="factor", ids=(), factor="commodity:crude_oil", etype=EntityType.COMMODITY)
    assert disabled.match([oil], snap) == []
    with pytest.raises(ValueError):
        ExposureEngine({}, disabled_families=["telepathy"])


def test_relationships_recorded_after_event_are_excluded_point_in_time(engine):
    snap = snapshot(("sec_tsm", "TSM", 1.0))
    assert [
        m for m in engine.match([entity()], snap, as_of="2024-01-15T00:00:00Z") if m.ticker == "TSM"
    ] == []
    assert [m for m in engine.match([entity()], snap, as_of="2025-01-15T00:00:00Z") if m.ticker == "TSM"]


# ----------------------------------------------------------------------------- 4.3


def match(
    weight,
    rel="direct",
    direction=Direction.NEGATIVE,
    role="primary_subject",
    strength=1.0,
    line=1,
    ticker="NVDA",
) -> ExposureMatch:
    return ExposureMatch(
        security_id=f"sec_{ticker.lower()}",
        ticker=ticker,
        display_name=ticker,
        position_line=line,
        position_weight=weight,
        position_market_value=None,
        relationship_type=rel,
        family="direct" if rel == "direct" else "relationship",
        source_entity="E",
        source_entity_role=role,
        entity_direction=direction,
        direction=direction,
        link_strength=strength,
        provenance={},
        path="p",
    )


def test_hand_computed_fixture_matches_code():
    # NVDA: 0.15/0.20=0.75 × 1.0 × 0.75 (high) × 0.87 × 1.0 = 0.489375
    # TSM supplier: 0.07/0.20=0.35 × 0.6 × 0.75 × 0.87 × (0.8 affected × 0.8 strength = 0.64) = 0.08769...
    score = score_matches(
        [match(0.15), match(0.07, "supplier", role="affected", strength=0.8, line=2, ticker="TSM")],
        severity="high",
        confidence=0.87,
    )
    by = {c.ticker: c for c in score.components}
    assert by["NVDA"].signed_component == pytest.approx(-0.489375, abs=1e-9)
    assert by["TSM"].base == pytest.approx(0.35 * 0.6 * 0.75 * 0.87 * 0.64, abs=1e-6)
    assert score.signed_score == pytest.approx(-100 * (0.489375 + 0.35 * 0.6 * 0.75 * 0.87 * 0.64), abs=1e-3)
    assert score.absolute_priority == pytest.approx(-score.signed_score)
    assert score.impact_level == "Critical" and score.net_direction == "negative"


def test_same_inputs_and_version_are_deterministic():
    args = dict(severity="medium", confidence=0.6)
    ms = [match(0.1), match(0.05, "competitor", Direction.POSITIVE, line=2, ticker="AMD")]
    assert score_matches(ms, **args).model_dump() == score_matches(list(reversed(ms)), **args).model_dump()


def test_caps_and_threshold_boundaries():
    assert (
        score_matches([match(0.9)], severity="critical", confidence=1.0).components[0].exposure_magnitude
        == 1.0
    )
    many = [match(0.2, line=i, ticker=f"T{i}") for i in range(5)]
    assert score_matches(many, severity="critical", confidence=1.0).absolute_priority == 100.0
    assert [level_for(v) for v in (0, 9.9999, 10, 24.9999, 25, 49.9999, 50, 100)] == [
        "Low",
        "Low",
        "Medium",
        "Medium",
        "High",
        "High",
        "Critical",
        "Critical",
    ]
    # exactly 25.0: 0.2 weight → 1.0 × 1.0 × 0.5 (medium) × 0.5 conf × 1.0
    assert score_matches([match(0.2)], severity="medium", confidence=0.5).impact_level == "High"


def test_mixed_neutral_uncertain_and_double_counting():
    mixed = score_matches([match(0.2, direction=Direction.MIXED)], severity="high", confidence=1.0)
    assert mixed.signed_score == 0.0 and mixed.absolute_priority == 75.0 and mixed.net_direction == "mixed"
    neutral = score_matches([match(0.2, direction=Direction.NEUTRAL)], severity="high", confidence=1.0)
    assert neutral.absolute_priority == 37.5
    unc = score_matches([match(0.2, direction=Direction.UNCERTAIN)], severity="high", confidence=1.0)
    assert unc.components == () and unc.excluded[0].reason == "direction uncertain"
    both = score_matches([match(0.1), match(0.1, "supplier", line=1)], severity="high", confidence=1.0)
    assert [c.counted for c in both.components] == [True, False]
    assert both.absolute_priority == pytest.approx(37.5)
    pos_neg = score_matches(
        [match(0.1), match(0.1, direction=Direction.POSITIVE, line=2, ticker="X")],
        severity="high",
        confidence=1.0,
    )
    assert pos_neg.signed_score == 0.0 and pos_neg.net_direction == "mixed"


def test_score_labeled_priority_not_expected_return():
    score = score_matches([match(0.1)], severity="low", confidence=0.5)
    assert "Not an expected return" in score.semantics
    assert score.scoring_version == DEFAULT_CONFIG.version == "impact-v1"
    assert ScoringConfig(version="impact-v2", weight_cap=0.1).version == "impact-v2"


def test_invalid_confidence_rejected():
    with pytest.raises(ValueError):
        score_matches([match(0.1)], severity="low", confidence=1.2)


# ----------------------------------------------------------------------------- 4.4 / 4.5


@pytest.fixture
def scored(container, demo_snapshot):
    record = _ingest(container, "n01_export_controls")
    analysis_id = container.analysis_service.analyze(record).analysis_id
    outcome = container.impact_service.score(analysis_id, demo_snapshot)
    return container, demo_snapshot, analysis_id, container.impacts.get(outcome.impact_id)


def test_explanation_names_paths_and_numbers_match_scorer(scored):
    container, _, _, impact = scored
    exp = impact["explanation"]
    assert len(exp["positions"]) == len(impact["result"]["components"])
    for pos, comp in zip(exp["positions"], impact["result"]["components"], strict=True):
        assert pos["ticker"] == comp["ticker"] and pos["path"] == comp["path"]
        assert pos["numbers"]["signed_component"] == comp["signed_component"]
        assert pos["numbers"]["position_weight"] == comp["position_weight"]
        assert comp["path"] in pos["text"]
    assert any("supplier" in p["text"].lower() for p in exp["positions"])
    assert "Not an expected return" in exp["disclaimer"]


def test_template_explanation_only_quotes_grounded_evidence(scored):
    container, _, analysis_id, impact = scored
    article = container.news.get(impact["news_id"]).analysis_text.casefold()
    for cite in impact["explanation"]["citations"]:
        assert " ".join(cite["quote"].casefold().split()) in " ".join(article.split())
        assert cite["content_hash"].startswith("sha256:")
    # Fabricated-span analyses never reach scoring, so explanation inputs are always grounded:
    analysis = container.analyses.get(analysis_id)
    assert analysis["evidence_report"]["fabricated_ids"] == []
    rebuilt = build_explanation(
        score=__import__("impactlens.impact.scoring", fromlist=["ImpactScore"]).ImpactScore.model_validate(
            {
                k: impact["result"][k]
                for k in (
                    "scoring_version",
                    "signed_score",
                    "absolute_priority",
                    "impact_level",
                    "net_direction",
                    "components",
                    "excluded",
                    "affected_positions",
                    "semantics",
                    "config",
                )
            }
        ),
        analysis=analysis,
        news=container.news.get(impact["news_id"]).model_dump(mode="json"),
    )
    assert rebuilt.model_dump(mode="json") == impact["explanation"]


def test_end_to_end_fixture_returns_positions_and_breakdown(scored):
    _, _, _, impact = scored
    counted = {c["ticker"] for c in impact["result"]["components"] if c["counted"]}
    assert counted == {"NVDA", "AMD", "TSM", "ASML"}
    assert impact["impact_level"] == "Critical" and impact["signed_score"] < 0
    nvda = next(c for c in impact["result"]["components"] if c["ticker"] == "NVDA" and c["counted"])
    assert nvda["signed_component"] == pytest.approx(-0.489375)


def test_idempotent_rerun_does_not_duplicate_rows(scored):
    container, snap, analysis_id, impact = scored
    again = container.impact_service.score(analysis_id, snap)
    assert again.reused and again.impact_id == impact["impact_id"]
    forced = container.impact_service.score(analysis_id, snap, force=True)
    assert forced.impact_id == impact["impact_id"] and container.impacts.count() == 1
    assert len(container.impacts.components(impact["impact_id"])) == len(impact["result"]["components"])


def test_uncertain_analysis_is_not_scored(container, demo_snapshot):
    record = _ingest(container, "n05_rumor")
    analysis_id = container.analysis_service.analyze(record).analysis_id
    with pytest.raises(ValueError):
        container.impact_service.score(analysis_id, demo_snapshot)


def test_positive_negative_mixed_fixtures_rank_deterministically(container, demo_snapshot):
    ids = []
    for name in ("n03_oil_spike", "n04_alphabet_ruling", "n01_export_controls", "n08_prior_export"):
        a = container.analysis_service.analyze(_ingest(container, name)).analysis_id
        ids.append(container.impact_service.score(a, demo_snapshot).impact_id)
    feed = container.impact_service.feed(demo_snapshot.snapshot_id)
    order = [f["news_id"] for f in feed]
    priorities = [f["absolute_priority"] for f in feed]
    assert priorities == sorted(priorities, reverse=True)
    assert order == [f["news_id"] for f in container.impact_service.feed(demo_snapshot.snapshot_id)]
    oil = next(f for f in feed if f["result"]["net_direction"] == "mixed")
    assert {c["direction"] for c in oil["result"]["components"]} == {"positive", "negative"}
    assert (
        container.impact_service.feed(demo_snapshot.snapshot_id, min_level="Critical")[0]["impact_level"]
        == "Critical"
    )
