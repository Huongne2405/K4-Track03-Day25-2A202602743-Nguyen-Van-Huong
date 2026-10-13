"""Check exact thresholds, traffic weighting and alert episode boundaries."""

import pytest

from gameday_lab.slo.alerting import AlertEvent, AlertRule, BurnRateAlerter, WindowSums, error_budget_report


@pytest.mark.parametrize("bad, expected", [(5, True), (4, False)])
def test_exact_burn_threshold_and_below_threshold(bad: int, expected: bool) -> None:
    rule = AlertRule("boundary", "ticket", 1, 1, 1.0)
    events = BurnRateAlerter(rules=(rule,)).evaluate([1000], [bad])
    assert bool(events) is expected
    if expected:
        assert events == [AlertEvent("boundary", "ticket", 0, 1)]


def test_high_short_burn_alone_does_not_fire() -> None:
    rule = AlertRule("both_windows", "page", 3, 1, 3.0)
    assert BurnRateAlerter(rules=(rule,)).evaluate([1000] * 3, [0, 0, 40]) == []


def test_window_error_ratio_is_weighted_by_request_volume() -> None:
    burn = BurnRateAlerter().burn_rate(WindowSums([1, 1000]), WindowSums([1, 0]), 1, 2)
    assert burn == pytest.approx((1 / 1001) / 0.005)


def test_separate_episodes_close_exclusively_and_flush_at_end_of_data() -> None:
    rule = AlertRule("episodes", "ticket", 3, 1, 1.0)
    events = BurnRateAlerter(rules=(rule,)).evaluate([1000] * 7, [0, 20, 20, 0, 0, 20, 20])
    assert events == [AlertEvent("episodes", "ticket", 1, 3), AlertEvent("episodes", "ticket", 5, 7)]


def test_events_are_sorted_by_start_time_across_rules() -> None:
    strict = AlertRule("strict", "page", 1, 1, 4.0)
    loose = AlertRule("loose", "ticket", 1, 1, 2.0)
    events = BurnRateAlerter(rules=(strict, loose)).evaluate([1000] * 3, [0, 10, 20])
    assert events == [AlertEvent("loose", "ticket", 1, 3), AlertEvent("strict", "page", 2, 3)]


def test_exactly_exhausted_budget_freezes_releases() -> None:
    report = error_budget_report([1000] * 100, [500] + [0] * 99)
    assert report["budget_consumed"] == 1.0
    assert report["budget_remaining"] == 0.0
    assert report["freeze_releases"] is True


def test_no_traffic_produces_no_alerts_or_consumed_budget() -> None:
    assert BurnRateAlerter().evaluate([0] * 10, [0] * 10) == []
    assert BurnRateAlerter().evaluate([], []) == []
    report = error_budget_report([], [])
    assert report["budget_consumed"] == 0.0
    assert report["budget_remaining"] == 1.0
    assert report["freeze_releases"] is False
