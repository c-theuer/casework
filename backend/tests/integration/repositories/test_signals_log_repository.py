from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from app.domain.entities import CaseSource, SignalLogEntry


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(signals_log_repo):
    yield
    await signals_log_repo.delete_by_source(CaseSource.INTEGRATION_TEST.value)
    await signals_log_repo.delete_by_source(CaseSource.EVAL.value)


def make_signal_log_entry(**overrides) -> SignalLogEntry:
    defaults = dict(
        signal_id=f"sig_repo_it_{uuid4().hex}",
        account_id="acct_repo_it",
        device_context="known_device",
        geo_context="usual_location",
        signal_type="transaction",
        occurred_at=datetime.now(UTC),
        source=CaseSource.INTEGRATION_TEST,
        raw_signal={},
    )
    defaults.update(overrides)
    return SignalLogEntry(**defaults)


@pytest.mark.asyncio
class TestSignalsLogRepository:
    async def test_log_persists_and_returns_the_entry(self, signals_log_repo):
        entry = await signals_log_repo.log(make_signal_log_entry(signal_id="sig_repo_it_log_1"))

        assert entry.signal_id == "sig_repo_it_log_1"
        assert entry.account_id == "acct_repo_it"

    async def test_log_is_idempotent_on_signal_id(self, signals_log_repo):
        first = await signals_log_repo.log(
            make_signal_log_entry(signal_id="sig_repo_it_dupe", account_id="acct_first")
        )
        second = await signals_log_repo.log(
            make_signal_log_entry(signal_id="sig_repo_it_dupe", account_id="acct_second")
        )

        # ON CONFLICT DO NOTHING -- the second log() call is a no-op against
        # the already-committed row, so the first call's account_id wins.
        assert first.account_id == "acct_first"
        assert second.account_id == "acct_first"

    async def test_count_recent_counts_within_the_window_by_account_id(self, signals_log_repo):
        now = datetime.now(UTC)
        await signals_log_repo.log(
            make_signal_log_entry(
                signal_id="sig_repo_it_recent_1", account_id="acct_repo_it_velocity", occurred_at=now
            )
        )
        await signals_log_repo.log(
            make_signal_log_entry(
                signal_id="sig_repo_it_recent_2", account_id="acct_repo_it_velocity", occurred_at=now
            )
        )

        count = await signals_log_repo.count_recent(
            account_id="acct_repo_it_velocity", within_minutes=10, now=now
        )

        assert count == 2

    async def test_delete_by_source_removes_only_matching_rows(self, signals_log_repo):
        integration_entry = await signals_log_repo.log(
            make_signal_log_entry(
                signal_id="sig_repo_it_del_1",
                account_id="acct_repo_it_del_integration",
                source=CaseSource.INTEGRATION_TEST,
            )
        )
        eval_entry = await signals_log_repo.log(
            make_signal_log_entry(
                signal_id="sig_repo_it_del_2", account_id="acct_repo_it_del_eval", source=CaseSource.EVAL
            )
        )

        await signals_log_repo.delete_by_source("eval")

        remaining_count = await signals_log_repo.count_recent(
            account_id=integration_entry.account_id, within_minutes=10_000
        )
        assert remaining_count == 1

        deleted_count = await signals_log_repo.count_recent(
            account_id=eval_entry.account_id, within_minutes=10_000
        )
        assert deleted_count == 0
