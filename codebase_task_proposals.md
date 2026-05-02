# Codebase task proposals

## 1) Typo fix task
**Issue found:** In `watcher_entsoe.py`, the inline comment says `# Normaliseer naar NL-tijd en sorteert`.
This is a wording typo in Dutch (`sorteert` should be imperative form `sorteer` to match the style of the comment).

**Task:** Update the comment to `# Normaliseer naar NL-tijd en sorteer` for linguistic consistency and readability.

## 2) Bug fix task
**Issue found:** `ensure_96_quarters` in `run_daily.py` performs interpolation with:
`np.interp(np.linspace(0, length, 96), np.arange(length), data)`.
Because `np.linspace` includes the endpoint by default, the last query point can be exactly `length`, which is outside the valid source x-range `[0, length-1]`. That can lead to subtle edge distortion (flat extrapolation of the final sample).

**Task:** Change interpolation to stay in-range, e.g. use `np.linspace(0, length - 1, 96)` (or `endpoint=False` with a matching grid), and add an assertion/test for boundary behavior.

## 3) Code comment / documentation discrepancy task
**Issue found:** The docstring for `expected_hours_for_delivery_date` in `run_daily.py` says:
`target_date is een tz-aware Timestamp in Europe/Amsterdam`.
But the implementation only uses `target_date.date()` and does not validate or enforce timezone awareness. Naive timestamps are silently accepted, which does not match the documented contract.

**Task:** Either (a) enforce the contract by validating timezone-awareness and timezone, or (b) relax/update the docstring to reflect actual accepted inputs.

## 4) Test improvement task
**Issue found:** There are currently no automated tests in the repository for critical date/time and shaping utilities.

**Task:** Add a `tests/` suite (pytest) covering:
- `_expected_hours` and `expected_hours_for_delivery_date` for normal day + DST spring/fall transition days in `Europe/Amsterdam`.
- `ensure_96_quarters` for input lengths 24/48/96 and a nonstandard length (e.g., 23 or 25) to verify output length and edge-value behavior.
- A small unit test around `wait_for_day_ahead` timeout behavior by mocking `_fetch` / client responses.
