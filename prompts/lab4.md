# Lab 4 (optional) — Prompt for Codex: decision support with the Decisions API

Paste everything below the line into Codex, from the repository root.

---

Read `AGENTS.md` and follow it. Then build Lab 4: decision support on the
forensic report, with the OpenAI Decisions API. It is one new module,
`fraud_detective/decisions.py`, with its command line. Do not change any provided
file, and do not change the modules of Labs 1–3.

## Context

- The CLI of Lab 3 saves the report as JSON, for example
  `out/halden-ap-q3-2026-report.json`: the report's fields (`summary`,
  `overall_risk`, `total_exposure_eur`, `findings`, `cleared_items`,
  `timeline`, `next_steps`) plus `bundle_sha256` and `review_note`. Each
  finding has `title`, `scheme`, `severity`, `amount_at_risk_eur`,
  `confidence`, `description` and `evidence`. Lab 4 reads this file only: it
  does not import the modules of Labs 1–3 and creates no sandbox.
- `fraud_detective/config.py` (provided): `Settings.load()`. The Decisions API has
  its own settings, `[decisions]` in `config/settings.toml`:
  `decisions_provider` (`ModelProvider.OPENAI` by default) and
  `decisions_model_id` (`"gpt-6-luna"` by default).
  `settings.validate_decisions() -> list[str]` lists what is missing, for
  example `"OPENAI_API_KEY (.env) is not set"`.
- `fraud_detective/llm.py` (provided): `DecisionsClientFactory(settings).create()`
  returns an `openai.OpenAI` client for the Decisions API. Use it: on OCI the
  Decisions API refuses the project header, which the client of the other
  labs sends.

## How the Decisions API works (verified on OCI and OpenAI)

The Decisions API answers **bounded questions** with typed values and
probabilities, in about a second, and gives no explanation. The agent of
Labs 1–3 investigates and writes; the Decisions API only decides.

```python
decision = client.decisions.create(
    model="gpt-6-luna",
    input=[{"role": "user", "content": [{"type": "input_json", "data": {...}}]}],
    questions=[
        {"type": "predicate", "name": "F1_deliberate", "instructions": "..."},
        {"type": "choice", "name": "case_action", "instructions": "...",
         "choices": [{"value": "...", "description": "..."}, ...]},
    ],
)
```

- `decision.answers`: one answer per question, each with `type` and `name`.
  Match answers to questions **by `name`**, never by position.
  - `type == "predicate"`: `probability` (0 to 1) that the statement is true.
  - `type == "choice"`: `choice` (the chosen value), `confidence`, and
    `probabilities`, a list of items with `value` and `probability`.
  - `type == "refusal"`: the model refused this question; the others still
    have answers.
- `decision.model`, and `decision.usage.input_tokens`.

## What to build: `fraud_detective/decisions.py`

Module docstring with the usage line
`python -m fraud_detective.decisions out/halden-ap-q3-2026-report.json`.

Constants:

- `REPORT_FIELDS = ("summary", "overall_risk", "total_exposure_eur",
  "findings", "cleared_items")`: the only fields of the report sent to the
  API. The hash, the note, the timeline and the next steps are not needed.
- `LIKELY = 0.7` and `UNLIKELY = 0.3`: thresholds set by people, not by the
  model.
- `ACTIONS`: a tuple of `(value, description)` pairs, in this order:
  - `stop_payments_and_escalate`: hold the payments that can still be
    stopped, and escalate to legal and HR now;
  - `investigate_further`: gather more evidence before any action;
  - `correct_and_recover`: treat it as a processing error, correct it and
    recover the money, without escalation;
  - `no_action`: nothing in the report requires action.
- `DECISION_NOTE`: a fixed sentence: the indicators come from the OpenAI
  Decisions API and from the report only; the thresholds are set by people,
  and the decision stays with the investigators.

`DecisionError(Exception)`: the report cannot be used, or an answer is
missing.

`build_questions(report: dict) -> list[dict]`: for each finding, numbered
from 1, two `predicate` questions, then one `choice` question for the case.
Write questions about **observable criteria**: each one says "Based only on
the report", and names the finding by number and title, for example
`finding F1 ("<title>")`.

1. `F<n>_deliberate`: does the evidence of the finding indicate a deliberate
   act rather than a processing error?
2. `F<n>_stoppable`: is part of the amount at risk of the finding not yet
   paid, so that it can still be stopped before it leaves the company?
3. `case_action` (last): which next action should the investigators take on
   the case as a whole? Its `choices` are `ACTIONS`, each as
   `{"value": ..., "description": ...}`.

Why these questions: "stopped *or recovered*" was tested and rejected. It
mixes two situations (a payment not yet made, a refund from a supplier), so
the answer changed from one report to another. "Not yet paid" is observable
in the report, and it is what the investigators can act on today.

