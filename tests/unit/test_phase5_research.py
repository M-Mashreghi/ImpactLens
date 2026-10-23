"""Tasks 5.1–5.5: market data, session alignment, event study, analogs, calibration."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from impactlens.market.calendar import nyse_calendar
from impactlens.market.provider import (
    CachedMarketDataProvider,
    CsvMarketDataProvider,
    FakeMarketDataProvider,
    MarketDataUnavailable,
)
from impactlens.research import analogs as analogs_mod
from impactlens.research import event_study as es_mod
from impactlens.research.analogs import AnalogFeatures, find_analogs
from impactlens.research.calibration import Observation, calibrate
from impactlens.research.event_study import EventStudyConfig, run_event_study
from impactlens.research.pit import LookAheadViolation, assert_point_in_time

CAL = nyse_calendar()

# ----------------------------------------------------------------------------- 5.1


def test_fixture_data_normalize_to_common_schema(tmp_path):
    (tmp_path / "AAA.csv").write_text(
        "Date,Open,Close,Adj Close\n2025-03-03,1,10,9.5\n2025-03-04,1,11,10.5\n"
    )
    (tmp_path / "BBB.csv").write_text("timestamp,price\n2025-03-03T00:00:00,20\n")
    provider = CsvMarketDataProvider(tmp_path)
    a = provider.get_daily_closes("aaa", "2025-03-01", "2025-03-31")
    b = provider.get_daily_closes("BBB", "2025-03-01", "2025-03-31")
    assert a.as_map() == {"2025-03-03": 9.5, "2025-03-04": 10.5} and a.price_field == "adj_close"
    assert b.as_map() == {"2025-03-03": 20.0} and b.symbol == "BBB" and a.provider == "csv"
    fake = FakeMarketDataProvider({"AAA": {"2025-03-03": 1.0}}).get_daily_closes(
        "AAA", "2025-03-01", "2025-03-05"
    )
    assert type(fake) is type(a)
    with pytest.raises(MarketDataUnavailable):
        provider.get_daily_closes("NOPE", "2025-01-01", "2025-01-02")


def test_cache_keys_include_security_date_provider_and_are_bounded(tmp_path):
    inner = FakeMarketDataProvider(
        {"AAA": {"2025-03-03": 1.0, "2025-03-04": 2.0}, "BBB": {"2025-03-03": 3.0}}
    )
    cache = CachedMarketDataProvider(inner, tmp_path, max_entries=2)
    assert (
        CachedMarketDataProvider.cache_key("fake", "aaa", "2025-03-01", "2025-03-31")
        == "fake|AAA|2025-03-01|2025-03-31"
    )
    cache.get_daily_closes("AAA", "2025-03-01", "2025-03-31")
    cache.get_daily_closes("AAA", "2025-03-01", "2025-03-31")
    assert (inner.calls, cache.hits) == (1, 1)
    cache.get_daily_closes("AAA", "2025-03-01", "2025-03-03")
    cache.get_daily_closes("BBB", "2025-03-01", "2025-03-31")
    assert inner.calls == 3 and len(list((tmp_path / "market").glob("*.json"))) == 2


def test_research_code_consumes_interface_not_vendor_shape():
    for module in (es_mod, analogs_mod):
        imports = {
            n.module for n in ast.walk(ast.parse(inspect.getsource(module))) if isinstance(n, ast.ImportFrom)
        }
        assert not any(m and ("pandas" in m or "csv" in m or "httpx" in m) for m in imports)


# ----------------------------------------------------------------------------- 5.2


@pytest.mark.parametrize(
    ("utc", "session", "anchor"),
    [
        ("2025-03-03T14:05:00Z", "pre_open", "2025-03-03"),  # 09:05 EST Monday
        ("2025-03-03T15:00:00Z", "in_session", "2025-03-03"),  # 10:00 EST
        ("2025-03-07T21:30:00Z", "after_close", "2025-03-10"),  # Friday 16:30 EST → Monday
        ("2025-03-08T15:00:00Z", "non_trading_day", "2025-03-10"),  # Saturday
        ("2025-04-18T15:00:00Z", "non_trading_day", "2025-04-21"),  # Good Friday holiday
        ("2025-03-10T13:00:00Z", "pre_open", "2025-03-10"),  # 09:00 EDT after DST switch
        ("2025-03-10T13:30:00Z", "in_session", "2025-03-10"),  # 09:30 EDT open
        ("2025-03-10T20:00:00Z", "after_close", "2025-03-11"),  # 16:00 EDT exactly
    ],
)
def test_alignment_fixtures(utc, session, anchor):
    result = CAL.align(utc, "exact")
    assert (result.session, result.anchor_date) == (session, anchor)
    assert not result.timestamp_flagged and result.policy == "anchor-v1"


def test_low_quality_timestamp_is_flagged():
    assert CAL.align("2025-03-08T00:00:00Z", "date_only").session == "date_only"
    assert CAL.align("2025-03-08T00:00:00Z", "date_only").anchor_date == "2025-03-10"
    for quality in ("missing", "assumed_utc", "invalid"):
        assert CAL.align("2025-03-03T15:00:00Z", quality).timestamp_flagged


# ----------------------------------------------------------------------------- 5.3

PRICES = {
    "SEC": {
        "2025-02-28": 100.0,
        "2025-03-03": 95.0,
        "2025-03-04": 96.9,
        "2025-03-05": 97.0,
        "2025-03-06": 98.0,
        "2025-03-07": 99.0,
        "2025-03-10": 90.0,
        "2025-03-11": 91.0,
    },
    "SPY": {
        "2025-02-28": 500.0,
        "2025-03-03": 495.0,
        "2025-03-04": 500.0,
        "2025-03-05": 505.0,
        "2025-03-06": 510.0,
        "2025-03-07": 515.0,
        "2025-03-10": 520.0,
        "2025-03-11": 525.0,
    },
}


def study(prices=PRICES, as_of="2025-04-01T00:00:00Z", utc="2025-03-03T14:05:00Z", windows=((0, 1), (0, 5))):
    return run_event_study(
        security_symbol="SEC",
        alignment=CAL.align(utc),
        calendar=CAL,
        provider=FakeMarketDataProvider(prices),
        as_of=as_of,
        config=EventStudyConfig(windows=windows),
    )


def test_hand_calculated_windows_match():
    result = study()
    w01, w05 = result.windows
    # [0,+1]: base 2025-02-28, end 2025-03-04 → 96.9/100−1 = −3.1%; SPY 500/500−1 = 0 → AR −3.1%
    assert (w01.base_date, w01.end_date) == ("2025-02-28", "2025-03-04")
    assert w01.security_return == pytest.approx(-0.031) and w01.benchmark_return == pytest.approx(0.0)
    assert w01.abnormal_return == pytest.approx(-0.031) and w01.abnormal_return_bps == pytest.approx(-310.0)
    # [0,+5]: end 2025-03-10 → 90/100−1 = −10%; SPY 520/500−1 = +4% → AR −14%
    assert w05.end_date == "2025-03-10"
    assert w05.abnormal_return == pytest.approx(-0.14)
    assert "association" in result.interpretation.lower()


def test_missing_data_follows_documented_rule():
    gappy = {"SEC": {k: v for k, v in PRICES["SEC"].items() if k != "2025-03-04"}, "SPY": PRICES["SPY"]}
    w01, w05 = study(gappy).windows
    assert w01.status == "insufficient_data" and w01.missing == ("SEC:2025-03-04",)
    assert w05.status == "ok"  # no forward-filling, other windows unaffected
    nobench = study({"SEC": PRICES["SEC"]})
    assert all(w.status == "insufficient_data" for w in nobench.windows)
    assert any("unavailable" in n for n in nobench.notes)


def test_window_not_observable_before_as_of_is_withheld():
    w01, w05 = study(as_of="2025-03-05T12:00:00Z").windows
    assert w01.status == "ok" and w05.status == "not_yet_observable"
    # bars after as_of are never used, even if the provider returns them
    w01_early = study(as_of="2025-03-04T15:00:00Z").windows[0]
    assert w01_early.status == "not_yet_observable"


def test_llm_is_not_called_by_calculation_engine():
    for module in (es_mod, analogs_mod):
        source = inspect.getsource(module)
        imports = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
        assert not any(m and "intelligence.llm" in m for m in imports)
        assert "complete(" not in source


# ----------------------------------------------------------------------------- 5.4


def feat(
    aid,
    when,
    et="regulation_policy",
    d="negative",
    s="high",
    h="medium_term",
    iss=("iss_nvidia",),
    sec=("Information Technology",),
) -> AnalogFeatures:
    return AnalogFeatures(
        analysis_id=aid,
        news_id=aid,
        event_time=when,
        event_type=et,
        direction=d,
        severity=s,
        time_horizon=h,
        issuers=frozenset(iss),
        sectors=frozenset(sec),
        title=f"n{aid}",
    )


def test_known_analog_ranks_expected_and_future_never_eligible():
    query = feat(1, "2025-03-03T14:05:00Z")
    cands = [
        feat(2, "2025-01-13T15:00:00Z", s="medium"),  # close analog
        feat(3, "2024-11-01T15:00:00Z", et="earnings", d="positive", iss=("iss_apple",)),
        feat(4, "2025-03-20T15:00:00Z"),  # identical but future
        feat(5, "2025-03-03T14:05:00Z"),  # same timestamp: excluded
        feat(1, "2025-03-03T14:05:00Z"),  # itself
    ]
    results = find_analogs(query, cands)
    assert [a.analysis_id for a in results] == [2, 3]
    assert results[0].components["event_type"] == 1.0 and results[0].components["severity"] == pytest.approx(
        2 / 3
    )
    assert set(results[0].weights) == set(results[0].components)
    assert results[0].similarity == pytest.approx(0.4 + 0.25 + 0.15 + 0.1 + 0.05 * (2 / 3) + 0.05, abs=1e-6)


# ----------------------------------------------------------------------------- 5.5


def obs(
    i, level, comp, ar, status="ok", feature_time="2025-01-02T00:00:00Z", et="regulation_policy"
) -> Observation:
    return Observation(
        impact_id=i,
        news_id=i,
        security_id=f"s{i}",
        event_type=et,
        position_level=level,
        signed_component=comp,
        event_time="2025-03-03T14:05:00Z",
        feature_times={"snapshot_as_of": feature_time},
        abnormal_return=ar,
        study_status=status,
    )


DATASET = [
    obs(1, "Critical", -0.5, -0.06),
    obs(2, "High", -0.3, -0.02),
    obs(3, "High", 0.3, -0.01),
    obs(4, "Low", 0.05, 0.002, et="earnings"),
    obs(5, "Low", -0.05, None, status="insufficient_data"),
    obs(6, "Medium", -0.1, None, status=None),
]


def test_fixed_dataset_report_reproduces():
    report = calibrate(DATASET)
    assert report == calibrate(list(DATASET))
    by = {b.key: b for b in report.by_level}
    assert [b.key for b in report.by_level] == ["Low", "High", "Critical"]
    assert by["High"].n == 2 and by["High"].mean_abs_ar == pytest.approx(0.015)
    assert by["High"].direction_hits == 1 and by["High"].direction_hit_rate == 0.5
    assert by["Critical"].direction_hit_rate == 1.0
    assert "not causal" in report.note.lower()


def test_no_look_ahead_test_fails_when_future_feature_injected():
    poisoned = [*DATASET, obs(7, "High", -0.3, -0.05, feature_time="2025-03-04T00:00:00Z")]
    with pytest.raises(LookAheadViolation):
        calibrate(poisoned, strict_point_in_time=True)
    lenient = calibrate(poisoned, strict_point_in_time=False)
    assert lenient.excluded["look_ahead_feature"] == 1
    with pytest.raises(LookAheadViolation):
        assert_point_in_time("2025-01-01T00:00:00Z", [("price", "2025-01-02T00:00:00Z")])


def test_evaluation_reports_coverage_and_every_exclusion():
    report = calibrate(DATASET)
    assert report.candidates == 6 and report.included == 4
    assert report.excluded == {"no_event_study": 1, "study_insufficient_data": 1}
    assert report.included + sum(report.excluded.values()) == report.candidates


def test_sample_prices_exist_for_demo_symbols(samples_dir: Path):
    for symbol in ("SPY", "NVDA", "AMD", "TSM", "ASML", "XOM", "DAL", "GOOGL", "GOOG"):
        assert (samples_dir / "prices" / f"{symbol}.csv").is_file()
