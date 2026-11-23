# Lab 3 — Prompt for Codex: forensic report and CLI

Paste everything below the line into Codex, from the repository root.

---

Read `AGENTS.md` and follow it. Then build Lab 3: the structured forensic
report and the command line that verifies a case bundle and runs a whole
investigation on a real OCI Sandbox. Do not change any provided file, and do not change
`fraud_detective/tools.py` or `fraud_detective/agent.py`.

## Context

- `fraud_detective/agent.py` (Lab 2): `InvestigationAgent.from_settings(settings, tools,
  max_steps=..., on_event=...)`, `run(task) -> AgentResult` with `answer`,
  `response_id`, `stopped_reason`, `steps`, `tool_calls`, `input_tokens`,
  `output_tokens`. The conversation is stored on the server (`store=True`).
- `fraud_detective/tools.py` (Lab 1): `ToolRegistry(session)`, `call(name,
  arguments) -> str`; `read_file` returns lines as `path:line: text`.
- `fraud_detective/ingest.py` (provided): integrity and upload of a bundle.
  - `reference_hash(bundle) -> str` reads the reference SHA-256 from the
    `.sha256` file next to the zip (it stands for the value recorded in the
    case file); `verify_hash(path, expected) -> str` checks a local zip
    against it and returns the hash. Both raise `BundleError`.
  - `BundleUploader(session).upload(path, expected_sha256=...) ->
    BundleSummary` checks the zip locally (without extracting it), checks
    the hash, uploads it, checks the hash of the uploaded copy **in the
    sandbox**, and extracts it under `/workspace/bundle`; raises
    `BundleError`. `BundleSummary.describe()` gives one line for the console;
    `sha256` and `verified_in_sandbox` report the checks.
- `fraud_detective/sandbox.py` (provided): `SandboxManager.from_settings(settings,
  OciClients(settings))`, `create(display_name=..., on_progress=...)`,
  `attach(sandbox_id)`; `SandboxSession.snapshot() -> str`,
  `close(on_progress=...)` (stops and deletes only a sandbox the session
  created), `sandbox_id`. Creating a sandbox can take minutes: always pass
  `on_progress`.
- `fraud_detective/make_bundle.py` (provided): `python -m fraud_detective.make_bundle` writes
  the sample case, `bundles/halden-ap-q3-2026.zip`, and its reference hash,
  `bundles/halden-ap-q3-2026.sha256`.

## How the report is produced (verified on OCI)

The report is one more turn of the **same server-side conversation**: the
model already has every tool result, so the client sends nothing but a
request and the id of the last response:

```python
client.responses.create(
    model=model_id,
    previous_response_id=agent_result.response_id,
    input=REPORT_REQUEST,
    text={"format": {"type": "json_schema", "name": "fraud_report",
                     "schema": REPORT_SCHEMA, "strict": True}},
    store=True,
)
```

The answer is a JSON document that follows `REPORT_SCHEMA` (the `text` of the
`output_text` parts of the `message` items).

## What to build (1): `fraud_detective/report.py`

A fraud review finds several problems, each with its own evidence and amount,
so the report is a list of findings, not one root cause.

- `REPORT_SCHEMA`: strict JSON schema (every property in `required`,
  `additionalProperties: false` at every level) with:
  - `summary` (string), `overall_risk` (`"high"`, `"medium"` or `"low"`),
    `total_exposure_eur` (number);
  - `findings`: array of `{title, scheme, severity, amount_at_risk_eur,
    confidence, description, evidence}`; `scheme` is one of
    `supplier_bank_change`, `split_invoices`, `duplicate_payment`,
    `segregation_of_duties`, `self_approval`, `fictitious_supplier`,
    `other`; `severity` and `confidence` are `high`, `medium` or `low`;
    `amount_at_risk_eur` is a number; `evidence` is an array of
    `{location, observation}`, where `location` is `path:line`,
    `path:line-line` or `path:line,line`;
  - `cleared_items`: array of `{item, reason}`: anomalies checked and found
    legitimate;
  - `timeline` (array of `{time, event, evidence}`), `next_steps` (array of
    strings).
- `REPORT_REQUEST`: the request to the model: write the forensic report from
  the investigation, one finding per distinct loss or exposure. The control
  failures that made a loss possible (self-approval, split invoices,
  conflicting roles...) go inside that finding, with their evidence, not in
  separate findings; a control failure is a finding of its own only when it
  caused no loss, with an amount of 0. Cite only evidence found with the
  tools (line 1 of a CSV file is the header), list cleared anomalies, and
  give a total exposure that does not count the same money twice.
