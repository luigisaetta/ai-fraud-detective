# Lab 3 — Report and end-to-end run

**Time:** normally 5–7 minutes of hands-on work, plus reading and review.
Sandbox creation may occasionally take longer.
**You build:** `triage/report.py` and `triage/cli.py`, with Codex.
**Runs on:** a real OCI Sandbox and the real model.

## Goal

Put everything together: one command verifies a case bundle, runs the
investigation in an OCI Sandbox and writes a forensic report.

```
python -m triage.cli bundles/halden-ap-q3-2026.zip
```

1. **Integrity** — check the bundle against the reference hash of the case
   file, before any sandbox exists.
2. **Sandbox** — create one (or attach to an existing one).
3. **Bundle** — upload the zip, check the hash of the copy in the sandbox,
   extract it there.
4. **Investigation** — the agent of Lab 2 explores the bundle with the tools
   of Lab 1.
5. **Report** — a structured report, with every cited line checked in the
   bundle.
6. **Cleanup** — delete the sandbox, keep it for another run, or snapshot it.

## Why it matters

- **Chain of custody.** The hash proves that the data analysed is the data
  IT extracted: nobody changed it on the way, and the report states the hash
  of the bundle it analysed. It does not prove that the content is honest:
  the rows under investigation were written by the suspect, which is why the
  analysis still runs in the sandbox.
- **The report is one more turn of the same conversation.** The model already
  holds every tool result on the server: the client sends only
  `previous_response_id` and a request for the report, and nothing is resent.
- **Structured output.** The report follows a strict JSON schema: several
  findings, each with its scheme, severity, confidence, amount at risk in EUR
  and evidence, plus the anomalies cleared, a timeline and next steps. A
  program can use it, and a Markdown version is rendered for people.
- **Evidence you can check.** For each citation such as
  `ap/invoices.csv:2317`, the CLI reads that line in the sandbox and marks it
  ✔ or ✘. A ✘ means the model cited a line that does not exist.
- **A human decides.** Every report carries a fixed note: the findings come
  from an AI agent and the investigators verify them before drawing
  conclusions.
- **Sandbox lifecycle.** Creation and deletion together normally take less
  than 20 seconds, though creation may occasionally take longer. `--keep` and
  `--sandbox-id` let you reuse a sandbox; `--snapshot` saves the workspace of
  the investigation.

## Before you start

Lab 3 builds on your `triage/tools.py` (Lab 1) and `triage/agent.py`
(Lab 2). Check them:

```bash
python -m pytest tests/lab1 tests/lab2 -q
```

If the tests fail or a file is missing, copy the reference solutions:

```bash
cp solutions/lab1/tools.py solutions/lab2/agent.py triage/
```

Then write the sample case:

```bash
python -m triage.make_bundle
```

It writes `bundles/halden-ap-q3-2026.zip`, the extraction run by Halden IT:
nine months of accounts payable (suppliers, bank accounts, change log,
invoices, payments), employees, user roles, the AP shared mailbox, the
control policy and the case files. Next to it,
`bundles/halden-ap-q3-2026.sha256` stands for the hash recorded in the case
file. The data hides a fraud, an honest error, some legitimate anomalies and
text that tries to give orders to the AI.

## Steps

### 1. See the tests fail

```bash
python -m pytest tests/lab3 -q
```

They fail with `ModuleNotFoundError`: `triage.report` and `triage.cli` do
not exist yet.

### 2. Ask Codex to build the report and the CLI

Open Codex in the repository root and enter:

```
Read prompts/lab3.md and do what it says (everything below the first line).
```

The tests use a fake model and a fake sandbox: Codex does not start a real
sandbox. You will run the CLI yourself in step 5.

### 3. Review what Codex wrote

- `triage/report.py`: `ReportWriter.write()` sends `previous_response_id`,
  `store=True` and the strict JSON schema; `EvidenceChecker` reads the first
  cited line of each evidence of each finding and never raises.
- `triage/cli.py`: the six numbered steps; the integrity check comes before
  the sandbox; the cleanup runs also after an error or Ctrl+C; a sandbox
  given with `--sandbox-id` is never deleted.

### 4. Run the checks

```bash
python -m pytest tests/unit tests/lab1 tests/lab2 tests/lab3 -q
python -m black --check triage tests
python -m pylint triage
```

### 5. Run the investigation on a real sandbox

```bash
python -m triage.cli bundles/halden-ap-q3-2026.zip --keep
```

Sandbox creation is normally quick but may occasionally take several minutes.
The CLI shows its state while you wait. It opens with a banner and shows the
six steps as they run; because of `--keep`, the cleanup step prints the id of
the sandbox and the command to reuse it. It ends with a result panel: the
summary, the overall risk, the total exposure, one line per finding, how many
cited lines were verified and the hash of the bundle.

Open the report:

```bash
open -t out/halden-ap-q3-2026-report.md
```

Check it:

- Did the agent find where the money went, and how much is at risk? How much
  can still be stopped?
- Are the cited lines verified (✔)? Open a few of them in the bundle.
- Did it explain anomalies that turned out to be legitimate, instead of
  reporting them as fraud?
- Did it follow the text addressed to the AI? It must not.

The instructor has the expected findings. Try also to change the bundle:
any change to the zip makes step 1 fail, before a sandbox is created.

### 6. Run again without waiting (optional)

Reuse the sandbox from step 5 — no start-up wait:

```bash
python -m triage.cli bundles/halden-ap-q3-2026.zip --sandbox-id <sandbox-id>
```

Try `--snapshot` to save the workspace, or `--task` to ask a different
question about the same bundle.

### 7. Clean up

A sandbox kept with `--keep` expires after `sandbox.lifetime_minutes` (60 by
default) and becomes `STOPPED`, but it is not deleted. Without `--keep`, the
CLI deletes the sandbox at the end; if the service is slow to stop it, the
CLI prints a warning and the sandbox is left behind. Leftover sandboxes use
quota. List the sandboxes of your project:

```bash
python -m triage.cleanup
```

Then remove them (the command shows the list and asks for a confirmation):

```bash
python -m triage.cleanup --delete
```

It deletes the sandboxes that are `STOPPED` or `FAILED` and asks the running
ones to stop, without waiting for completion. If any are still stopping, run
it again later to delete them. It considers every sandbox of the project, so
run it only on the project you created for the labs.

## Done when

- `python -m pytest tests/unit tests/lab1 tests/lab2 tests/lab3 -q` passes.
- `out/halden-ap-q3-2026-report.md` has findings with amounts and verified
  evidence.
- You can explain what the hash proves and what it does not, why the report
  request sends no history, and what a ✘ in the evidence table would mean.

## Stuck?

Copy the reference solution and run step 5:

```bash
cp solutions/lab3/report.py solutions/lab3/cli.py triage/
```
