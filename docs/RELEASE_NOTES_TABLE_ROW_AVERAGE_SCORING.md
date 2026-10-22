# Release notes: results-table scoring by row average

## What changed

**New setting: Threshold Config → Condition Scores → "Table scoring"**

- **Worst row (current):** a results table (oil test results, DGA gases, tan δ rows) counts as one field at its worst row's condition. This is the default and matches the old behaviour.
- **Row average:** the table keeps its field weight, and each evaluated row gets an equal share of it. A table with one breaching row out of six now scores 66.7 (5 × 100 − 100) ÷ 6. Before, it scored −100.

How rows are counted in row-average mode:

- **Threshold tables (DGA, oil, BDV):** one row per table row.
- **Column-rule tables (tan δ, DFR, functional tests):** each row counts once, at its worst cell. A row with more columns does not weigh more.
- **Rows with no status are not counted:** a blank reading, or a row with no threshold.
- **Table-level verdicts count as one extra row:** e.g. a Duval Triangle zone or an aggregate rule that rates the table worse than any of its rows. A DGA table in a Critical Duval zone therefore cannot score 100.
- **Column-level weights inside a table are ignored.** Rows share the table's weight equally.
- **Stored results without row detail** still score as worst row.

**Critical stays Critical.** A CRITICAL row still produces a critical finding, so the asset is still Critical whatever its score.

**Other risk levels follow the new score.** Only CRITICAL rows hold the risk level. A table whose worst row is ALERT now scores from the average of its rows, so the test and the asset can land in a milder band than before: for example, one ALERT row out of ten scores 95 (Low) instead of 50 (Medium). On dev data (13 Oct 2026) Critical / Medium / Low went from 27 / 4 / 24 to 27 / 0 / 28.

**New label: "Critical — by finding"** appears where an asset is Critical because of a finding and not because of its score:

- AI Analytics: the Critical risk sheet (opened from the tile), the drill-down rows, and the equipment detail sheet header
- AI Graph: the equipment detail sheet
- Asset Dashboard: the equipment rows and the detail sheet
- Equipment recommendations popup (equipment actions menu → Recommendations): the risk badge beside the health score

The API now returns a `risk_by_finding` flag on these endpoints:

- `/analytics/dashboard/equipment`
- `/analytics/equipment/{id}/test-types`
- `/analytics/ai-graph/life-left`
- the equipment recommendations endpoint used by that popup

**Fix:** a critical finding for an ALERT table row now reports condition "Fair" instead of always "Poor".

**Fix:** a results table whose overall verdict is worse than any of its rows now gets its own finding, e.g. "DGA Results — Duval zone D2" when a Duval Triangle zone is CRITICAL but the worst gas is only ALERT. Without it, 3 DGA tests on dev data lost Critical under row average. In worst-row mode this only adds the finding to "Why Critical?"; scores and risk levels don't change.

## Deploy steps

1. Deploy the API and run `python alter_health_scoring_config.py`. It creates the `health_scoring_config` table and seeds no row, so behaviour stays "worst row".
2. Deploy the app.
3. To switch modes: an **org admin**, a role with **Threshold Config edit** permission, or a super admin picks "Row average" in Threshold Config. The setting is shared by every organization, so saving it rescores every organization in the background. A manual Recompute All is only needed if that background rescore didn't start (it is logged as a warning).

## Side effects of switching to Row average

- Health scores and the Avg Health Score go up. On dev data (13 Oct 2026, including 3 temporary demo edits) the org average went from 62.1 to 74.9, and tests scoring exactly 0 went from 311 to 71.
- `condition_summary` and the condition-monitoring recommendation follow the score. On dev data, 14 assets got a different recommendation, including assets that are still Critical by finding.
- Department risk levels are worked out from score alone, so they can become milder.
- Tests that couldn't be assessed (no thresholds or blank readings) still score 0. Those are a separate story.

Re-measure the figures above after the demo edits are reverted.
