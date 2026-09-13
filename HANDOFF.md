# BUY OR WAIT — AGENT HANDOFF

> **IMPORTANT:** Every new agent must read this file FIRST before inspecting the project.

This file is the single source of truth for the current development state.

Do not assume previous work is complete.

Do not scan the entire repository unless necessary.

Start from the current phase below.

---

# 1. PROJECT

**Project:** Buy or Wait? (HackerRank Orchestrate, September 2026)

**Goal:** Build an AI-powered financial affordability agent that processes
`dataset/requests.csv` (250 rows) and produces `output.csv` at the repo root.

**Deadline:** 2026-09-13 18:00 IST.

**Repo layout:** everything lives in `hackerrank-orchestrate-september26-main/`
(`AGENTS.md`, `problem_statement.md`, `code/`, `dataset/`, `tests/`, `evaluation/`).

---

# 2. CURRENT STATUS

## Current Phase

```text
COMPLETE — all 10 phases done; scorecard calibrated (104/150); submission packaged
```

## Overall Progress

```text
[x] Phase 1 — Project Setup & Dataset Understanding
[x] Phase 2 — Financial Data Reconstruction
[x] Phase 3 — Message & Image Intelligence
[x] Phase 4 — Currency & Financial State Normalization
[x] Phase 5 — 90-Day Financial Forecast Engine
[x] Phase 6 — Payment Plan Generator
[x] Phase 7 — Safety Validator & Plan Ranking
[x] Phase 8 — Orchestrator Agent & Decision Explanation
[x] Phase 9 — Sample Validation harness + calibration sweeps
[x] Phase 10 — Full 250-row run -> output.csv, zero validation violations
[x] Phase 10 polish — projection model calibrated (104/150), code.zip packaged
```

Note: `python code/main.py` produces the complete submission
(`output.csv` at repo root + `dataset/output.csv` + `evaluation/usage_report.md`),
passing every Phase 10 hard check with zero violations. `code.zip` is
assembled. The residual accuracy gap is the `amount_safe_to_pay` number
formula (section 8); the three structural levers that were findable have
been applied and measured.

---

# 3. WHAT HAS BEEN COMPLETED

```text
All 10 phases complete. 26/26 unit tests pass. Full run: 250/250 rows,
0 errors, 0 validation violations. Scorecard improved to status 20/25
method 21/25 plan 20/25 earliest 18/25 changes 21/25 amount 4/25
(total 104/150, up from 97).
OCR cache built (16/16 blank-amount images resolved).
AGENTS.md log.txt compliance active. code.zip packaged, secret-scan clean.
```

Remaining work: none blocking. Only optional amount-formula polish remains
(section 8); packaging is done.

---

# 4. CURRENT WORK

## Current Phase

```text
PHASE 9/10 REFINEMENT
```

## Current Objective

None critical — the project is submission-ready. Optional residual polish:
the `amount_safe_to_pay` formula (4/25; see section 8 for what has been
measured and exhausted).

## Current Agent Task

If more accuracy is wanted:

1. Run `python tests/sample_scorecard.py` and read the mismatch table.
2. Re-run `python tests/matrix_probe.py` (guard x coverage x estimator
   matrix) before proposing any new estimator — it reproduces every
   measured config in one shot.
3. The three structural levers are already applied (salary 1-month gate,
   no double-count guard, upper-middle per-event median). Remaining ideas
   are in section 8; expect diminishing returns.
4. Re-run `python code/main.py` after any change (rebuilds output.csv +
   usage report + validation in one shot), then refresh
   `dataset/output.csv` (manual copy; main.py does not write it).
5. Rebuild code.zip if code changed; update this HANDOFF when finished.

---

# 5. FILES CREATED

