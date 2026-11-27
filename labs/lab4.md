# Lab 4 (optional) — Decision support with the Decisions API

**Time:** normally 5–7 minutes of hands-on work, plus reading and review.
**You build:** `fraud_detective/decisions.py`, with Codex.
**Runs on:** the OpenAI Decisions API (model `gpt-6-luna`); no sandbox.

> **Working directory:** Run all terminal commands in this guide from the
> project root (`ai-fraud-detective/`), the directory containing `README.md`,
> `config/`, and `fraud_detective/`. Do not change into `labs/`.

## Goal

The agent of Labs 1–3 *investigates*: it explores the bundle step by step,
writes code and produces a report in prose. In this lab you add a different
use of AI: a model that *decides*. The OpenAI Decisions API reads the saved
report and answers three bounded questions, with probabilities, in about a
second:

| Question | Type | Asked |
|----------|------|-------|
| Does the evidence indicate a deliberate act rather than a processing error? | `predicate`: a probability | for each finding |
| Is part of the amount at risk not yet paid, so that it can still be stopped? | `predicate`: a probability | for each finding |
| Which next action should the investigators take? | `choice`: one of four actions, with probabilities | once, for the case |

```
python -m fraud_detective.decisions out/halden-ap-q3-2026-report.json
```

## Why it matters

- **Two kinds of AI work.** The Responses API runs an open-ended
  investigation: many steps, tools, text. The Decisions API answers closed
  questions with typed values: a probability, a choice. Use each one where
  it fits.
- **Fast and repeatable.** All the questions go in one request, and the
  answers come back in about a second. With the same report, the answers are
  the same every time.
- **No explanation.** The Decisions API returns numbers, not reasons. That is
  why it works *on the report*: the report gives the evidence, and the
  decision support only summarizes it for whoever has to act.
- **Questions about observable criteria.** A good question can be checked in
  the report. "Is part of the amount not yet paid?" can; "Can the money be
  stopped *or recovered*?" mixes two situations, and in our tests its answer
  changed from one report to another.
- **People set the thresholds.** A probability becomes "likely" or
  "unlikely" only through thresholds that people choose (0.7 and 0.3 here),
  weighing a false alarm against a missed fraud. The decision stays with the
  investigators.

## Before you start

You need:

- a report from Lab 3: `out/halden-ap-q3-2026-report.json`. If you skipped
  the labs, follow [the easy path](../docs/easy-path.md) to produce one;
- an **OpenAI API key** in `.env`, `OPENAI_API_KEY=...`, even if you ran
  Labs 1–3 on OCI;
- the `[decisions]` section of `config/settings.toml`, which works as it
  is:

```toml
[decisions]
provider = "openai"
model_id = "gpt-6-luna"
```

## Steps

### 1. Ask Codex to build the decision support

Open Codex in the repository root and enter:

```
Read prompts/lab4.md and do what it says (everything below the first line).
```

The tests use a fake Decisions API client: Codex makes no real call.

### 2. Review what Codex wrote

- One request with all the questions; the report goes as `input_json`, and
  only the fields listed in `REPORT_FIELDS`.
- Answers matched to questions by `name`; a refused question gives `None`,
  not an error.
- The thresholds `LIKELY` and `UNLIKELY` are constants in the code, and the
  output always carries the fixed note.

### 3. Run the checks

```bash
python -m pytest tests/unit tests/lab4 -q
python -m black --check fraud_detective tests
python -m pylint fraud_detective
```

### 4. Run it on your report

```bash
python -m fraud_detective.decisions out/halden-ap-q3-2026-report.json
```

It prints one block per finding and the suggested next action, and writes
`out/halden-ap-q3-2026-decisions.md` and `.json`.

Check it:

- Does it separate the fraud from the honest error? The deliberate-act
  probability should be high for one finding and low for the other.
- Where can money still be stopped? Compare with the scheduled payment in
  the report.
- Is the next action consistent with the two answers above?
- How long did the request take, compared with the investigation?

### 5. Change a question (optional)

In `build_questions`, replace the stoppable question with "can part of the
amount at risk still be stopped or recovered?" and run step 4 again. Look at
the answer for the duplicate payment: it is less clear, because the question
mixes two situations. Put the original question back.

## Done when

- `python -m pytest tests/unit tests/lab4 -q` passes.
- `out/halden-ap-q3-2026-decisions.md` has a row per finding and a next
  action.
- You can explain when to use the Decisions API instead of the Responses
  API, why a question must be about observable criteria, and who sets the
  thresholds.

## Stuck?

Copy the reference solution and run step 4:

```bash
cp solutions/lab4/decisions.py fraud_detective/
```