- `REVIEW_NOTE`: a fixed sentence that says the findings come from an AI agent
  and must be verified by the investigators before drawing conclusions. The
  code adds it to every report: it is not asked to the model.
- Frozen dataclasses `Evidence` (`location`, `observation`,
  `verified: bool | None = None`), `Finding`, `ClearedItem`,
  `TimelineEvent`, `FraudReport`, with `FraudReport.from_dict(data)`,
  `to_dict()` and an `evidence` property with every evidence of every
  finding, in order.
- `ReportError(Exception)`: the answer is not valid JSON or does not match the
  schema (wrong types, unknown enum values, missing or extra fields, amounts
  that are not numbers or are negative; `true` is not a number).
- `ReportWriter(client, model_id)`, `from_settings(settings)`,
  `write(result: AgentResult) -> FraudReport`: the call above.
- `EvidenceChecker(tools: ToolRegistry)`, `check(report) -> FraudReport`:
  for each evidence of each finding, reads the first cited line with the
  `read_file` tool and sets `verified` to `True` when the line exists,
  `False` otherwise (missing file, line past the end, location that cannot be
  parsed). It never raises. This shows which evidence really exists in the
  bundle.
  **Parse locations tolerantly**: the model writes them in many ways, and a
  correct citation must not be marked ✘ because of its format. Strip
  surrounding backticks, quotes and spaces; accept `-`, `–` and `—` for
  ranges; accept spaces after commas; accept lists that mix lines and ranges.
  All of these must be verified when line 2 exists:
  `ap/invoices.csv:2`, `` `ap/invoices.csv:2` ``,
  `ap/invoices.csv:2-4`, `ap/invoices.csv:2–4`,
  `ap/invoices.csv:2, 9`, `ap/invoices.csv:2,29-34`.
  The first number after the last `:` is the line to check.
- `money(amount) -> str`: for example `106,991.00 EUR`.
- `amount_at_risk(amount) -> str`: `money(amount)`, or `no direct loss` when
  the amount is 0: printed as `0.00 EUR`, a control failure without a loss of
  its own would read as "no risk". Use it wherever the amount of a finding is
  shown (Markdown and result panel).
- `render_markdown(report, metadata: dict[str, str]) -> str`: a readable
  report: title `Forensic Review Report`, the review note, a metadata table
  (bundle, bundle SHA-256, date, model, sandbox, steps, tool calls, tokens),
  Summary with overall risk and total exposure, Findings (one section per
  finding, `F1.`, `F2.`, ..., with scheme, severity, confidence, amount and an
  evidence table with verified ✔ / ✘), Cleared items, Timeline, Next steps as
  a numbered list.

## What to build (2): `fraud_detective/cli.py`

```
python -m fraud_detective.cli BUNDLE [--sandbox-id ID] [--keep] [--snapshot]
                            [--max-steps N] [--task TEXT] [--output-dir DIR]
                            [--expected-sha256 HEX]
```

- `InvestigationApp(settings, manager, model_client, output_dir, stream)`, with
  `run(bundle, *, sandbox_id=None, keep=False, snapshot=False, max_steps=...,
  task=..., expected_sha256=None) -> Path` (the Markdown report). `main()` builds the real
  dependencies from `Settings.load()`, parses the arguments, runs the app and
  returns the exit code.
- The run starts with a **banner** (see "Console output" below), then
  numbered steps printed to `stream` so the user always knows what is being
  waited for:
  1. **Integrity**: before any sandbox exists, check the bundle against the
     reference hash: `--expected-sha256`, or else `reference_hash(bundle)`;
     then `verify_hash`. Print the first characters of the hash. A missing
     or different hash stops the run here (`BundleError`): no sandbox is
     created.
  2. **Sandbox**: attach to `--sandbox-id`, or create a new one, printing the
     state while it starts ("a cold start can take minutes").
  3. **Bundle**: upload it with `expected_sha256`, so the copy in the sandbox
     is checked before the extraction; print that the copy matches, and
     `summary.describe()`.
  4. **Investigation**: run the agent; print each `on_event` line. The
     agent cannot check the hash itself (the reference is outside the
     bundle), so tell it the result: its task is `task_with_integrity(task,
     sha256)`, the task followed by a blank line and `INTEGRITY_NOTE`, a
     fixed sentence with the verified hash saying that the bundle matched the
     reference locally and in the sandbox, so the archive hash needs no
     further check. It is a fact established by the code, not bundle
     content.
  5. **Report**: `ReportWriter`, then `EvidenceChecker`; write
     `<output-dir>/<bundle-stem>-report.md` and `-report.json`; print both
     paths and how many evidence lines were verified. The JSON file is the
     report's `to_dict()` plus `bundle_sha256` and `review_note`; the
     Markdown metadata include the bundle SHA-256.
  6. **Cleanup**: with `--snapshot`, take a snapshot and print its id. Then
     close a sandbox created by this run, unless `--keep`: in that case print
     its id and the command to reuse it (`--sandbox-id`). Never close a
     sandbox given with `--sandbox-id`.

  After a successful cleanup, the run ends with the **result panel** (see
  "Console output"): the summary, the overall risk, the total exposure, one
  line per finding, the verified evidence and the bundle hash, as the last
  thing on the screen.
