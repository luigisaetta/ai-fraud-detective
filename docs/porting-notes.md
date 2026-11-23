# Porting to AI Fraud Detective

This is a copy of the Support Bundle Triage Agent workshop, not a scenario
redesign. The `triage` package name, interfaces, provided modules, tests,
reference solutions, and teaching sequence are retained. Participant modules
are absent in the initial checkout; use `./copy_solutions.sh all` to populate
them temporarily and `./clean.sh all` to restore the workshop starting point.

## Reusable as is

- `triage/config.py`: loads settings and secrets for the configured providers.
- `triage/oci_clients.py`: constructs OCI SDK clients.
- `triage/llm.py`: constructs the configured Responses API client.
- `triage/sandbox.py`: manages isolated execution, file transfer, timeouts, and sandbox lifecycle; its `triage` resource-name prefix can stay.
- `triage/ingest.py`: validates and uploads a ZIP safely; the implementation is reusable despite its support-bundle module description.
- `triage/cleanup.py`: lists and deletes leftover sandboxes.
- `triage/preflight/`: environment, model, project, sandbox, and network checks are reusable; the banner in `runner.py` is listed below.
- `triage/tools.py` (Lab 1; reference at `solutions/lab1/tools.py`): sandbox-backed file search, line reads, and Python analysis are scenario independent.
- `triage/agent.py` (Lab 2; reference at `solutions/lab2/agent.py`): the Responses API function-calling loop, stored conversation continuation, tool dispatch, and limits are reusable; its instructions are listed below.
- `config/project-conversation.json`: server-side conversation configuration.
- `config/project-short-term-memory.json`: project memory configuration.
- `config/sandbox-project-deny-all.json`: sandbox outbound network isolation.
- `.env.example`: credential variable template, with no working secrets.
- `requirements.txt`: pinned runtime dependencies.
- `requirements-dev.txt`: test, formatting, and lint dependencies.
- `copy_solutions.sh`: copies reference modules into the participant package.
- `clean.sh`: restores the participant starting point.
- `.gitignore`: excludes secrets, participant modules, caches, and generated outputs already covered by the original workshop.
- `tests/unit/test_config.py`: configuration validation with synthetic OCIDs.
- `tests/unit/test_sandbox.py`: sandbox lifecycle and execution behavior with fakes.
- `tests/unit/test_ingest.py`: ZIP validation and sandbox-only upload behavior.
- `tests/unit/test_preflight.py`: preflight orchestration and console reporting behavior.
- `tests/unit/test_preflight_checks.py`: infrastructure checks with fake clients.
- `tests/unit/fakes.py`: inert OCI sandbox test doubles.

## To adapt for AI Fraud Detective