```text
code/config.py                       paths, constants, model costs
code/main.py                         entry point (python code/main.py --audit)
code/data/types.py                   Profile/Event/Request/PaymentOption/Message/ImageLink/ResolvedEvent/FinancialState
code/data/loader.py                  stdlib CSV loaders + parse helpers + dataset_summary() audit
code/data/chain_resolution.py        5-pattern linked-event resolution
code/data/state_builder.py           DataStore: indexed dataset + per-user chain resolution + build_state()
code/evaluation/token_ledger.py      append-only CSV ledger + usage_report.md writer
code/evaluation/llm_client.py        shared LLM wrapper (stdlib urllib; logs to ledger; None => fallback)
code/interpret/message_interpreter.py multilingual (en/id) message facts + injection tripwire
code/interpret/image_interpreter.py  OCR chain + cache + optional OpenAI vision path
code/interpret/ocr_extract.py        marker-aware amount/date extraction (western/Indian/dotted-Indian/European numbers)
code/finance/currency.py             FxGraph: directional dated FX, multi-hop, nearest-earlier fallback (logged)
code/finance/normalizer.py           classification, month-total recurrence, fact application, timeline
code/finance/forecast.py             deterministic 90-day engine (build_movements/balance_path/forecast_finances)
code/finance/payment_plans.py        CandidatePlan generator with eligibility trails
code/validate/plan_ranker.py         spec-order ranking + Decision mapping
code/validate/output_validator.py    Phase 10 hard checks (zero-violation bar)
code/orchestrator.py                 Phase 8: per-request flow + row + explanation
tests/test_phases_1_3.py             loader/chain/interpreter unit tests
tests/test_phases_4_7.py             FX/forecast/plan/ranker unit tests
tests/run_tests.py                   stdlib test runner (pytest CANNOT run here - see section 8)
tests/sample_scorecard.py            25-sample ground-truth harness -> tests/sample_scorecard.md
tests/trough_solver.py               brute-force category-set solver vs implied troughs
tests/trough_probe.py                trough under estimator variants per sample
tests/calibration_sweep.py           full-pipeline sweep: estimator x salary cap
output.csv                           FULL-DATASET PREDICTIONS (repo root, 250 rows)
tests/recurrence_probe.py            coverage x estimator matrix harness (Phase 9)
tests/guard_probe.py                 double-count-guard on/off harness (Phase 9)
tests/matrix_probe.py                combined guard x coverage x estimator matrix
code.zip                             submission package (code/tests/eval/docs)
evaluation/ocr_cache.json            OCR text cache for the 16 images (69s -> instant)
evaluation/token_ledger.csv          running ledger (302 zero-cost rows: heuristic + local OCR)
evaluation/usage_report.md           final-run report (regenerated by python code/main.py)
log.txt                              AGENTS.md transcript (gitignored, never commit)
```

Also written by the run: `dataset/output.csv` (template location copy).
No dataset file was ever modified (output.csv template is a deliverable).

---

# 6. FILES MODIFIED BY CURRENT AGENT

```text
code/main.py               full-run entry (run_full + --limit), audit kept
code/validate/plan_ranker.py   method-independent amount + base earliest
                               + not_recommended rows carry headroom
code/finance/payment_plans.py  spending-change rewrite (flexibility-driven
                               action type, minimum_allowed_amount floors,
                               greedy multi-change combos) + rep-event fix
code/finance/normalizer.py     AMOUNT_VARIANT knob (default nPm) + stats import
code/finance/forecast.py       SALARY_MONTHS_CAP knob + build_movements param
code/finance/currency.py       failed-hop returns None (consistency fix)
README.md                  Solution section (run commands + architecture)
HANDOFF.md (this file)
log.txt (per AGENTS.md §5)
dataset/output.csv         filled with the run's predictions (deliverable)
```

---

# 7. TEST STATUS

## Tests

```text
26 unit tests in tests/test_phases_1_3.py and tests/test_phases_4_7.py
Sample scorecard: tests/sample_scorecard.py (25 solved examples)
Phase 10 validator: runs automatically after python code/main.py
```

## Last Test Command

```text
python code/main.py
python tests/run_tests.py
python tests/sample_scorecard.py
```

## Result

```text
Unit tests: passed=26 failed=0 errors=0
Full run: 250/250 rows, 0 errors, VALIDATION: zero violations
Output distribution: affordable_now 71 | with_plan 72 | later 58 |
  not_affordable 49; methods full 74 / installments 63 / wait 58 /
  not_recommended 49 / partial 6
Scorecard (latest):
  affordability_status:            20/25
  recommended_payment_method:      21/25
  amount_safe_to_pay:               4/25   <- residual open problem
  payment_plan:                    20/25
  earliest_date_for_full_payment:  18/25
  spending_changes_needed:         21/25
Audit: INTEGRITY OK; ledger 302 calls, all zero-cost local OCR/heuristic.
```

---

# 8. KNOWN PROBLEMS

