# README outline — for YOU to write

You said the README is what you'd actually show in interviews, and that you want
to write it yourself. Good instinct: you can't defend prose you didn't write, and
an interviewer's follow-up question ("why FIFO for the journal but average cost
for the holdings?") goes badly if the answer isn't already in your head.

So this file is a **scaffold, not a draft**. Each section below has:
  - what the section is for,
  - a prompt to answer in your own words,
  - the raw facts/decisions from the build, so you're not digging through code.

Write your answers into a real `README.md` and delete this file when done.
If a decision below doesn't make sense to you yet, that's the signal to go read
that file before writing about it — the docstrings explain the reasoning.

---

## 1. What it is (3–4 sentences)

**Prompt:** What does this do, who's it for, and what makes it different from
every other paper-trading toy?

Facts to draw on:
- Paper trading simulator for NSE/BSE with virtual cash (default ₹10,00,000).
- Multiple named "strategy" portfolios, each tracked separately.
- The differentiator: **the trade journal**. Every buy records a thesis and a
  1–5 confidence rating; every sell records why you exited. The analytics layer
  then tells you whether your reasoning actually holds up.
- Explicitly a *learning* tool — the goal is understanding your own trading
  behaviour, not simulating a broker.

**Interview angle:** lead with the journal. "I built a trading simulator" is
forgettable; "I built a tool that measures whether my own conviction predicts my
returns" is not.

---

## 2. Screenshots

Take 3: the strategy detail page, the journal, and the analytics page. The
analytics page is the money shot — it's the one that shows judgment rather than
CRUD.

---

## 3. Architecture

**Prompt:** Explain the layering and why the engine has no idea the web exists.

Facts:
```
engine/   pure Python domain logic — no Flask, no HTTP, no disk except its stores
api/      Flask REST layer — translates HTTP <-> engine calls
frontend/ React (Vite) — plain useState/useEffect/fetch, no state library
data/     JSON files (per-user directories)
```
- The engine is a standalone module with a working CLI (`python main.py`) that
  predates the web layer entirely. Flask became a *second caller* of the same
  methods; the CLI still works.
- **Why that matters:** every trading rule is unit-testable with no server, no
  network, no mocking. 87 tests run in ~6 seconds.

**Draw the dependency direction:** `frontend → api → engine`. The engine never
imports from api. Say why that's deliberate.

---

## 4. Design decisions (the section interviewers actually read)

Write each as: *decision → why → what you gave up*. That last part is what
separates "I read a tutorial" from "I made a call".

### 4a. Average-cost holdings + FIFO lot-linking for the journal
- Holdings track one blended `avg_price` per symbol (simple, standard retail).
- But confidence/tags live on *individual buys*, so each sell also FIFO-links
  back to the buys it closed, storing a `ClosedLot` snapshot.
- **This is the cleverest thing in the codebase.** It means a sell carries two
  P&L numbers: the headline one (vs average cost — the money that hit your cash)
  and per-lot ones (vs each original buy price — what the analytics use).
- **Tradeoff given up:** two numbers that can disagree, which needs explaining.
  Read `Portfolio.sell`'s docstring before writing this section.

### 4b. Storage: JSON files, atomic writes
- Temp file + `os.replace()` (atomic on Windows and POSIX) so a crash mid-write
  can't corrupt data.
- Corrupt files are quarantined to `.corrupt-<timestamp>` rather than silently
  overwritten.
- **Tradeoff:** no concurrent writes, no queries, whole-file rewrites. Fine for
  one user; SQLite is the migration path. Say when you'd migrate and why you
  hadn't yet.

### 4c. Price source behind an interface
- `engine/prices.py` defines a `PriceSource` protocol with one method.
- The engine only ever receives a `{symbol: price}` dict — it never fetches.
- **Payoff:** swapping the manual stub for `nsepython` (Phase 4) touches one
  construction site, not the trading logic. Alerts poll through the same seam.

### 4d. Two-layer request validation
- Syntactic at the API boundary (`api/validation.py`): is it JSON, right types
  → 400 before the engine is touched.
- Semantic in the engine: enough cash, confidence in range → typed errors mapped
  to 409/400.
