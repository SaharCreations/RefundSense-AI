# Conservative explanation iteration results

Dense retrieval and the pinned local model are unchanged. The new prompt and
mutually exclusive output schema improve citation precision and abstention,
with a substantial loss of answerable coverage. This is a measured experiment,
not a production-quality claim.

| Metric | Prior original dev | Current original dev | Supplementary heldout | Original heldout regression |
| --- | --- | --- | --- | --- |
| Gold-label citation precision | 14/49 (28.6%) | 11/11 (100.0%) | 4/4 (100.0%) | 2/2 (100.0%) |
| Answer/abstain behavior accuracy | 15/20 (75.0%) | 14/20 (70.0%) | 8/12 (66.7%) | 4/10 (40.0%) |
| Answerable coverage | 15/16 (93.8%) | 10/16 (62.5%) | 4/8 (50.0%) | 2/8 (25.0%) |
| Unknown abstention rate | 0/4 (0.0%) | 4/4 (100.0%) | 4/4 (100.0%) | 2/2 (100.0%) |

All accepted quotations have verbatim support. Current abstentions came from the
model, with no contradictory/invalid output blocks in the final runs. In the
intermediate v3 run, three unknown refusals came from the contradiction guard;
that intermediate result is preserved and not presented as clean model abstention.

The supplementary run answered only four of eight answerable questions. The
original heldout regression answered only two of eight. The model is too
conservative, including on questions with the relevant policy already retrieved.
Do not interpret 100% precision over four supplementary citations as a general
accuracy claim. The original heldout regression's behavior accuracy declined
from 8/10 to 4/10; refusal correctness improved while useful-answer coverage fell.

The supplementary split has 12 synthetic cases and was authored by the
implementer from the same policies, before generation and outside tuning. It
is not independent or blind. Its scores cannot be directly compared with the
old heldout percentages because the questions differ. Original heldout results
are already observed, so their new run is a regression diagnostic only.

| Answerable retrieval metric | Original dev, all iterations | Supplementary heldout | Original heldout regression |
| --- | --- | --- | --- |
| Recall@5 | 0.8125 | 0.8750 | 0.7500 |
| MRR@5 | 0.677083 | 0.750000 | 0.572917 |

Ranked chunk IDs match the previous original-development run exactly. In the
supplementary run, S03 (payment method), S05 (warranty/refund separation) and S07
(superseded status) were refused despite a gold-labeled section appearing in
top-5 retrieval. S08's injection wording also caused a retrieval miss. The
original development run refused Q14, Q22 and Q23 despite gold evidence in
top-5. Selection/answerability quality remains a problem separate from retrieval.

Macro emitted gold-label recall, including refusals as zero, is 0.59375 on
original development, 0.4375 on supplementary heldout and 0.25 on original
heldout regression. These are label-coverage diagnostics, not semantic metrics.
No semantic answer accuracy or citation-entailment metric is invented.

Raw generation, retrieved evidence, attempted protocols and comparison
denominators are preserved under reports/explanation_v2. Earlier reports and
original seed files remain unchanged. Source policies and dense retrieval were
not adapted to the questions. Refund eligibility, dates, amounts and actions
remain SQL-backed and deterministic; explanations cannot approve or execute.

Next: a stronger local selector evaluated on development data against a
predeclared coverage requirement. Keep the planned Next.js/TypeScript frontend
and existing FastAPI/PostgreSQL/LangGraph architecture.

Verification: 157 tests passed, seven native-only PostgreSQL checks remain
pending, and 21 real HTTP checks passed across two Uvicorn processes. The
unknown policy question abstained; SQL assessment amounts were preserved;
explanations created no ledger entries. Human approval later created one demo
ledger refund and repeated requests/recovery did not duplicate it.