- **Progress while waiting**: a sandbox can take many minutes to start or
  stop, and the state is polled every few seconds. Do not print a new line
  for each state message. When `stream` is a terminal, rewrite the same line
  in place (`\r` and clear to end of line) and end it with a newline when the
  step is over; otherwise print a state line at most every 30 seconds, and
  whenever the state changes.
- **A slow cleanup is a warning, not a failure**: the service can take more
  than five minutes to stop a sandbox, and `close()` then raises
  `SandboxError` ("still STOPPING..."). The report is already written: print
  a warning with the sandbox id and "delete it from the OCI Console once it is
  STOPPED", and exit 0.
- Defaults: `--output-dir out`, `--max-steps` 15, a default `--task` that
  asks to review the accounts payable in the bundle: find payments that may
  be fraudulent or wrong, explain why, quantify the exposure in EUR and cite
  the evidence.
- Validate the settings first (`settings.validate()`): print the problems and
  exit 1.
- The cleanup also runs after an error or Ctrl+C. Expected errors
  (`BundleError`, `SandboxError`, `ReportError`, `openai.APIError`) print one
  clear line and exit 1, without a traceback.

## Console output

The CLI is what participants watch for many minutes: make it pleasant to
read, in the same style as the preflight (`python -m fraud_detective.preflight`).
Use only the standard library (no `rich` or other new dependency), and keep
this code in a small console class of its own in `cli.py` (for example
`ConsoleView`), not scattered `print` calls in `InvestigationApp`.

Target layout (non-terminal stream, so no colors):

```
╭──────────────────────────────────────────────────────────────╮
│  AI FRAUD DETECTIVE                                          │
│  Oracle LiveLabs · Forensic review                           │
│                                                              │
│  Bundle  halden-ap-q3-2026.zip                               │
│  Model   openai.gpt-5.2 · max 15 steps                       │
╰──────────────────────────────────────────────────────────────╯

▸ 1. Integrity
  Checking the bundle against the reference hash of the case file.
  ✔ SHA-256 matches the reference: 9dafa3d717310e2d…
▸ 2. Sandbox
  Creating sandbox: a cold start can take minutes.
  RUNNING, 9 s
  ✔ Sandbox ocid1.sandbox.oc1...
▸ 3. Bundle
  ✔ Copy in the sandbox matches the reference hash
  ✔ halden-ap-q3-2026.zip: 19 files, 0.7 MB extracted
▸ 4. Investigation
  · step 1: list_files {"path": "."}
  · step 2: read_file {"path": "policy/ap_controls.md", ...}
  · step 9: answer
▸ 5. Report
  ✔ Evidence verified: 21/22 (first cited lines)
  Markdown  out/halden-ap-q3-2026-report.md
  JSON      out/halden-ap-q3-2026-report.json
▸ 6. Cleanup
  ✔ Sandbox closed

╭─ Investigation result ───────────────────────────────────────╮
│  Summary:                                                    │
│    An AP clerk redirected a dormant supplier's payments to   │
│    his own account and approved his own invoices.            │
│                                                              │
│  Overall risk: high · Total exposure: 111,803.40 EUR         │
│                                                              │
│  Findings (2):                                               │
│    F1 [high] Supplier payments redirected to an employee ·   │
│       106,991.00 EUR                                         │
│    F2 [medium] Duplicate payment to Kestrel · 4,812.40 EUR   │
│                                                              │
│  Evidence verified: 21/22                                    │
│  Bundle SHA-256: 9dafa3d717310e2d…                           │
╰──────────────────────────────────────────────────────────────╯
```

Rules:

