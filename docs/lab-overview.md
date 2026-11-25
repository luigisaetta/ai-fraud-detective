# AI Fraud Detective — Lab Overview

Build an AI agent that reviews accounts payable data for fraud and errors, as
the analyst of an external forensic firm would. The model is reached
through the OpenAI Responses API (on OCI Generative AI or on OpenAI); every
command the agent runs executes inside an isolated OCI Sandbox. You write the
code with Codex, guided by `AGENTS.md`, the lab guides and acceptance tests.

**Total time:** about **40–60 minutes**, including time to read the guides and
review the generated code. Sandbox creation may occasionally take longer.
Each lab normally takes 5–7 minutes of hands-on work; the total estimate allows
additional time for reading and review.

| Lab | Topic | You build | Runs on | Hands-on time |
|-----|-------|-----------|---------|------|
| 0 | Setup and preflight | nothing (provided) | OCI | 5–7 min |
| 1 | Sandbox tools | `fraud_detective/tools.py` | local fake | 5–7 min |
| 2 | Agent loop | `fraud_detective/agent.py` | local fake + model | 5–7 min |
| 3 | Report and end-to-end run | `fraud_detective/report.py`, `fraud_detective/cli.py` | OCI Sandbox + model | 5–7 min |
| 4 (optional) | Decision support | `fraud_detective/decisions.py` | OpenAI Decisions API | 5–7 min |

Each lab has four parts:

| Part | Where |
|------|-------|
| Guide for the participant | `labs/labN.md` |
| Prompt for Codex | `prompts/labN.md` |
| Acceptance tests | `tests/labN/` |
| Reference solution | `solutions/labN/` |

Read the guide, give the prompt to Codex, review what it writes, run the
tests. The code you build stays in `fraud_detective/`, and each lab builds on the
previous ones. If you fall behind, copy `solutions/labN/` into `fraud_detective/` and
move on.

---

## Lab 0 — Setup and preflight

**Goal:** a working environment and an OCI project ready for the agent.

**Steps:**
1. Create the Python environment and install the requirements.
2. Create the Generative AI project: conversations on, short-term memory on
   (compaction model `openai.gpt-oss-120b`), long-term memory off, sandboxes
   on with `MANAGED` network and `DENY_ALL`.
3. Put your API key in `.env` (secrets only); set model, region and project
   OCID in `config/settings.toml`.
4. Run `python -m fraud_detective.preflight --quick`: configuration, OCI credentials,
   project settings, permissions, and a model call that continues on the
   server.
5. Run `python -m fraud_detective.preflight`: a test sandbox starts, runs commands,
   moves a file, cannot reach the internet, and is deleted. Creation and
   deletion together normally take less than 20 seconds. Creation may
   occasionally take several minutes: read Lab 1 meanwhile.
6. Read `AGENTS.md`: the rules Codex follows in this repo.

**You learn:** Generative AI projects (conversations, short-term memory,
sandboxes), managed network policy (`DENY_ALL`), the Responses API on OCI vs
OpenAI, secrets vs configuration.

**Done when:** all preflight checks pass (a slow cleanup warning is fine).

---

## Lab 1 — Sandbox tools

**Goal:** give the model safe, small tools to explore a case bundle.

**Build with Codex:** `fraud_detective/tools.py`, function tools on top of the provided
`SandboxSession`:
- `list_files` — bundle tree with sizes
- `read_file` — a line range of a file
- `grep` — matches with `file:line`
- `run_python` — run a short analysis script in `/workspace`

Each tool has a JSON schema for the model and returns short, bounded output.
Paths outside the bundle and symbolic links that leave it are refused.

**You learn:** function tool design, why the model never runs code locally,
timeouts and output limits in the sandbox, model input as untrusted input.

**Done when:** `pytest tests/unit tests/lab1` passes (against the local fake).

---

## Lab 2 — Agent loop

**Goal:** an agent that investigates the bundle by calling the tools.

**Build with Codex:** `fraud_detective/agent.py`, a loop on the Responses API:
send the task and the tool schemas, execute the requested function calls in the
sandbox, return the results, repeat until the model answers or the step budget
runs out. The conversation is kept on the server: after the first call, only
`previous_response_id` and the new tool outputs are sent. Tool errors are
returned to the model, not raised.

**You learn:** function calling with Responses, server-side conversation
(`store=True`, `previous_response_id`), several tool calls per step, step
budgets, instructions that carry a forensic method, treating bundle content
as untrusted data (prompt injection).

**Done when:** `pytest tests/lab2` passes; optionally, watch the agent
investigate a small bundle with the real model.

---

## Lab 3 — Report and end-to-end run

**Goal:** a forensic report from the sample case, on a real OCI Sandbox.

**Before:** `python -m fraud_detective.make_bundle` writes
`bundles/halden-ap-q3-2026.zip`, the extraction of nine months of accounts
payable of a fictitious company, and `bundles/halden-ap-q3-2026.sha256`, its
reference hash. The data hides a fraud, an honest error, legitimate
anomalies and text that tries to give orders to the AI.

**Build with Codex:**
- `fraud_detective/report.py` — the report is one more turn of the same server-side
  conversation, with structured output (strict JSON schema): findings, each
  with scheme, severity, confidence, amount at risk in EUR and evidence as
  `file:line`; cleared anomalies; timeline; next steps. Each cited line is
  read in the sandbox and marked ✔ or ✘. Rendered as Markdown, with a fixed
  note that investigators verify the findings.
- `fraud_detective/cli.py` — `python -m fraud_detective.cli bundles/<bundle>.zip`: check the
  bundle against its reference hash, create a sandbox, upload the bundle and
  check the copy, run the agent, write the report and the trace of the tool
  calls to `out/`, clean up.

**Steps:** run the CLI on the sample case with `--keep` (sandbox creation
may occasionally take longer); check the findings, the amounts and the
evidence; change the zip and see the integrity check stop the run; run it
again with `--sandbox-id` to reuse the same sandbox without waiting;
optionally take a snapshot with `--snapshot`.

**You learn:** chain of custody with a hash (and what it does not prove),
structured outputs, continuing a stored conversation, evidence-based reports,
sandbox lifecycle (create, attach, snapshot, cleanup).

**Done when:** `pytest tests/lab3` passes and the report finds the fraud of
the sample case, with its amount and verified evidence.

---

## Lab 4 (optional) — Decision support

**Goal:** bounded decisions on the finished report, with the OpenAI
Decisions API.

**Build with Codex:** `fraud_detective/decisions.py` —
`python -m fraud_detective.decisions out/<bundle>-report.json` sends the report
as `input_json` to the Decisions API (`gpt-6-luna`) with three questions,
in one request: for each finding, the probability of a deliberate act
rather than an error, and of an amount not yet paid that can still be
stopped; for the case, one of four next actions. It prints the answers,
read against thresholds set by people, and writes them next to the report.

**You learn:** the Responses API for open-ended work and the Decisions API
for bounded answers; questions about observable criteria; probabilities and
thresholds; why a model that gives no explanation works on a report and not
instead of it.

**Done when:** `pytest tests/lab4` passes and the decision support separates
the fraud from the honest error of the sample case.
