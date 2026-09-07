import pytest


@pytest.mark.asyncio
class TestCheckoutEndpoint:
    async def test_elevated_card_creates_a_pending_review_case(self, client):
        response = await client.post(
            "/checkout",
            json={
                "account_id": "acct_it_1",
                "amount": 42.5,
                "merchant_id": "merch_it",
                "device_context": "known_device",
                "geo_context": "usual_location",
                "test_card": "elevated",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["charge_succeeded"] is True
        assert body["risk_level"] == "elevated"
        assert body["signal_created"] is True
        assert body["case_status"] == "pending_review"
        assert body["case_id"] is not None

    async def test_highest_not_blocked_card_auto_escalates(self, client):
        response = await client.post(
            "/checkout",
            json={
                "account_id": "acct_it_2",
                "amount": 999.0,
                "merchant_id": "merch_it",
                "device_context": "new_device",
                "geo_context": "new_or_foreign_location",
                "test_card": "highest_not_blocked",
            },
        )

        body = response.json()
        assert body["charge_succeeded"] is True
        assert body["case_status"] == "auto_escalated"

    async def test_always_blocked_card_never_creates_a_signal(self, client):
        response = await client.post(
            "/checkout",
            json={
                "account_id": "acct_it_3",
                "amount": 5.0,
                "merchant_id": "merch_it",
                "device_context": "new_device",
                "geo_context": "usual_location",
                "test_card": "highest_blocked",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["charge_succeeded"] is False
        assert body["signal_created"] is False
        assert body["case_id"] is None

    async def test_invalid_amount_is_rejected_with_422(self, client):
        response = await client.post(
            "/checkout",
            json={
                "account_id": "acct_it_4",
                "amount": -5,
                "merchant_id": "merch_it",
                "device_context": "known_device",
                "geo_context": "usual_location",
                "test_card": "elevated",
            },
        )

        assert response.status_code == 422
