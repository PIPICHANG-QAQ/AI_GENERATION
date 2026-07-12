from app.adaptive_concurrency import AdaptiveConcurrencyGate


def test_gate_increases_after_success_window():
    gate = AdaptiveConcurrencyGate(
        initial=4,
        minimum=2,
        maximum=8,
        success_window=3,
        cooldown_seconds=30,
    )

    for _ in range(3):
        gate.record_success(100)

    assert gate.snapshot()["limit"] == 5


def test_gate_halves_on_provider_pressure_and_respects_floor():
    gate = AdaptiveConcurrencyGate(
        initial=8,
        minimum=2,
        maximum=8,
        success_window=20,
        cooldown_seconds=30,
    )

    gate.record_failure("rate_limit")
    assert gate.snapshot()["limit"] == 4
    gate.record_failure("service_unavailable")
    assert gate.snapshot()["limit"] == 2
    gate.record_failure("timeout")
    assert gate.snapshot()["limit"] == 2


def test_interactive_priority_precedes_retry_batch_and_automatic():
    gate = AdaptiveConcurrencyGate(
        initial=4,
        minimum=2,
        maximum=8,
        success_window=20,
        cooldown_seconds=30,
    )

    assert gate.priority_value("interactive") < gate.priority_value("retry")
    assert gate.priority_value("retry") < gate.priority_value("batch")
    assert gate.priority_value("batch") < gate.priority_value("automatic")


def test_snapshot_reports_active_and_bounds():
    gate = AdaptiveConcurrencyGate(
        initial=4,
        minimum=2,
        maximum=8,
        success_window=20,
        cooldown_seconds=30,
    )

    with gate.slot("batch"):
        snapshot = gate.snapshot()
        assert snapshot == {
            "active": 1,
            "limit": 4,
            "minimum": 2,
            "maximum": 8,
            "cooldown": False,
        }

    assert gate.snapshot()["active"] == 0