```text
- [HIGH->REDUCED] amount_safe_to_pay now matches 4/25 samples (was 3/25);
  structural fields 18-21/25 -> 20-21/25 after the three calibrated levers
  below. Established facts about the formula (measured, do not re-derive):
  * It is METHOD-INDEPENDENT: not_recommended rows carry positive headroom
    (request_05: 737 with status not_affordable; request_14: 597.74 with
    explanation 'Although EUR 597.74 is available today, the full amount
    cannot be completed safely').
  * It equals today's headroom WITHOUT spending changes, capped at
    requested (request_06: 603.30 < requested 620.40 even though the
    recommended plan pays in full AFTER stopping event_476; request_11:
    12,510,645 < requested 13,110,000 with a reduce_to winning plan).
  * Implied trough = keep + amount exactly on 21 samples -> the formula is
    min(path) - keep under THEIR projection model; the gap is the model,
    not the semantics.
  * 2026-09-13 (Buffy #2) EXHAUSTIVE MODEL SEARCH - all negative:
    - tests/model_fitter.py: 147-model grid (7 amount estimators x 6
      timing schedules x 3 category scopes) -> ZERO exact trough fits
      across the 21 uncapped samples (all 4 capped samples satisfy the
      lower bound under aggressive models; the capped set is exactly the
      set where ours already equals requested: r01/r09/r12/r16).
    - tests/outflow_probe.py: whole-outflow formulas (any single
      historical month total, trailing 1..120-day actual outflow, minus
      k salaries, med/mean/min/max month totals minus k salaries) ->
      ZERO exact fits on all 21.
    - tests/deduction_solver.py: bitset subset-sum over ~200 blocks
      (category variants x month counts x ceil/round, raw event amounts,
      recent totals, salary/pending credits) -> every D reachable, i.e.
      NON-IDENTIFYING; the exact GT projection is not recoverable by
      combinatorial fitting either.
    - Fractional cents analysis: D has nonzero cents on r05/r06/r13/r20/
      r23 (e.g. .10, .12, .05) -> their model uses per-event amounts and
      exact dates, not rounded monthly totals; r13/r15 expected values
      equal balance - keep - MEAN of per-event spend within .01 ->
      continuous spend estimate, likely daily-rate x elapsed days.
    - CONCLUSION: reproducing their troughs requires a different (likely
      daily-rate) spend model whose exact form is not identifiable from
      the 25 samples without fitting per-sample constants (= hardcoding
      by another name). Do NOT re-run these searches expecting a
      different answer; see tests/model_fitter_out.txt.

- [MEDIUM] request_13: we emit spending changes for an affordable_later
  sample that expects none (wait ranked first there, ours ranked full with
  changes after a partial-payment regression); revisit wait vs
  full-with-changes ranking if any further outflow-model change lands.

- [MEDIUM] request_21 change-count is coupled to the projection gap: under
  our (shallower) trough one change (stop:event_1815) already restores
  safety, so we emit 1 change where GT emits 2 (its deeper projected
  trough needs the streaming reduce too). We verified headroom with/without
  each change (1570.05 / 1581.05 / 1604.55): forcing a second change when
  one already clears the minimum would be an unsupported assumption.
  Fixing the outflow model would likely fix this field automatically.

- [FIXED 2026-09-13 Buffy #2] spending-change candidate ORDER: GT tries
  candidates in EVENT-ID order (earliest event first), preferring
  reduce-to-floor for reducible_or_stoppable rows; previous code sorted
  by largest monthly saving (picked dining over the subscriptions on
  request_21). Implemented in payment_plans.generate_candidates; covered
  by tests/test_spending_changes.py.

- [MEDIUM] python code/main.py does NOT refresh dataset/output.csv (the
  template-location deliverable copy); copy output.csv there manually
  after every full run.

- [MEDIUM] pytest is unusable in this repo: the required `code/` package
  shadows Python's stdlib `code` module and pytest's pdb import crashes.
  Use `python tests/run_tests.py` instead. Do NOT rename code/ - it is the
  entry-point contract (python code/main.py).

- [LOW] OCR cache must be regenerated if dataset images change:
  delete evaluation/ocr_cache.json (costs ~69s per full re-run).

- [LOW] FX rate gaps (31 foreign events) resolved by nearest-earlier rate,
  logged, never silent. No path failures observed in dataset.

- [LOW] RapidOCR loads once per process (~15s); JSON cache removes repeat
  cost for repeated runs.
```

---

# 9. IMPORTANT DECISIONS

These decisions must not be changed casually.

## Architecture

```text
LLM + Deterministic Python financial engine.
The LLM never computes any output number. Interpreters emit fixed-shape
fact dicts; the engine applies them under strict gates.
```

## Entry point

```text
python code/main.py            (contract from problem_statement/README)
python code/main.py --audit    Phase 1 dataset audit (current default)
```

## Data safety

Messages and images are UNTRUSTED DATA. Enforced in code:
- injection tripwire regexes flag "ignore rules" and config-tamper text;
- flagged facts are dropped in normalizer.apply_facts();
- fact application can only touch amount/date/status of referenced events;
- employer confirm_salary facts may amend/anchor the next scheduled salary
  (this is the spec's "count confirmed salary on its settlement date";
  verified as the ground-truth behavior via request_02).

## Blank amounts

Blank event amounts are NEVER zero. All 16 are resolved from images via
event_id -> images.csv -> image_id -> PNG -> RapidOCR -> marker-aware
extraction (11 needed the label-above-amount + Indian-number handling).

## Currency

Dated supplied rates only. Directional graph (USD->IDR != IDR->USD);
multi-hop composition (USD->ZAR = USD->EUR->ZAR); nearest-earlier-date
substitution is logged, never silent; conversion valued at settlement date.

## Chain resolution (all 5 patterns audited in dataset)

