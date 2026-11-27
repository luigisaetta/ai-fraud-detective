# Changelog

All significant changes to the workshop are recorded here, newest first.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## What to record

Record every change that a participant, an instructor or an administrator
would notice:

- the lab guides, the Codex prompts and the acceptance tests;
- the provided code, the CLI and the preflight;
- the sample case, its bundle and hash, and the answer key;
- the setup, the configuration and the OCI policies;
- the supported model providers and models.

Typos, wording fixes and internal refactorings with no visible effect need
no entry. Add the entry in the same commit as the change, under
**Unreleased**. On release, rename **Unreleased** to the new version and
date, update `version` in `pyproject.toml` and tag the commit `vX.Y.Z`.

A change to the sample bundle changes its hash: say so in the entry, because
the reference runs in [Tested LLMs](docs/tested-llms.md) and the published
LiveLab refer to the old one.

## [Unreleased]

## [1.0.0] - 2026-11-27

First release of the workshop.

### Added

- Labs 0–3: setup and preflight, sandbox tools, agent loop, report and
  end-to-end run. Participants build each module with Codex from a prompt in
  `prompts/` and check it with the acceptance tests in `tests/`.
- Optional Lab 4: decision support with the OpenAI Decisions API.
- The sample case of Halden Manufacturing: a deterministic generator for the
  accounts payable bundle (`python -m fraud_detective.make_bundle`), the
  reference hash and the answer key, with a reference solver.
- Analysis in an OCI Sandbox with outbound network denied, with integrity
  checks of the bundle before and after the upload.
- A forensic report in JSON and Markdown with verified `file:line`
  evidence, and a trace of every tool call.
- Two model providers: OpenAI and OCI Generative AI.
- A preflight with a quick mode, hints for refused calls, and a cleanup
  command for leftover sandboxes.
- Setup with Conda or Python venv, the OCI policies for the workshop
  compartment, and the instructor pages: scenario design, expected findings,
  data preview and tested models.

[Unreleased]: https://github.com/luigisaetta/ai-fraud-detective/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/luigisaetta/ai-fraud-detective/releases/tag/v1.0.0
