from datetime import UTC, datetime

import pytest

from app.domain.entities import Signal
from app.infrastructure.agents import StubTriageAgent


def make_signal(**overrides) -> Signal:
    defaults = dict(
        signal_id="sig_1",
        signal_type="transaction",
        occurred_at=datetime.now(UTC),
        account_id="acct_1",
        upstream_score=0.6,
        flag_reason="ml_score_0.60",
        payload={"amount": 50.0, "merchant_id": "m1", "device_context": "known_device", "geo_context": "usual_location"},
    )
    defaults.update(overrides)
    return Signal(**defaults)


@pytest.mark.asyncio
class TestStubTriageAgent:
    async def test_low_confidence_maps_to_benign(self):
        result = await StubTriageAgent().run(make_signal(upstream_score=0.1), velocity_context={})
        assert result.pattern == "benign"
        assert result.tier == "low"

    async def test_high_confidence_with_velocity_flag_maps_to_card_testing(self):
        result = await StubTriageAgent().run(
            make_signal(upstream_score=0.9, flag_reason="velocity_rule_7"), velocity_context={}
        )
        assert result.pattern == "card_testing"
        assert result.tier == "critical"

    async def test_entities_carry_signal_fields_forward_verbatim(self):
        signal = make_signal()
        result = await StubTriageAgent().run(signal, velocity_context={"recent_txn_count_10min": 3})
        assert result.entities["account_id"] == signal.account_id
        assert result.entities["merchant_id"] == "m1"
        assert result.entities["recent_txn_count_10min"] == 3