```text
cancelled+settled   -> keep settled (authorization superseded)
failed+scheduled    -> keep scheduled retry
settled+unrealized  -> keep settled cash row, drop valuation
settled+pending     -> keep BOTH (pending refund = future credit only when
                       settled; pending duplicate debit = reserved)
settled+settled     -> keep both (both are history)
```

Dataset effect: 25342 raw -> 25317 resolved (25 rows collapsed, 58 chains).

## Forecast

90-day daily balance path from current balance; counts scheduled salary +
cadence continuation, reserves pending/scheduled debits, projects
recurring + variable spending from month-total medians (>= 2 months of
evidence), ignores pending credits/failed/cancelled/unrealized.
max_safe_today = min(path) - minimum_balance_to_keep (exact, no search:
paying X today shifts the whole path down by X).

## amount_safe_to_pay (Phase 9-validated semantics)

```text
amount = clamp(min(path of BASE no-change forecast) - minimum_balance,
               0, requested_amount)
Method-independent: applies to every row, including not_recommended.
earliest_date_for_full_payment always comes from the same base scan,
except affordable_now rows pin it to request_date (spec rule).
```

## Spending-change plans (Phase 9-validated)

```text
Action type follows the event rows' flexibility: 'stoppable' -> stop;
'reducible'/'reducible_or_stoppable' -> reduce_to at the event's
minimum_allowed_amount (its floor), never an invented percentage.
Multiple changes combine greedily (largest monthly saving first, max 3)
until full payment today is safe. Representative event id = most recent
settled debit of the category (any cadence category, not just recurring
class). Changes are generated even when a plain full plan already looks
safe IF the base headroom < requested (that is what request_06/21 show).
```

## Projection estimator (calibrated)

```text
AMOUNT_VARIANT = 'nPm' (upper-middle per-event amount x events/month)
chosen by full-pipeline sweeps (7 estimators x 5 salary caps, then the
matrix probes). Salary projects from >= 1 month of history; expenses
still need >= 2. No double-count guard between scheduled rows and
cadence projection. Knobs live in code/finance/normalizer.py and
code/finance/forecast.py; harnesses: tests/calibration_sweep.py,
tests/recurrence_probe.py, tests/guard_probe.py, tests/matrix_probe.py.
A 147-model grid (tests/model_fitter.py) later confirmed no category-
monthly model reproduces the GT troughs exactly - see section 8 before
proposing new estimators.
```

## Spending-change candidate order (2026-09-13 Buffy #2)

```text
Candidates accumulate in EVENT-ID order (earliest first; numeric id
parse), preferring reduce-to-floor for reducible_or_stoppable rows;
search stops as soon as full payment is safe (max 3 changes). Evidence:
request_21 (stop event_1815 then reduce event_1816), request_06 (stop
only), request_11 (reduce dining to its floor). Covered by
tests/test_spending_changes.py (3 tests, 29 total in run_tests.py).
```

## Ranking (spec order, implemented)

```text
1 completes by deadline  2 no spending changes  3 lowest total paid
4 starts earlier         5 fewer payments       6 lowest payment_option_id
```

---

# 10. NEXT AGENT INSTRUCTIONS

The next agent should **NOT start by reviewing the entire project**.

Start with:

```text
1. Read HANDOFF.md (this file)
2. Read section 8 (KNOWN PROBLEMS) - the amount formula is the only
   residual task, and much has been measured/exhausted already
3. Read IMPLEMENTATION_PLAN_V2.md Phase 8 (orchestrator) + Phase 9/10
4. Run: python tests/run_tests.py && python tests/sample_scorecard.py
5. Re-run python tests/matrix_probe.py before proposing any new
   estimator - it reproduces every measured config in one shot
6. Read tests/sample_scorecard.md mismatch details
7. Continue only if a change measures better on the scorecard without
   breaking the 26 unit tests
```

Only inspect other project files if the current task requires them.

Key APIs (all import from `code.*` with repo root on sys.path):

```python
from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image
from code.finance.payment_plans import generate_candidates
from code.validate.plan_ranker import decide

ds = DataStore()                      # load once, reuse
fx = FxGraph(ds.rates)
req = ds.request_by_id("request_26")  # works for eval + sample ids
state = ds.build_state(req)
facts = [interpret_message(m, request_id=req.request_id) for m in state.messages]
facts += [interpret_image(i, request_id=req.request_id) for i in state.image_links]
norm = normalize_state(state, fx, facts)
plans = generate_candidates(state, norm)
decision = decide(state, norm, plans)
```

---

# 11. HANDOFF PROCEDURE

Before an agent finishes its work, it MUST update this file.

The agent must update:

```text
CURRENT STATUS
WHAT HAS BEEN COMPLETED
CURRENT WORK
FILES CREATED
FILES MODIFIED
TEST STATUS
KNOWN PROBLEMS
IMPORTANT DECISIONS
NEXT AGENT INSTRUCTIONS
```

And append a per-turn entry to `log.txt` (AGENTS.md §5.2, `tool=` mandatory).

