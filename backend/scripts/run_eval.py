"""Phase 3 eval harness (casework-spec.md §10): runs the 20 hand-labeled
scenarios in scripts/eval_scenarios.yaml through the real pipeline --
Triage/Research/Synthesis run for real, ActionAgent is stubbed so a
critical-route scenario never posts to real Slack -- and scores the
results against ground truth. Writes eval_report.md at the repo root.

Idempotent: deletes any prior source="eval" rows from both cases and
signals_log before running, so re-running never accumulates stale rows or
double-counts a scenario.

Run from backend/: uv run python scripts/run_eval.py [--only <scenario_id>]
Requires ANTHROPIC_API_KEY (and the Postgres/Settings the real agents need)
in the environment, same as any other real-agent script in this project.
"""

import argparse
import asyncio
import statistics
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.entities import CaseSource, Signal, SignalLogEntry
from app.domain.services import CoordinatorError, CoordinatorService
from app.infrastructure.agents import (
    ClaudeResearchAgent,
    ClaudeSynthesisAgent,
    ClaudeTriageAgent,
    StubActionAgent,
)
from app.infrastructure.db.session import close_engine, get_sessionmaker, open_engine
from app.infrastructure.repositories import (
    SqlAlchemyCaseEventsRepository,
    SqlAlchemyCasesRepository,
    SqlAlchemySignalsLogRepository,
)

SCENARIOS_PATH = Path(__file__).parent / "eval_scenarios.yaml"
REPORT_PATH = Path(__file__).parents[2] / "eval_report.md"


@dataclass
class ScenarioResult:
    scenario_id: str
    ground_truth_pattern: str
    ground_truth_route: str
    actual_pattern: str | None = None
    actual_route: str | None = None
    actual_tier: str | None = None
    confidence: float | None = None
    draft_note: str | None = None
    elapsed_seconds: float | None = None
    error_stage: str | None = None
    error_message: str | None = None

    @property
    def errored(self) -> bool:
        return self.error_message is not None

    @property
    def pattern_correct(self) -> bool:
        return not self.errored and self.actual_pattern == self.ground_truth_pattern

    @property
    def route_correct(self) -> bool:
        return not self.errored and self.actual_route == self.ground_truth_route

    @property
    def tier_route_agree(self) -> bool | None:
        if self.errored or self.actual_tier is None or self.actual_route is None:
            return None
        return self.actual_tier == self.actual_route


def _load_scenarios(only: str | None) -> list[dict[str, Any]]:
    with SCENARIOS_PATH.open() as f:
        data = yaml.safe_load(f)
    scenarios: list[dict[str, Any]] = data["scenarios"]
    if only:
        scenarios = [s for s in scenarios if s["id"] == only]
        if not scenarios:
            raise SystemExit(f"No scenario with id {only!r} in {SCENARIOS_PATH}")
    return scenarios


def _build_signal(scenario: dict[str, Any], run_now: datetime) -> Signal:
    raw = scenario["signal"]
    occurred_at = run_now - timedelta(minutes=raw.get("occurred_minutes_ago", 0))
    return Signal(
        signal_id=raw["signal_id"],
        signal_type=raw["signal_type"],
        occurred_at=occurred_at,
        account_id=raw["account_id"],
        upstream_score=raw["upstream_score"],
        flag_reason=raw["flag_reason"],
        payload=raw["payload"],
    )


def _build_prior_entries(
    scenario: dict[str, Any], signal: Signal, run_now: datetime
) -> list[SignalLogEntry]:
    entries = []
    for i, prior in enumerate(scenario.get("prior_signals", [])):
        occurred_at = run_now - timedelta(minutes=prior["minutes_ago"])
        entries.append(
            SignalLogEntry(
                signal_id=prior.get("signal_id", f"{signal.signal_id}_prior_{i}"),
                account_id=prior.get("account_id", signal.account_id),
                device_context=prior.get("device_context", signal.payload.get("device_context")),
                geo_context=prior.get("geo_context", signal.payload.get("geo_context")),
                signal_type=prior.get("signal_type", signal.signal_type),
                occurred_at=occurred_at,
                source=CaseSource.EVAL,
                raw_signal={"synthetic_prior_signal": True, "scenario_id": scenario["id"]},
            )
        )
    return entries


