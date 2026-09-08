"""Local dev seed: personas + rules + a couple of already-resolved cases for
the "thin history" personas, so the Research Agent has something real to
find when a demo run reuses these account_ids -- without this, Research
would truthfully report "nothing found" every time, which is correct but
makes for a flat demo.

Personas/rules upsert (safe to re-run). The seed cases are a one-time
insert; re-running skips any that already exist by signal_id rather than
erroring.

Run from backend/: uv run python scripts/seed_dev_data.py
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.domain.entities import Case, CaseSource, CaseStatus, Persona, Resolution, Route, Rule
from app.infrastructure.db.session import close_engine, get_sessionmaker, open_engine
from app.infrastructure.repositories import (
    SqlAlchemyCasesRepository,
    SqlAlchemyPersonasRepository,
    SqlAlchemyRulesRepository,
)

# Must match frontend/src/pages/Checkout.tsx's PERSONAS constant exactly --
# that's what lets a live demo run and this seed data share an account_id.
PERSONAS = [
    Persona(
        account_id="acct_longtenured_1",
        display_name="Long-tenured, low risk",
        tenure_days=2400,
        lifetime_volume_cents=48_000_00,
        prior_case_count=0,
        default_device_context="known_device",
        default_geo_context="usual_location",
    ),
    Persona(
        account_id="acct_newaccount_1",
        display_name="Brand-new account",
        tenure_days=3,
        lifetime_volume_cents=12_000,
        prior_case_count=0,
        default_device_context="new_device",
        default_geo_context="usual_location",
    ),
    Persona(
        account_id="acct_thinhistory_1",
        display_name="Thin history, one cleared case",
        tenure_days=180,
        lifetime_volume_cents=340_000,
        prior_case_count=1,
        default_device_context="known_device",
        default_geo_context="usual_location",
    ),
    Persona(
        account_id="acct_thinhistory_2",
        display_name="Thin history, two cleared cases",
        tenure_days=210,
        lifetime_volume_cents=410_000,
        prior_case_count=2,
        default_device_context="known_device",
        default_geo_context="new_or_foreign_location",
    ),
]

RULES = [
    Rule(
        rule_id="velocity_rule_7",
        pattern="card_testing",
        title="Card testing velocity",
        description="5 or more authorization attempts on the same card range within 10 minutes.",
        active=True,
    ),
    Rule(
        rule_id="new_device_high_value",
        pattern="account_takeover",
        title="New device, high-value transaction",
        description=(
            "A new (never-seen) device completes a high-value transaction within "
            "minutes of a password reset or a streak of failed logins."
        ),
        active=True,
    ),
    Rule(
        rule_id="merchant_chargeback_spike",
        pattern="merchant_fraud",
        title="Merchant chargeback spike",
        description="Chargeback rate at a single merchant spikes well above its historical baseline.",
        active=True,
    ),
    Rule(
        rule_id="mule_rapid_transfer",
        pattern="mule_activity",
        title="Rapid in-and-out transfer",
        description="Funds move into an account from a newly linked source and back out within hours.",
        active=True,
    ),
    Rule(
        rule_id="friendly_fraud_prior_purchase",
        pattern="friendly_fraud",
        title="Dispute with legitimate purchase history",
        description="A chargeback is filed on an account with an established history of legitimate purchases at the same merchant.",
        active=True,
    ),
    Rule(
        rule_id="general_review",
        pattern=None,
        title="General manual review",
        description="Signal doesn't cleanly match a known pattern but crossed the upstream review threshold; route for manual judgment.",
        active=True,
    ),
]


def _cleared_case(*, account_id: str, pattern: str, days_ago: int) -> Case:
    occurred_at = datetime.now(UTC) - timedelta(days=days_ago)
    return Case(
        signal_id=f"sig_seed_{account_id}_{days_ago}d",
        account_id=account_id,
        signal_type="transaction",
        occurred_at=occurred_at,
        upstream_score=0.55,
        flag_reason="ml_score_0.55",
        payload={"amount": 42.50, "seed": True},
        pattern=pattern,
        triage_tier="elevated",
        confidence=0.55,
        entities={"account_id": account_id},
        matched_rules=[],
        similar_cases=[],
        evidence=["seed data: no prior cases at the time"],
        risk_score=0.3,
        recommended_action="clear",
        draft_note=f"[seed] Reviewed and cleared -- no fraud found for {account_id}.",
        route=Route.ELEVATED,
        status=CaseStatus.CLOSED,
        resolution=Resolution.DENIED,
        source=CaseSource.BULK_SYNTHETIC,
    )


SEED_CASES = [
    _cleared_case(account_id="acct_thinhistory_1", pattern="merchant_fraud", days_ago=40),
    _cleared_case(account_id="acct_thinhistory_2", pattern="account_takeover", days_ago=75),
    _cleared_case(account_id="acct_thinhistory_2", pattern="account_takeover", days_ago=20),
]


async def main() -> None:
    await open_engine()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        personas_repo = SqlAlchemyPersonasRepository(session)
        rules_repo = SqlAlchemyRulesRepository(session)
        cases_repo = SqlAlchemyCasesRepository(session)

        for persona in PERSONAS:
            await personas_repo.upsert(persona)
        await session.commit()
        print(f"Upserted {len(PERSONAS)} personas.")

        for rule in RULES:
            await rules_repo.upsert(rule)
        await session.commit()
        print(f"Upserted {len(RULES)} rules.")

        created, skipped = 0, 0
        for case in SEED_CASES:
            try:
                await cases_repo.create(case)
                await session.commit()
                created += 1
            except IntegrityError:
                await session.rollback()
                skipped += 1
        print(f"Seed cases: {created} created, {skipped} already present.")

    await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