Results, frozen dataclasses:

- `FindingAdvice(number, title, deliberate, stoppable)`: `deliberate` and
  `stoppable` are probabilities, or `None` when the model refused.
- `CaseAdvice(findings, action, action_confidence, action_probabilities={},
  model="", elapsed_seconds=0.0, input_tokens=0)`: `findings` is a tuple of
  `FindingAdvice` in report order; `action` and `action_confidence` are
  `None` when the model refused; `action_probabilities` maps each value to
  its probability. `to_dict()` returns the fields (`dataclasses.asdict`)
  plus `"thresholds": {"likely": LIKELY, "unlikely": UNLIKELY}` and
  `"note": DECISION_NOTE`.

`likelihood(probability: float | None) -> str`: `"likely"` at or above
`LIKELY`, `"unlikely"` at or below `UNLIKELY`, `"uncertain"` in between,
`"refused"` for `None`.

`DecisionAdvisor(client, model_id, clock=time.monotonic)`:

- `from_settings(settings)`: if `settings.validate_decisions()` lists
  problems, raise `ValueError` with them joined by `"; "`; otherwise build
  the client with `DecisionsClientFactory(settings).create()` and use
  `settings.decisions_model_id`.
- `advise(report: dict) -> CaseAdvice`: **one** request with all the
  questions: `model`, `input` as one `user` message with one `input_json`
  part whose `data` holds only `REPORT_FIELDS`, and
  `questions=build_questions(report)`. Time it with `clock` (round to 2
  decimals). Match the answers by name; a refused predicate gives `None`; a
  refused `case_action` gives `action=None`, `action_confidence=None` and no
  probabilities. A question without an answer raises `DecisionError` naming
  the question.

`load_report(path: Path) -> dict`: read the JSON file. Raise
`DecisionError` if it is not valid JSON, is not an object with a list of
`findings`, or has no findings.

`output_paths(report_path, output_dir) -> (markdown_path, json_path)`:
`x-report.json` gives `x-decisions.md` and `x-decisions.json` (strip a
final `-report` from the stem); in the report's folder, or in `output_dir`
when given.

`render_markdown(advice, report_name) -> str`:

- `# Decision Support`, then `DECISION_NOTE` as a quote.
- A metadata table (`| Metadata | Value |`): report, model, duration in
  seconds, input tokens, and `Thresholds` as
  `likely >= 0.7, unlikely <= 0.3`.
- `## Findings`: a table `| Finding | Deliberate act | Can still be stopped |`
  with one row per finding, for example
  `| F1. <title> | 0.86 likely | 1.00 likely |`: probabilities with 2
  decimals and their `likelihood`, or `refused`. Escape `|` in titles as `\|`.
- `## Next action`: `**<action>** (confidence 0.97)` and a table
  `| Action | Probability |` with every action; or a sentence saying that
  the model refused to suggest an action.

`main(argv=None, stream=sys.stdout, advisor_factory=DecisionAdvisor.from_settings) -> int`:
the command line, `python -m fraud_detective.decisions REPORT [--output-dir DIR]`.

- Print `AI FRAUD DETECTIVE · Decision support` and `Report  <path>`.
- Load the report, build the advisor with
  `advisor_factory(Settings.load())`, call `advise`, write both files.
- Then print the model, the duration and the input tokens; one block per
  finding: `F<n> <title>`, then
  `deliberate act 0.86 likely · can still be stopped 1.00 likely`;
  `Next action: <action> (confidence 0.97)`; `DECISION_NOTE`; and the two
  paths (`Markdown  ...`, `JSON      ...`).
- `DecisionError`, `openai.APIError`, `OSError` and `ValueError` print one
  line `ERROR: <message>`, write no file and return 1. Success returns 0.

End the module with `if __name__ == "__main__": sys.exit(main())`.

## Tests: `tests/lab4/test_decisions.py` (already written: read them first)

They use a fake client that returns a real `openai.types.Decision`, and a
fake clock. They check:

- the questions: names and order, two predicates per finding, the finding
  number and title in the instructions, the actions in order;
- the request: one call, the model, one `user` message with one
  `input_json` part holding only `REPORT_FIELDS`;
- the answers matched by name (the fake returns them in another order),
  refusals as `None`, a missing answer as `DecisionError`;
- `likelihood` at the thresholds, `load_report`, `output_paths`,
  `render_markdown`;
- `main`: the printed lines and both files; one `ERROR:` line for a missing
  file or for missing settings; `from_settings` with
  `DecisionsClientFactory`.

## Done

Run `python -m pytest tests/unit tests/lab4 -q`,
`python -m black --check fraud_detective tests` and `python -m pylint fraud_detective`, fix
any problem, and report what you built, the commands you ran and their
results. Do not call the real Decisions API: the user will run it.