- `README.md`: workshop title, support-engineer motivation, logs/config/metrics inputs, repository/environment names, sample archive commands, root-cause report, and illustration.
- `AGENTS.md`: support-triage project description and report terminology; this file is maintained by the lab authors and remains read-only.
- `layout.md`: sample support-bundle generator and scenario-oriented directory descriptions.
- `pyproject.toml`: support-triage project metadata and description; keep dependencies and tool settings.
- `config/settings.toml`: support-triage title comment; real project OCIDs and the personal compartment comment have already been replaced with setup placeholders pointing to Lab 0.
- `triage/__init__.py`: package description says it diagnoses customer support bundles.
- `triage/make_bundle.py`: produces `sample-ora00020.zip` containing Oracle alert logs, database parameters, application logs, metrics, a causal configuration change, red herrings, and an untrusted instruction sample.
- `triage/ingest.py`: module description calls the input a support bundle; ZIP safety logic is reusable.
- `triage/preflight/runner.py`: console banner says `SUPPORT BUNDLE TRIAGE AGENT`; check orchestration is reusable.
- `triage/agent.py` (reference at `solutions/lab2/agent.py`): `TRIAGE_INSTRUCTIONS` defines a support engineer investigating a customer bundle and requesting root cause, cited evidence, timeline, confidence, and next steps; identified through `prompts/lab2.md`, without reading the solution.
- `triage/report.py` (reference at `solutions/lab3/report.py`): report request, `triage_report` schema name, `root_cause` field, report types, and rendered headings follow incident diagnosis; identified through `prompts/lab3.md` and acceptance tests, without reading the solution.
- `triage/cli.py` (reference at `solutions/lab3/cli.py`): support-triage banner, default investigation task, result labels, sample archive workflow, and report output naming; identified through `prompts/lab3.md` and acceptance tests, without reading the solution.
- `prompts/lab1.md`: support-bundle context and log/config/metric examples; the tool interfaces are reusable.
- `prompts/lab2.md`: support-engineer role and root-cause instructions in `TRIAGE_INSTRUCTIONS`; preserve the loop and untrusted-data rules.
- `prompts/lab3.md`: diagnosis report schema, CLI wording, ORA-00020 console example, root-cause task, and sample-bundle workflow.
- `labs/lab0.md`: original conda environment name, `support-triage` project display name, and triage-oriented setup examples.
- `labs/lab1.md`: customer diagnostic-bundle context, triage terminology, and evidence examples.
- `labs/lab2.md`: incident diagnosis task, root-cause expectations, and support-investigation walkthrough.
- `labs/lab3.md`: sample Oracle archive, process-limit diagnosis, expected findings, report review, and end-to-end CLI commands.
- `docs/lab-overview.md`: workshop title, diagnostic evidence, support-bundle lab goals, and report expectations.
- `docs/sample-bundle.md`: instructor answer key for ORA-00020, database process/session limits, cited alert logs, red herrings, injection example, and remediation.
- `docs/how-ai-is-used.md`: incident-investigation narrative, sample logs, process-limit correlation, root-cause reporting, and example model/tool calls.
- `docs/easy-path.md`: sample archive generation, triage commands, root-cause result panel, and expected-findings links.
- `docs/setup-venv.md`: original checkout directory and support-triage OCI project examples.
- `docs/tested-llms.md`: manual results for the original Oracle incident; these do not establish fraud-detection performance.
- `images/support-bundle-triage-workshop.prompt.txt`: illustration prompt names the original workshop, diagnostic input files, and root-cause report.
- `images/support-bundle-triage-workshop.png`: existing workshop artwork referenced by the scenario-specific README and its image prompt; retained without regeneration.
- `tests/lab1/test_tools.py`: synthetic sample bundle includes an alert log; generic tool contracts remain reusable.
- `tests/lab2/test_agent.py`: support-bundle fixture, incident task, and assertions about the triage instructions.
- `tests/lab3/fakes.py`: fake root-cause report cites an Oracle alert log and ORA-00020.
- `tests/lab3/test_report.py`: schema, `root_cause`, triage report naming, and report rendering assertions.
- `tests/lab3/test_cli.py`: support-triage banner, Oracle alert-log evidence, result labels, and scenario-specific CLI assertions.
- `tests/unit/test_cleanup.py`: sample sandbox display name uses `support-bundle-triage`; lifecycle assertions are reusable.

The inventory was found with `rg -n -i` searches for `support.bundle`,
`ORA-00020`, `alert.log`, `root.cause`, `support engineer`, and `sample.bundle`,
plus searches for workshop naming. Reference solutions were copied and used
for the requested verification only, without opening or searching their code.
They remain unchanged.

Sanitization replaces both configured project OCIDs with
`ocid1.generativeaiproject.oc1..<your-project-ocid>` and personal GitHub owners
with `<your-github-owner>`. Remaining test OCIDs are deliberately fake;
documentation OCIDs and the configuration validator prefix are examples or
syntax checks. Author headers and the original MIT copyright notice are
retained as attribution. No scenario adaptation has been made.