---

# 12. PHASE COMPLETION FORMAT

When a phase is completed, change:

```text
[ ] Phase X
```

to:

```text
[x] Phase X
```

Then update:

```text
Current Phase
```

to the next phase.

---

# 13. COMPLETED PHASE LOG

## Phase 1

### Status

```text
COMPLETE
```

### Completed Work

```text
Project structure (code/data, code/interpret, code/finance, code/validate,
code/evaluation, tests). All 8 dataset files load via stdlib csv into typed
dataclasses. Dataset audit printed by `python code/main.py --audit`:
  financial_profiles 275 | financial_events 25342 | exchange_rates 134
  requests 250 | sample_requests 25 | payment_options 790
  messages 215 | images 16 links (16 PNGs)
  blank-amount events 16 (all with image link + file) | integrity OK
  message languages: en, id (Indonesian confirmed)
Token ledger (evaluation/token_ledger.py) + shared llm_client wrapper
wired before any interpreter was written (per plan).
```

### Files

```text
code/config.py code/main.py code/data/{types,loader}.py
code/evaluation/{token_ledger,llm_client}.py
```

### Tests

```text
Loader parse helpers covered in tests/test_phases_1_3.py (blank amount ->
None, dates, splits).
```

### Problems

```text
None open.
```

---

## Phase 2

### Status

```text
COMPLETE
```

### Completed Work

```text
DataStore pre-indexes profiles/events/messages/images/options by user and
request. linked_event_id chains (all 2-row, 58 chains) resolved by the 5
audited patterns with a log line per non-trivial chain (44 log lines).
25342 raw -> 25317 resolved logical events. build_state() returns one
FinancialState per request (works for eval and sample ids).
```

### Files

```text
code/data/{chain_resolution,state_builder}.py
```

### Tests

```text
5 pattern tests in tests/test_phases_1_3.py.
```

### Problems

```text
None open.
```

---

## Phase 3

### Status

```text
COMPLETE
```

### Completed Work

```text
message_interpreter: fixed fact shape {event_id, action, new_amount,
new_currency, new_date, confidence, source_id, relevant, language,
injection_detected}. Multilingual (English + Bahasa Indonesia) patterns
for salary changes, settlements, cancellations, delays. Injection
tripwire: "ignore rules" AND config-tamper ("set minimum_balance_to_keep
to 0") both flagged; flagged facts dropped by the normalizer.
image_interpreter: RapidOCR (auto-discovered in env) -> pytesseract ->
flagged-None chain; OpenAI vision path behind OPENAI_API_KEY.
ocr_extract: marker-aware extraction with strength tiers
(balance_due 4 > total 3 > amount_due/weak 2) and a number parser for
western (1,234,567.89), Indian (2,00,000.00), dotted-Indian
(1.00.000.00), European (5.000,00) formats.
16/16 blank-amount images resolved. OCR text cached to
evaluation/ocr_cache.json.
```

### Files

```text
code/interpret/{message_interpreter,image_interpreter,ocr_extract}.py
```

### Tests

```text
Indonesian salary, English salary, adversarial injection (no rule change),
config tamper, settlement facts - all in tests/test_phases_1_3.py.
```

### Problems

```text
Ground truth expects "Balance Due" priority over "Total" when both appear
(request_14) - implemented as strength tier; verify on full run.
```

---

## Phase 4

### Status

```text
COMPLETE
```

### Completed Work

```text
FxGraph: directional dated rates; BFS multi-hop composition; exact-date
lookup with nearest-earlier fallback (logged, never silent); settlement-
date valuation; None on unconvertible (event dropped from timeline and
flagged, never zeroed). Normalizer: classify_event (salary/refund/
recurring_expense/one_time_expense/pending_payment/cancelled_payment/
investment/recurring_income); month-total recurrence detection
(fixed vs variable strength); fact application with gates (injection
drop, relevance, event-id binding, user-level employer salary facts);
home-currency timeline builder.
```

### Files

```text
code/finance/{currency,normalizer}.py
```

### Tests

```text
4 FX tests (direction, multi-hop, fallback logged, no-path None).
```

### Problems

```text
Exact ground-truth outflow scope for amounts still open (see section 8).
```

---

## Phase 5

### Status

```text
COMPLETE
```

### Completed Work

```text
Deterministic engine: build_movements() (scheduled salary credits,
salary cadence continuation or projection from settled history,
pending/scheduled debit reservation, recurring + variable category
projection, double-count guard per calendar month), balance_path()
(daily balances + suffix-minimum), forecast_finances() (safe flag,
first breach date, exact max_safe_today = min(path) - keep, earliest
full-payment date via suffix-min scan). Pure functions, no LLM/network.
```

### Files

```text
code/finance/forecast.py
```

### Tests

```text
Hand-verified cases: safe plan, breach on payment day, exact headroom,
headroom capped by window minimum, rent-before-salary dip.
```