async def _delete_scenario_rows(session: AsyncSession, scenario: dict[str, Any]) -> None:
    main_signal_id = scenario["signal"]["signal_id"]
    prior_ids = [
        prior.get("signal_id", f"{main_signal_id}_prior_{i}")
        for i, prior in enumerate(scenario.get("prior_signals", []))
    ]
    await session.execute(text("DELETE FROM cases WHERE signal_id = :sid"), {"sid": main_signal_id})
    all_ids = [main_signal_id, *prior_ids]
    await session.execute(
        text("DELETE FROM signals_log WHERE signal_id = ANY(:sids)"), {"sids": all_ids}
    )
    await session.commit()


async def _run_scenario(
    session: AsyncSession,
    coordinator: CoordinatorService,
    signals_log_repo: SqlAlchemySignalsLogRepository,
    scenario: dict[str, Any],
    run_now: datetime,
) -> ScenarioResult:
    ground_truth = scenario["ground_truth"]
    result = ScenarioResult(
        scenario_id=scenario["id"],
        ground_truth_pattern=ground_truth["pattern"],
        ground_truth_route=ground_truth["expected_route"],
    )
    signal = _build_signal(scenario, run_now)
    for entry in _build_prior_entries(scenario, signal, run_now):
        await signals_log_repo.log(entry)

    start = time.monotonic()
    try:
        case = await coordinator.handle_signal(signal, source=CaseSource.EVAL)
    except CoordinatorError as exc:
        await session.rollback()
        result.error_stage = exc.stage
        result.error_message = str(exc.original)
        return result
    except Exception as exc:  # noqa: BLE001 -- a bad scenario shouldn't sink the whole run
        await session.rollback()
        result.error_stage = "harness"
        result.error_message = f"{type(exc).__name__}: {exc}"
        traceback.print_exc(file=sys.stderr)
        return result

    result.elapsed_seconds = time.monotonic() - start
    result.actual_pattern = case.pattern
    result.actual_route = case.route.value if case.route else None
    result.actual_tier = case.triage_tier
    result.confidence = case.confidence
    result.draft_note = case.draft_note
    return result