- **Banner**: the first output of `run()`, a rounded box (`╭ ╮ │ ╰ ╯ ─`)
  `BOX_WIDTH = 64` characters wide, like the preflight banner, with the title,
  the subtitle, the bundle file name, the model id and the step budget. Text
  that does not fit is cut with `…`: every box line is exactly `BOX_WIDTH`
  characters, with a margin of two spaces inside each border.
- **Steps**: a header line `▸ N. Title` (the text `N. Title` exactly, for
  example `2. Sandbox`), then the step's lines indented by two spaces. A
  completed action starts with `✔`; agent events start with `·`.
- **Result panel**: a box of the same width titled `Investigation result`,
  with the report's **summary** under `Summary:`, wrapped with `textwrap` to
  fit inside the box (never cut: the whole text is shown); a line
  `Overall risk: <value> · Total exposure: <money>`; `Findings (<n>):` and
  one wrapped line per finding, `F<n> [<severity>] <title> · <amount>`
  (`amount_at_risk`); then
  `Evidence verified: <n>/<total>` and `Bundle SHA-256: <first 16 hex>…`.
  The report paths are printed in step 5, outside the box, so long paths are
  never cut.
- **Warnings and errors**: `⚠ WARNING: ...` and `✘ ERROR: ...`, each on one
  line; an error is printed exactly once.
- **Colors**: only when `stream.isatty()` is true and the `NO_COLOR`
  environment variable is not set. Cyan for the banner, the result panel
  border and the step headers; green for `✔`; yellow for warnings; red for
  errors; the overall risk in red (`high`), yellow (`medium`) or green
  (`low`); dim for agent events. Otherwise (a file, a pipe, the tests) the output has
  no escape codes at all, and box lines stay exactly `BOX_WIDTH` characters
  (compute widths on the text without color codes).
- The progress line keeps the behavior described above (rewritten in place
  on a terminal, throttled otherwise), indented like the other step lines.

## Tests: `tests/lab3/` (already written: read them first)

The acceptance tests of this lab are already in `tests/lab3/`. They are
the exact contract: besides the interface above, they import or patch a
few more names (constants, helper functions, names imported in the
module). Read them **before** writing code, then make them pass **without
changing them**. If you want more tests, add them in a new file,
`tests/lab3/test_extra.py`.

The tests never call OCI or the model:

- Model: a fake client whose `responses.create(**kwargs)` returns scripted
  responses and records its arguments (output items built with the real
  openai types, as in `tests/lab2`).
- Sandbox: a real `SandboxManager` and `SandboxSession` over
  `FakeSandboxClient` (`tests/unit/fakes.py`); bundles built with
  `zipfile` in `tmp_path`, each with its `.sha256` file next to it.

They cover:

- `ReportWriter`: the request has `previous_response_id`, `store=True` and
  the strict `json_schema` format named `fraud_report`; valid JSON becomes a
  `FraudReport`; invalid JSON, wrong types, unknown enum values and bad
  amounts raise `ReportError`.
- `REPORT_SCHEMA` is strict at every level, with the fields above.
- `EvidenceChecker`: every location format listed above is verified when the
  line exists; a missing file, a line past the end and a malformed location
  are not, and nothing raises.
- `render_markdown`: all sections, the review note, the amounts in EUR and
  the ✔ / ✘ marks are present; an amount of 0 reads `no direct loss`.
- Integrity: a missing `.sha256` file or a changed bundle stops the run
  before any sandbox is created, with one error line; `--expected-sha256`
  replaces the file.
- `InvestigationApp.run` end to end with the fakes: the six steps in order; the
  first request carries `task_with_integrity(task, sha256)`; the report
  files are written, with the bundle hash;
  a created sandbox is closed; with `keep=True` it is not, and its id is
  printed; an attached sandbox is never closed; a bad bundle prints one
  error line and still runs the cleanup; a `close()` that raises
  `SandboxError` prints a warning and the run still succeeds.
- Progress: many state messages on a non-terminal stream produce only a few
  lines (use a stream whose `isatty()` returns False, and patch the clock).
- Console output: the banner comes before step 1; the result panel shows
  the summary, the risk, the exposure and the findings; every box line is
  `BOX_WIDTH` characters,
  also with a long summary and a long model id; a non-terminal stream gets no
  escape codes; a terminal stream gets colors unless `NO_COLOR` is set.

## Done

Run `python -m pytest tests/unit tests/lab1 tests/lab2 tests/lab3 -q`,
`python -m black --check fraud_detective tests` and `python -m pylint fraud_detective`, fix
any problem, and report what you built, the commands you ran and their
results. Do not run the CLI against OCI: creating a sandbox takes minutes,
and the user will run it.