### Problems

```text
None open (accuracy tuning tracked in section 8).
```

---

## Phase 6

### Status

```text
COMPLETE
```

### Completed Work

```text
generate_candidates() emits typed CandidatePlans with eligibility trails:
full_payment (method-gated, forecast-checked), partial_payment (request
flag + method + 0 < today < requested + remainder by deadline), installments
(ONLY from supplied options; implied months vs max_installment_months;
blank max_installment_months disqualifies), wait (first safe full date;
only if user considers full_payment), spending-change plans (user's
reducible/stoppable categories, never protected, one change per plan -
validated against samples). Each plan records which rule fired (trail).
```

### Files

```text
code/finance/payment_plans.py
```

### Tests

```text
Covered indirectly through ranker tests + scorecard.
```

### Problems

```text
request_06/21 expect spending-change plans to WIN over plain full_payment;
ranker currently prefers the plain plan (see section 8).
```

---

## Phase 7

### Status

```text
COMPLETE (code) - accuracy tied to Phase 9 tuning
```

### Completed Work

```text
rank_plans(): deterministic spec-order sort; drops ineligible/unsafe.
decide(): maps the winner to output fields with per-method
amount_safe_to_pay semantics (full = requested; partial = first payment;
installments/spending-changes = residual headroom under plan; wait =
base headroom) and explanation facts citing real figures.
```

### Files

```text
code/validate/plan_ranker.py
```

### Tests

```text
5 ranker tests: deadline first, no-changes second, cheaper third,
option-id final tie-break, ineligible/unsafe dropped.
```

### Problems

```text
amount_safe_to_pay formula remains the dominant gap (3/25).
```

---

## Phase 8

### Status

```text
COMPLETE
```

### Completed Work

```text
code/orchestrator.py: process_request() wires P2 state -> P3 interpreters
-> P4 normalize -> P5/P6 candidates (forecast-validated) -> P7 decide ->
8-column row. Deterministic template explanation citing only already-
computed figures (pay/wait/installments sentence + forecast-fact clause
+ spending-change clause); LLM/Python boundary honored (no model call can
change a number; the deterministic path is the only path today).
code/main.py: run_full() batch runner with per-request error isolation
(fallback not_affordable row, never aborts the batch) and --limit flag.
```

### Files

```text
code/orchestrator.py code/main.py
```

### Tests

```text
Full run on 250 requests: 0 errors. Row-level checks in the Phase 10
validator (below) all pass.
```

### Problems

```text
None open.
```

---

## Phase 9

### Status

```text
COMPLETE (harness + calibration rounds; amount formula still open)
```

### Completed Work

```text
tests/sample_scorecard.py + sample_scorecard.md (field accuracy + per-
request mismatches). Method-independent amount semantics implemented and
sample-validated (request_05/14 evidence). Spending-change generator
rewritten to ground-truth semantics (flexibility-driven action type,
minimum_allowed_amount floors, greedy multi-change combos). Amount
estimator calibrated by full-pipeline sweep (7 x 5 combos): nPm wins.
Salary-cap knob wired but left unlimited. Trough analysis harnesses
(trough_solver, trough_probe) document why the exact outflow model
remains unidentified (5/21 exact fits).
```

### Files

```text
tests/sample_scorecard.py tests/sample_scorecard.md
tests/trough_solver.py tests/trough_probe.py tests/calibration_sweep.py
code/validate/plan_ranker.py code/finance/payment_plans.py
code/finance/normalizer.py code/finance/forecast.py
```

### Tests

```text
26/26 unit tests still pass after every change; scorecard improved from
(17,19,18,15,22) to (18,20,19,16,21) on status/method/plan/earliest/changes.
```

### Problems

```text
amount_safe_to_pay 3/25 (section 8 has all measured evidence).
```

---

## Phase 10

### Status

```text
COMPLETE (run + validation + packaging)
```

### Completed Work

```text
code/validate/output_validator.py implements every planned hard check:
columns/order, 0<=amount<=requested, enums, affordable_now->request_date,
plan chronology, partial_payment exactly-2-summing rule, installments
exactly-match-a-supplied-option, spending-change target validity +
stop/reduce mutual exclusion, duplicate ids, one row per input row.
python code/main.py: 250/250 rows, 0 errors, ZERO violations.
output.csv at repo root; copy at dataset/output.csv.
evaluation/usage_report.md regenerated from the final run (302 calls,
0 tokens, $0.00 - all local OCR/heuristic). Secret scan clean.
```

### Files

```text
code/validate/output_validator.py output.csv dataset/output.csv
evaluation/usage_report.md README.md
```

### Tests

```text
Validator runs as part of python code/main.py (zero violations).
```

### Problems

```text
None open. (code.zip assembled 2026-09-13, secret-scan clean.)
```

---

# 14. FINAL PROJECT STATE