def _render_report(results: list[ScenarioResult]) -> str:
    total = len(results)
    completed = [r for r in results if not r.errored]
    pattern_accuracy = sum(r.pattern_correct for r in results) / total
    route_accuracy = sum(r.route_correct for r in results) / total

    benign = [r for r in results if r.ground_truth_pattern == "benign"]
    fp_count = sum(1 for r in benign if r.errored or r.actual_route != "low")
    fp_rate = fp_count / len(benign) if benign else float("nan")

    timed = [r for r in completed if r.draft_note is not None and r.elapsed_seconds is not None]
    times = [r.elapsed_seconds for r in timed if r.elapsed_seconds is not None]

    df = pd.DataFrame(
        {
            "pattern": [r.ground_truth_pattern for r in results],
            "pattern_correct": [r.pattern_correct for r in results],
            "route_correct": [r.route_correct for r in results],
        }
    )
    per_pattern = df.groupby("pattern").agg(
        n=("pattern", "size"),
        pattern_accuracy=("pattern_correct", "mean"),
        route_accuracy=("route_correct", "mean"),
    )

    lines = [
        "# Casework Eval Report",
        "",
        (
            f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} "
            f"by `scripts/run_eval.py` against `scripts/eval_scenarios.yaml`."
        ),
        "",
        "## Headline metrics",
        "",
        f"- **Completed**: {len(completed)}/{total} scenarios ran without error.",
        f"- **Pattern classification accuracy**: {pattern_accuracy:.0%} ({sum(r.pattern_correct for r in results)}/{total})",
        f"- **Route/tier-escalation correctness**: {route_accuracy:.0%} ({sum(r.route_correct for r in results)}/{total})",
        f"- **False-positive rate on the benign set**: {fp_rate:.0%} ({fp_count}/{len(benign)})",
    ]
    if times:
        lines.append(
            f"- **Time-to-draft-recommendation** (n={len(times)}, elevated/critical "
            f"scenarios that reached Synthesis): mean {statistics.mean(times):.1f}s, "
            f"median {statistics.median(times):.1f}s, max {max(times):.1f}s"
        )
    else:
        lines.append("- **Time-to-draft-recommendation**: no scenario reached Synthesis this run.")

    lines += ["", "## Per-pattern breakdown", "", "| Pattern | N | Pattern accuracy | Route accuracy |",
              "|---|---|---|---|"]
    for pattern, row in per_pattern.iterrows():
        lines.append(f"| {pattern} | {int(row['n'])} | {row['pattern_accuracy']:.0%} | {row['route_accuracy']:.0%} |")

    errors = [r for r in results if r.errored]
    if errors:
        lines += ["", "## Failures", "", "| Scenario | Stage | Error |", "|---|---|---|"]
        for r in errors:
            lines.append(f"| {r.scenario_id} | {r.error_stage} | {r.error_message} |")

    lines += [
        "",
        "## Per-scenario results",
        "",
        "| Scenario | Pattern (expected → actual) | Route (expected → actual) | Tier/route agree | Confidence | Time (s) | Pass |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        passed = "✓" if (r.pattern_correct and r.route_correct) else "✗"
        agree = "—" if r.tier_route_agree is None else ("yes" if r.tier_route_agree else "no")
        confidence = f"{r.confidence:.2f}" if r.confidence is not None else "—"
        elapsed = f"{r.elapsed_seconds:.1f}" if r.elapsed_seconds is not None else "—"
        actual_pattern = r.actual_pattern or ("error" if r.errored else "—")
        actual_route = r.actual_route or ("error" if r.errored else "—")
        lines.append(
            f"| {r.scenario_id} | {r.ground_truth_pattern} → {actual_pattern} "
            f"| {r.ground_truth_route} → {actual_route} | {agree} | {confidence} | {elapsed} | {passed} |"
        )

    examples = [r for r in completed if r.draft_note][:2]
    if examples:
        lines += ["", "## Example draft notes", ""]
        for r in examples:
            lines.append(f"**{r.scenario_id}** ({r.actual_pattern}, {r.actual_route}):")
            lines.append(f"> {r.draft_note}")
            lines.append("")

    return "\n".join(lines) + "\n"


async def main(only: str | None) -> None:
    scenarios = _load_scenarios(only)
    run_now = datetime.now(UTC)

    await open_engine()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        cases_repo = SqlAlchemyCasesRepository(session)
        case_events_repo = SqlAlchemyCaseEventsRepository(session)
        signals_log_repo = SqlAlchemySignalsLogRepository(session)
        coordinator = CoordinatorService(
            cases_repo,
            case_events_repo,
            signals_log_repo,
            ClaudeTriageAgent(),
            ClaudeResearchAgent(get_settings()),
            ClaudeSynthesisAgent(),
            StubActionAgent(),
        )

        if only:
            # A single-scenario rerun (for cheap prompt iteration) must not
            # wipe the rest of a prior full run's results -- scope cleanup
            # to just this scenario's signal_id(s) instead of the blanket
            # delete_by_source used for a full run.
            await _delete_scenario_rows(session, scenarios[0])
        else:
            await cases_repo.delete_by_source("eval")
            await signals_log_repo.delete_by_source("eval")

        results = []
        for i, scenario in enumerate(scenarios, start=1):
            print(f"[{i}/{len(scenarios)}] running {scenario['id']}...", file=sys.stderr)
            result = await _run_scenario(session, coordinator, signals_log_repo, scenario, run_now)
            results.append(result)

    await close_engine()

    report = _render_report(results)
    print(report)
    if only:
        # A single-scenario report isn't the checked-in artifact -- writing
        # it here would clobber the full run's eval_report.md with a 1-row
        # report every time someone iterates on a single scenario.
        print(f"(--only run: not writing {REPORT_PATH} -- rerun without --only to refresh it)", file=sys.stderr)
    else:
        REPORT_PATH.write_text(report)
        print(f"Wrote {REPORT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Run only the scenario with this id")
    args = parser.parse_args()
    asyncio.run(main(only=args.only))