- **Why:** the engine stays the single source of truth for trading rules; the
  API just guards the door. Good example: `confidence: "high"` fails at layer 1,
  `confidence: 9` passes layer 1 and fails at layer 2.

### 4e. HTTP status codes and one error envelope
- Every error returns `{"error": {"type", "message"}}`.
- 400 malformed · 404 unknown resource · 409 conflicts with state (duplicate
  name, insufficient funds) · 500 our fault, generic message.
- **Why the `type` field:** so React can branch on `InsufficientFunds` without
  string-matching an English message.

### 4f. Auth structured for multi-user from day one
- Single user in practice, but **nothing hardcodes "the one user"**.
- `api/paths.py` resolves every file location from a `user_id`; routes get
  `g.paths` from the auth decorator.
- Prices are deliberately global (market data), everything else per-user.
- There's a test (`test_two_users_have_isolated_data`) proving user B can't see
  user A's strategies.
- Passwords: salted hashes via werkzeug. Tokens: signed with itsdangerous, so no
  server-side session store.
- **Tradeoff to own:** token in `localStorage` is XSS-readable; httpOnly cookie
  is safer but needs CSRF handling. You chose deliberately — say so.

### 4g. Background jobs as a plain daemon thread
- No Celery/APScheduler: a thread with a sleep loop, zero extra dependencies.
- Two gotchas handled, both worth mentioning:
  1. Flask's auto-reloader runs your code twice — guarded via `WERKZEUG_RUN_MAIN`.
  2. **A bug I hit and fixed:** the first version snapshotted once at boot, so a
     user who registered later had an empty chart for 24h. Fixed by sweeping
     every 5 min and relying on upsert-by-(date, strategy) to keep data daily.
     There's a regression test for it.
- **Mention that bug.** "Here's a bug I found in my own design and how I fixed
  it" is one of the strongest things you can say in an interview.

### 4h. Frontend state: why no Redux
- Server state lives in the page that displays it (`useApi` hook).
- Form state lives in the form. View state (journal filters) lives in the view.
- Auth is the *only* global state, because it gates the whole route table.
- After a mutation: **refetch, don't hand-patch**. Patching would mean
  duplicating the engine's P&L math in JavaScript.
- **Say what would change your mind:** the moment two distant components need
  the same live data, reach for Context or React Query.

---

## 5. Setup

```bash
# backend
pip install -r requirements.txt
python run_api.py              # http://127.0.0.1:5000

# frontend
cd frontend && npm install && npm run dev   # http://localhost:5173

# tests
python -m pytest -q            # 87 tests
python main.py                 # the standalone CLI still works
```
First run shows a "create your account" screen. Prices are manual until Phase 4
(use the price control / `PUT /prices/<symbol>`), which is what drives
unrealized P&L and fires alerts.

---

## 6. Project status / roadmap

Be honest — half-finished is fine if labelled:
- Done: core engine (CLI), REST API, React UI, alerts, snapshots + comparison,
  journal analytics, auth.
- **Not done: Phase 4, live NSE prices via `nsepython`.** Prices are entered
  manually. The `PriceSource` seam exists specifically for this.
- Known limitations worth listing yourself: no transaction costs/brokerage, no
  slippage, no market-hours check, no corporate actions (splits/dividends),
  JSON storage won't survive concurrent users.

**Listing your own limitations is a strength.** It shows you know the difference
between what you built and a real system.

---

## 7. What I learned (optional, but this is the interview hook)

**Prompt:** What did the journal analytics actually tell you about your own
trading? Even with fake money — did high confidence correlate with returns? Did
you hold losers longer than winners?

This is the section only you can write, and it's the one that makes the project
memorable. A candidate who says "my confidence-5 trades underperformed my
confidence-3 trades and I have the data" is instantly more interesting than one
who lists frameworks.

---

## Writing tips

- **Cut every sentence that could appear in any other project's README.**
  "Built with React and Flask" tells nobody anything.
- Prefer concrete numbers: "87 tests", "engine has zero runtime dependencies".
- If you can't explain a decision in one sentence, you don't understand it yet —
  go read that file, then write it.
- Keep it under ~150 lines. Interviewers skim.