This section is updated only near the end.

## Final Architecture

```text
LLM + deterministic Python engine; the deterministic path is the only
active path (no API key needed). Per request:
DataStore.build_state -> interpret_message/interpret_image ->
normalize_state (FX + classification + facts) -> generate_candidates
(forecast-validated) -> decide (rank + Decision) -> orchestrator row +
explanation -> output.csv (validate_output_file hard checks).
```

## Final Entry Point

```text
python code/main.py   (writes output.csv at repo root + dataset/output.csv,
                       regenerates evaluation/usage_report.md, runs the
                       Phase 10 validator; --audit and --limit N also exist)
```

## Final Output

```text
output.csv: 250 rows + header, exact column order, zero validation
violations. Distribution: affordable_now 73, affordable_with_plan 70,
affordable_later 55, not_affordable 52.
```

## Full Dataset Test

```text
python code/main.py -> 250/250 rows, 0 pipeline errors, VALIDATION: zero
violations. Unit tests: python tests/run_tests.py -> 26/26. Refresh
dataset/output.csv manually after runs (see section 8).
```

## Evaluation

```text
Sample scorecard: status 20/25 method 21/25 amount 4/25 plan 20/25
earliest 18/25 changes 21/25 (tests/sample_scorecard.md); total 104/150.
```

## Token Usage

```text
evaluation/usage_report.md: 302 model calls, all local (RapidOCR +
deterministic heuristics), 0 tokens, $0.00. No API keys required or used.
```

## Submission Status

```text
code.zip: DONE (code/ dataset/ tests/ evaluation/ README.md AGENTS.md
          problem_statement.md HANDOFF.md; secret-grep clean;
          dataset/ included so the zip runs standalone - verified by
          extracting into a clean folder and running code/main.py +
          tests/run_tests.py there)
output.csv: DONE (repo root + dataset/output.csv copy, same run)
chat_transcript: log.txt (in progress, gitignored; upload at submission)
evaluation/usage_report.md: reflects the final full-dataset run
```

---

# 15. HANDOFF SUMMARY

At the end of every agent session, add a short summary here.

Use this exact format:

```text
DATE:
AGENT:
PHASE:

COMPLETED:
-

FILES CHANGED:
-

TESTS:
-

KNOWN ISSUES:
-

NEXT STEP:
-

BLOCKERS:
-
```

The newest summary must always appear at the top of this section.

---

```text
DATE: 2026-09-13
AGENT: Buffy #2 (Freebuff, z-ai/glm-5.3-flash)
PHASE: 10 (accuracy hardening; scorecard unchanged at 104/150)

COMPLETED:
- Built per-sample diagnostic (tests/amount_diagnostic.py -> .txt):
  all 4 matching amount samples are exactly the capped-at-requested
  cases; expected values in non-capped cases are ALWAYS below naive
  headroom; GT earliest dates cluster on salary days.
- Exhaustive general-model search, all negative (do not re-run):
  * tests/model_fitter.py: 147 models (7 estimators x 6 timings x 3
    scopes) -> 0/21 exact trough fits
  * tests/outflow_probe.py: month-total / trailing-window / salary-
    offset whole-outflow formulas -> 0/21 exact fits
  * tests/deduction_solver.py: bitset subset-sum (~200 blocks/sample)
    -> every D reachable, hence non-identifying
  * Fractional-cents analysis -> GT uses a continuous (likely daily-
    rate) spend model; exact form not identifiable from 25 samples.
- FIXED (general): spending-change candidates now accumulate in
  EVENT-ID order with reduce-to-floor preference (was largest-saving
  first). Evidence: request_21/06/11. First change now matches GT on
  request_21; change COUNT stays coupled to the projection gap.
- Added tests/test_spending_changes.py (3 regression tests; 29 total).
- Full run re-executed: 250/250, 0 errors, ZERO violations;
  dataset/output.csv refreshed; code.zip rebuilt (79 files, secret-
  scan clean); HANDOFF/README updated.

FILES CHANGED:
- code/finance/payment_plans.py (event-id ordering)
- tests/{amount_diagnostic,model_fitter,outflow_probe,deduction_solver,
  event_dump,test_spending_changes}.py (new harnesses/tests)
- tests/run_tests.py (+1 module), tests/model_fitter_out.txt
- output.csv, dataset/output.csv, evaluation/usage_report.md, code.zip
- HANDOFF.md, README.md, log.txt

TESTS:
- python tests/run_tests.py -> passed=29 failed=0 errors=0
- python tests/sample_scorecard.py -> status 20 method 21 amount 4
  plan 20 earliest 18 changes 21 (104/150, unchanged)
- python code/main.py -> 250/250 rows, 0 errors, zero violations

KNOWN ISSUES:
- amount_safe_to_pay 4/25: GT projection model not identifiable
  (see section 8's exhaustive negative results). All structural
  evidence says semantics are right; the model is the gap.
- request_21 change-count coupled to the projection gap (see section 8).

NEXT STEP:
- If the hidden set mirrors the sample generator, the daily-rate spend
  model hypothesis (per-event amounts, elapsed-day proration) is the
  only untested direction left; anything beyond that requires labels.

BLOCKERS:
- None
```

