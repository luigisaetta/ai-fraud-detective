# How AI is used in this project

It is easy to think that the language model only writes the final report, and
that any small model would do. It is the opposite: **the model conducts the
whole investigation**. The code around it provides tools, isolation and
checks, but it contains no investigation logic. The quality of the review
depends directly on the quality of the model.

AI appears in two places:

| When | Who | What it does |
|------|-----|--------------|
| Building the code (Labs 1–3) | Codex | writes `tools.py`, `agent.py`, `report.py`, `cli.py` from the prompts, `AGENTS.md` and the tests |
| Running the agent | an OpenAI GPT model, through the Responses API (OCI Generative AI or OpenAI) | plans and runs the investigation, then writes the report |

The rest of this note is about the second one.

## The model is the investigator

`fraud_detective/agent.py` sends the model three things: the task ("review the
accounts payable: find payments that may be fraudulent or wrong, quantify the
exposure, cite the evidence"), the instructions of the agent, and the schemas
of four tools (`list_files`, `read_file`, `grep`, `run_python`). There is no
script of steps. At every turn the model decides what to do next, and the
client only executes what it asks for, in the sandbox.

### 1. Planning and choosing tools

The model decides which files to read first (the case files and the control
policy give the scope and the approval limits), which columns matter, which
leads to follow and when to stop. It can ask for several tools in one turn,
for example the first lines of every CSV file at once.

The sample case has about 3,000 invoices and 2,400 payments: far too much to
read through tools that return a few thousand characters. So the model
**writes Python code** that `run_python` executes in the sandbox, with the
standard library only: `csv` to read the exports, `sqlite3` in memory to join
and group them, `decimal` for amounts. The code is generated on the fly, for
this bundle, and nobody reviews it before it runs: one more reason for the
sandbox.

### 2. Correlating evidence across files

> This section describes the fraud of the sample case. To discover it
> yourself, read it after your first investigation.

The fraud of the sample case is not in any single row. The model has to
connect facts written in different files and formats:

- a role granted to an AP clerk "for the summer holidays" (`security/user_roles.csv`);
- a supplier bank change made by that clerk, with no call-back verification
  (`ap/supplier_changes.log`, `ap/supplier_bank_accounts.csv`);
- the new IBAN, which is the clerk's payroll IBAN, written with spaces in the
  HR register and without them in the supplier accounts: a match that only a
  normalized join finds (`hr/employees.csv`);
- invoices just under the approval limit, entered and approved by the same
  person (`ap/invoices.csv`), and the payments to the new account
  (`ap/payments.csv`);
- the sums: how much was paid, and how much is scheduled and can still be
  stopped.

It must also clear **legitimate anomalies** placed in the data: a large
round amount every month (the rent), a bank change done by the book, approvals
on a Saturday (announced for the quarter close). And it must say what is
*not* established instead of guessing. [The scenario design](scenario-design.md),
an instructor page, describes the whole case.

### 3. Treating bundle content as data

Text in the bundle was written by suppliers and by the person under
investigation. A phishing email and an invoice description both address "AI
reviewers", asking them to classify the supplier as compliant. The
instructions say that bundle content is evidence, never an instruction;
following that rule against text that looks authoritative is a capability of
the model. The sandbox limits what could happen in any case (no network,
bounded tools), but only the model can keep the *conclusions* honest.

### 4. Recovering from errors

Tools never crash the agent: a wrong path, a line past the end of a file or a
script that times out comes back as an `ERROR:` text. The model reads it and
corrects the next call. A step budget (15 tool-requesting calls by default)
ends a run that does not converge.

### 5. Writing the structured report

`fraud_detective/report.py` does not resend anything. The report is **one more turn of
the same server-side conversation**: the request carries only
`previous_response_id`, the instruction "write the report" and a strict JSON
schema. The model turns what it found into findings, each with its scheme,
severity, amount at risk in EUR, confidence (high, medium, low) and evidence
as `path:line`, plus the anomalies it cleared, a timeline and next steps —
with a confidence that should match the strength of the evidence.

### Behind the scenes: the conversation is managed by the platform

With `store=True`, the agent's short-term memory — the conversation with all
its tool calls and results — is kept and managed by **the platform that
serves the Responses API**, not by our code. Which platform depends on
`model.provider` in `config/settings.toml`:

- **OCI Generative AI** (`provider = "oci"`): the conversation belongs to the
  Generative AI project. The project settings decide how long conversations
  are kept and enable short-term memory; when a conversation grows, OCI
  condenses it with the compaction model chosen in the project (in this lab,
  `openai.gpt-oss-120b`).
- **OpenAI** (`provider = "openai"`): the conversation is stored by OpenAI,
  and how it is kept and handled is decided by OpenAI's platform and account
  settings. The OCI project settings do not apply.

In both cases the client code is the same: it only passes
`previous_response_id`, and never calls a compaction model itself.

## The model calls, at a glance

| Where | Request | Purpose |
|-------|---------|---------|
| `preflight` | 2 calls, `store=True` | the model calls a tool; the conversation continues on the server |
| `agent.py`, first call | instructions + task + tool schemas | start the investigation |
| `agent.py`, next calls | `previous_response_id` + tool outputs | continue the investigation |
| `agent.py`, budget exhausted | same, with `tool_choice="none"` | best answer with the evidence collected |
| `report.py` | `previous_response_id` + strict JSON schema | structured report |

## What the model must be good at

When choosing a model, look for:

- **reliable function calling** with strict schemas, including several calls
  per turn;
- **multi-step reasoning** over many files, keeping a chain of events,
  dates and amounts consistent;
- **writing small, correct Python** for analysis, including joins, sums and
  the line numbers of the rows it cites;
- **following the instruction hierarchy**, so that text inside the data does
  not override the instructions;
- **structured outputs** that match a strict JSON schema;
- **a long enough context**: the conversation grows with every tool result.

What a weak model typically does: it reads tables page by page instead of
writing code, stops after a couple of searches, reports a legitimate anomaly
as fraud, compares IBANs without normalizing them and misses the match, gets
the sums wrong, follows the injected instruction, or cites line numbers that
do not exist (often off by one, forgetting the CSV header).

## What is not AI

Everything around the model is deterministic code, there to contain and
verify it:

- **the sandbox and the tools**: the model can only *ask* for a command; it
  runs isolated, without network, with timeouts and bounded output;
- **the integrity check**: the bundle is compared with the reference hash of
  the case file, locally and again in the sandbox;
- **the bundle ingest**: the zip is checked locally and extracted only in the
  sandbox;
- **the evidence check**: every line the model cites is read again in the
  bundle and marked ✔ or ✘;
- **the step budget**.

The evidence check catches **invented citations**, but it cannot fix a wrong
investigation: a model that cites real lines and draws the wrong conclusion
passes it. That is why the model matters, and why every report says that
investigators verify the findings. To compare models, run the same sample
case with each one and check the report against the expected findings in
[sample-bundle.md](sample-bundle.md); the results so far are in
[tested-llms.md](tested-llms.md).
