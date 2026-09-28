# Casework Eval Report

Generated 2026-09-27T20:39:15+00:00 by `scripts/run_eval.py` against `scripts/eval_scenarios.yaml`.

## Headline metrics

- **Completed**: 20/20 scenarios ran without error.
- **Pattern classification accuracy**: 100% (20/20)
- **Route/tier-escalation correctness**: 100% (20/20)
- **False-positive rate on the benign set**: 0% (0/2)
- **Time-to-draft-recommendation** (n=18, elevated/critical scenarios that reached Synthesis): mean 23.5s, median 20.0s, max 73.0s

## Per-pattern breakdown

| Pattern | N | Pattern accuracy | Route accuracy |
|---|---|---|---|
| account_takeover | 4 | 100% | 100% |
| benign | 2 | 100% | 100% |
| card_testing | 5 | 100% | 100% |
| friendly_fraud | 3 | 100% | 100% |
| merchant_fraud | 3 | 100% | 100% |
| mule_activity | 3 | 100% | 100% |

## Per-scenario results

| Scenario | Pattern (expected → actual) | Route (expected → actual) | Tier/route agree | Confidence | Time (s) | Pass |
|---|---|---|---|---|---|---|
| card_testing_01 | card_testing → card_testing | critical → critical | yes | 0.90 | 15.4 | ✓ |
| card_testing_02 | card_testing → card_testing | critical → critical | yes | 0.88 | 20.7 | ✓ |
| card_testing_03 | card_testing → card_testing | critical → critical | yes | 0.93 | 16.6 | ✓ |
| card_testing_04 | card_testing → card_testing | critical → critical | yes | 0.93 | 21.1 | ✓ |
| card_testing_05 | card_testing → card_testing | elevated → elevated | yes | 0.62 | 29.0 | ✓ |
| account_takeover_01 | account_takeover → account_takeover | critical → critical | yes | 0.95 | 14.5 | ✓ |
| account_takeover_02 | account_takeover → account_takeover | critical → critical | yes | 0.96 | 25.6 | ✓ |
| account_takeover_03 | account_takeover → account_takeover | critical → critical | yes | 0.94 | 21.5 | ✓ |
| account_takeover_04 | account_takeover → account_takeover | elevated → elevated | yes | 0.55 | 23.7 | ✓ |
| merchant_fraud_01 | merchant_fraud → merchant_fraud | elevated → elevated | no | 0.91 | 19.1 | ✓ |
| merchant_fraud_02 | merchant_fraud → merchant_fraud | elevated → elevated | no | 0.92 | 38.9 | ✓ |
| merchant_fraud_03 | merchant_fraud → merchant_fraud | elevated → elevated | no | 0.90 | 22.9 | ✓ |
| mule_activity_01 | mule_activity → mule_activity | elevated → elevated | no | 0.92 | 18.0 | ✓ |
| mule_activity_02 | mule_activity → mule_activity | elevated → elevated | no | 0.90 | 14.9 | ✓ |
| mule_activity_03 | mule_activity → mule_activity | elevated → elevated | no | 0.90 | 12.7 | ✓ |
| friendly_fraud_01 | friendly_fraud → friendly_fraud | elevated → elevated | no | 0.85 | 16.2 | ✓ |
| friendly_fraud_02 | friendly_fraud → friendly_fraud | elevated → elevated | no | 0.85 | 19.3 | ✓ |
| friendly_fraud_03 | friendly_fraud → friendly_fraud | elevated → elevated | no | 0.85 | 73.0 | ✓ |
| benign_01 | benign → benign | low → low | yes | 0.75 | 4.9 | ✓ |
| benign_02 | benign → benign | low → low | yes | 0.85 | 3.0 | ✓ |

## Example draft notes

**card_testing_01** (card_testing, critical):
> Account flagged for card testing: 6 transactions across 6 distinct devices within 10 minutes, each at a $1.00 test amount targeting merch_eval_electronics_1. Despite the known-device/usual-location context, this multi-device micro-transaction velocity matches a dedicated card-testing rule (velocity_rule_7), corroborating the triage classification. No prior cases exist for this account or pattern, so this appears to be a first occurrence rather than a repeat offender -- recommend blocking further authorizations pending analyst confirmation.

**card_testing_02** (card_testing, critical):
> Card testing pattern flagged at critical tier (confidence 0.88): 5 transactions in 10 minutes at $0.50 each, but with 11 distinct devices in that window despite the account being tagged 'known_device' -- a classic card-testing signature. Research corroborates this via velocity_rule_7 (pattern-specific card-testing rule), though there's no prior history on this specific account. One similar card_testing case on a different account (acct_eval_card_testing_01) was auto-escalated and remains unresolved, so this may be part of a broader testing campaign worth cross-referencing.