```text
DATE: 2026-09-13
AGENT: Buffy (Freebuff, z-ai/glm-5.3-flash)
PHASE: 10 polish complete (all 10 phases done; submission packaged)

COMPLETED:
- Amount/outflow-model hunt executed via three new measurement harnesses
  (tests/recurrence_probe.py, tests/guard_probe.py, tests/matrix_probe.py)
- Three calibrated levers applied to production code:
  * salary cadence projects from >= 1 month of history (+5 fields)
  * double-count guard removed in forecast.build_movements (+2 fields)
  * per-event median = upper-middle element (part of winning config)
- Scorecard: (18,20,3,19,16,21) -> (20,21,4,20,18,21), total 97 -> 104/150
- Full run re-executed: 250/250 rows, 0 errors, ZERO violations;
  dataset/output.csv refreshed manually (main.py does not write it)
- code.zip assembled and secret-scan clean

FILES CHANGED:
- code/finance/normalizer.py (salary 1-month gate + upper-middle nPm)
- code/finance/forecast.py (double-count guard removed)
- tests/{recurrence_probe,guard_probe,matrix_probe}.py (new harnesses)
- output.csv, dataset/output.csv, evaluation/usage_report.md (fresh run)
- code.zip (new), HANDOFF.md, log.txt

TESTS:
- python tests/run_tests.py -> passed=26 failed=0 errors=0
- python tests/sample_scorecard.py -> (20,21,4,20,18,21) of 25
- python code/main.py -> 250 rows, 0 errors, VALIDATION: zero violations

KNOWN ISSUES:
- amount_safe_to_pay 4/25 (HIGH->REDUCED; all measured evidence in
  section 8; remaining ideas expect diminishing returns)
- dataset/output.csv needs manual refresh after full runs (MEDIUM)
- pytest unusable (code/ shadows stdlib); use tests/run_tests.py

NEXT STEP:
- Submit (code.zip + output.csv + log.txt + usage_report.md), or continue
  amount-formula polish per section 8 if accuracy matters more than time

BLOCKERS:
- None
```

```text
DATE: 2026-09-12
AGENT: Buffy (Freebuff, z-ai/glm-5.3-flash)
PHASE: 8 complete; 9 complete; 10 run+validation complete

COMPLETED:
- Phase 8: code/orchestrator.py (per-request flow + grounded explanation);
  main.py run_full() -> output.csv with per-request error isolation
- Phase 9: method-independent amount semantics (sample-evidenced);
  spending-change rewrite (flexibility action types + minimum_allowed
  floors + greedy combos); nPm estimator adopted via calibration sweep
  (total 97/150 vs 93); trough analysis harnesses; scorecard up to
  status 18 method 20 plan 19 earliest 16
- Phase 10: output_validator.py (full hard-check suite); full 250-row run
  with ZERO violations; usage report regenerated; README solution section

FILES CHANGED:
- code/orchestrator.py, code/validate/output_validator.py (new)
- code/main.py, plan_ranker.py, payment_plans.py, normalizer.py,
  forecast.py, README.md
- tests/{trough_solver,trough_probe,calibration_sweep}.py (new harnesses)
- output.csv + dataset/output.csv + evaluation/usage_report.md (final run)
- HANDOFF.md, log.txt

TESTS:
- python code/main.py -> 250 rows, 0 errors, VALIDATION: zero violations
- python tests/run_tests.py -> passed=26 failed=0 errors=0
- python tests/sample_scorecard.py -> (18,20,3,19,16,21) of 25

KNOWN ISSUES:
- amount_safe_to_pay 3/25 (HIGH; all measured evidence in section 8)
- code.zip not yet assembled (LOW; file list in section 14)
- pytest unusable (code/ shadows stdlib); use tests/run_tests.py

NEXT STEP:
- Amount-formula hunt: hybrid estimators / conservative non-recurring
  reserve, fit directly on the 21 exact-trough samples
- Assemble code.zip; final secret grep; submit

BLOCKERS:
- None
```

---

# 16. RULE FOR ALL FUTURE AGENTS

Before making changes:

```text
READ HANDOFF.md
```

Before implementing:

```text
READ THE CURRENT PHASE IN IMPLEMENTATION_PLAN_V2.md
```

Before finishing:

```text
UPDATE HANDOFF.md
```

Never leave the project without documenting the current state.

The goal is that a completely new agent can continue the project by reading:

```text
HANDOFF.md
        ↓
IMPLEMENTATION_PLAN_V2.md
        ↓
CURRENT PHASE FILES
```

without having to understand the entire repository first.
