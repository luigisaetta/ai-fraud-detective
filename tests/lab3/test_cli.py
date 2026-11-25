"""
Author: L. Saetta
Date Last Modified: 2026-11-25
License: MIT
Description: Test CLI output, the integrity check, the trace of the tool calls,
    progress throttling and sandbox lifecycle with local fakes.
"""

from dataclasses import dataclass, replace
import hashlib
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from openai import APIError
import pytest

from tests.lab3.fakes import (
    ModelFake,
    SnapshotFake,
    investigation_script,
    message,
    report_data,
    response,
    settings,
)
from fraud_detective import cli
from fraud_detective.agent import AgentResult, ToolCall
from fraud_detective.cli import BOX_WIDTH, DEFAULT_TASK, InvestigationApp, render_trace
from fraud_detective.config import Settings
from fraud_detective.ingest import BundleError
from fraud_detective.report import ReportError
from fraud_detective.sandbox import SandboxError, SandboxManager, SandboxSession

COLOR_CODE = re.compile(r"\033\[[0-9;]*m")
BOX_CHARS = ("╭", "│", "╰")


def write_reference(bundle: Path) -> str:
    """Record the reference hash of a bundle next to it, as the case file does.

    Args:
        bundle: The zip file.

    Returns:
        The SHA-256 written to the .sha256 file.
    """
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    bundle.with_suffix(".sha256").write_text(f"{digest}  {bundle.name}\n")
    return digest


def plain(text: str) -> str:
    """Remove color codes, keeping the cursor controls of the progress line.

    Args:
        text: Captured console output.

    Returns:
        The same text without SGR color sequences.
    """
    return COLOR_CODE.sub("", text)


def box_lines(text: str) -> list[str]:
    """Collect the lines of the banner and of the result panel.

    Args:
        text: Captured console output, without color codes.

    Returns:
        Every line drawn as part of a box.
    """
    return [line for line in text.splitlines() if line.startswith(BOX_CHARS)]


class TerminalStream(io.StringIO):
    """Capture raw terminal writes for progress rendering tests."""

    def isatty(self) -> bool:
        """Report terminal behavior.

        Returns:
            True, without needing an interactive terminal in the test runner.
        """
        return True


@dataclass
class Harness:
    """Dependencies for one inert end-to-end investigation."""

    client: SnapshotFake
    manager: SandboxManager
    model: ModelFake
    bundle: Path
    output: Path
    stream: io.StringIO
    settings: Settings

    def app(self) -> InvestigationApp:
        """Construct an app with real orchestration and fake external services.

        Returns:
            Application backed by the current test's resources.
        """
        return InvestigationApp(
            self.settings, self.manager, self.model, self.output, self.stream
        )


@pytest.fixture(name="harness")
def fixture_harness(tmp_path: Path) -> Harness:
    """Create a bundle and real manager over the provided local sandbox fake.

    Args:
        tmp_path: Isolated filesystem root for the test.

    Returns:
        Dependencies for one investigation, without OCI or model network access.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    client = SnapshotFake(root)
    configured = settings()
    manager = SandboxManager(client, configured.oci_project_id)
    bundle = tmp_path / "sample.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(
            "ap/invoices.csv",
            "invoice,supplier,amount,entered_by,approved_by\n"
            "NB-1,S2031,9480.00,MFERRI,MFERRI\n",
        )
        archive.writestr("policy/ap_controls.md", "Nobody approves own invoices.\n")
    write_reference(bundle)
    return Harness(
        client,
        manager,
        ModelFake(investigation_script()),
        bundle,
        tmp_path / "out",
        io.StringIO(),
        configured,
    )


def test_end_to_end_reports_and_cleanup(harness: Harness) -> None:
    """Run real upload, tool execution, report checking and lifecycle operations."""
    path = harness.app().run(harness.bundle)
    assert path == harness.output / "sample-report.md"
    markdown = path.read_text(encoding="utf-8")
    saved = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(harness.bundle.read_bytes()).hexdigest()
    assert saved["total_exposure_eur"] == report_data()["total_exposure_eur"]
    assert saved["findings"][0]["evidence"][0]["verified"] is True
    assert saved["bundle_sha256"] == digest
    assert "verify" in saved["review_note"].lower()
    assert "✔" in markdown and "| Steps | 2 |" in markdown
    assert digest in markdown
    assert "30 input / 11 output (investigation)" in markdown
    assert harness.client.calls[0] == "create"
    assert harness.client.calls[-2:] == ["stop", "delete"]
    requests = harness.model.requests
    assert requests[1]["previous_response_id"] == "investigation-1"
    assert (
        "ap/invoices.csv:2: NB-1,S2031,9480.00,MFERRI,MFERRI"
        in requests[1]["input"][0]["output"]
    )
    assert requests[2]["previous_response_id"] == "investigation-2"
    assert requests[2]["text"]["format"]["strict"] is True
    assert all(request["store"] is True for request in requests)
    text = harness.stream.getvalue()
    steps = (
        "1. Integrity",
        "2. Sandbox",
        "3. Bundle",
        "4. Investigation",
        "5. Report",
        "6. Cleanup",
    )
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    for value in (
        f"SHA-256 matches the reference: {digest[:16]}",
        "Copy in the sandbox matches the reference hash",
        "a cold start can take minutes",
        "RUNNING",
        "2 files",
        "step 1: read_file",
        "Overall risk: high",
        "Total exposure: 19,205.50 EUR",
        "F1 [high]",
        "Evidence verified: 1/1",
        str(path),
        str(path.with_suffix(".json")),
        str(harness.output / "sample-trace.md"),
    ):
        assert value in text


def test_end_to_end_writes_the_trace(harness: Harness) -> None:
    """Save every tool call, with its arguments and output, next to the report."""
    harness.app().run(harness.bundle)
    trace = (harness.output / "sample-trace.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(harness.bundle.read_bytes()).hexdigest()
    assert trace.startswith("# Investigation Trace")
    assert "case data" in trace
    assert digest in trace and "| Tool Calls | 1 |" in trace
    assert "## 1. read_file" in trace
    assert '"path": "ap/invoices.csv"' in trace
    assert "ap/invoices.csv:2: NB-1,S2031,9480.00,MFERRI,MFERRI" in trace


def _result(*calls: ToolCall) -> AgentResult:
    """An investigation result with the given tool calls."""
    return AgentResult(
        answer="done",
        response_id="r-1",
        stopped_reason="answered",
        steps=len(calls) + 1,
        tool_calls=calls,
        input_tokens=1,
        output_tokens=1,
    )


def test_trace_shows_the_code_of_run_python() -> None:
    """Show the Python the model wrote as code, not as a JSON string."""
    code = "import csv\nprint('rows', 3)"
    trace = render_trace(
        _result(ToolCall("run_python", json.dumps({"code": code}), "rows 3\n")),
        {"bundle": "sample.zip"},
    )
    assert "## 1. run_python" in trace
    assert "```python\nimport csv\nprint('rows', 3)\n```" in trace
    assert "```text\nrows 3\n```" in trace
    assert "| Bundle | sample.zip |" in trace


def test_trace_keeps_invalid_arguments_and_backticks_readable() -> None:
    """Show invalid JSON as sent, and fence output that contains backticks."""
    trace = render_trace(
        _result(
            ToolCall("grep", "{not json", "ERROR: invalid arguments"),
            ToolCall("read_file", json.dumps({"path": "a.md"}), "a.md:1: ```x```"),
        ),
        {},
    )
    assert "```text\n{not json\n```" in trace
    assert "## 2. read_file" in trace
    assert "````text\na.md:1: ```x```\n````" in trace


def test_trace_without_tool_calls() -> None:
    """Say so when the model answered without calling a tool."""
    trace = render_trace(_result(), {})
    assert "The model called no tools." in trace
    assert "## 1." not in trace


def test_banner_and_result_panel(harness: Harness) -> None:
    """Open with the banner and end with the summary and findings in a panel."""
    harness.app().run(harness.bundle)
    text = harness.stream.getvalue()
    assert "\033[" not in text  # no escape codes on a non-terminal stream
    assert text.index("AI FRAUD DETECTIVE") < text.index("1. Integrity")
    assert "sample.zip" in text and "test-model" in text
    panel = " ".join(
        line[1:-1].strip()
        for line in box_lines(text[text.index("Investigation result") - 3 :])
    )
    panel = " ".join(panel.split())
    assert text.index("6. Cleanup") < text.index("Investigation result")
    for value in (
        "Summary:",
        report_data()["summary"],
        "Overall risk: high",
        "Total exposure: 19,205.50 EUR",
        "Findings (1):",
        "F1 [high] Supplier bank account changed to an employee IBAN",
        "Evidence verified: 1/1",
        "Bundle SHA-256:",
    ):
        assert value in panel
    assert box_lines(text) and all(len(line) == BOX_WIDTH for line in box_lines(text))


def test_long_texts_wrap_inside_the_boxes(harness: Harness) -> None:
    """Wrap a long summary without losing words; cut a long model id in the banner."""
    summary = " ".join(f"word{index}" for index in range(60))
    long_report = {**report_data(), "summary": summary}
    script = investigation_script()
    script[-1] = response("report-1", message(json.dumps(long_report)))
    harness.model = ModelFake(script)
    harness.settings = replace(harness.settings, model_id="m" * 200)
    harness.app().run(harness.bundle)
    text = harness.stream.getvalue()
    lines = box_lines(text)
    assert all(len(line) == BOX_WIDTH for line in lines)
    start = next(i for i, line in enumerate(lines) if "Investigation result" in line)
    panel = " ".join(lines[start:])
    assert all(f"word{index}" in panel.split() for index in range(60))
    assert "…" in text


@pytest.mark.parametrize("no_color", [False, True])
def test_terminal_colors_respect_no_color(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, no_color: bool
) -> None:
    """Color a terminal stream, and keep it plain when NO_COLOR is set."""
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    harness.stream = TerminalStream()
    harness.app().run(harness.bundle)
    text = harness.stream.getvalue()
    assert bool(COLOR_CODE.search(text)) is not no_color
    assert all(len(line) == BOX_WIDTH for line in box_lines(plain(text)))


def test_keep_prints_reuse_command(harness: Harness) -> None:
    """Preserve a newly created sandbox and show its id and reuse command."""
    assert harness.app().run(harness.bundle, keep=True).is_file()
    assert "create" in harness.client.calls
    assert "stop" not in harness.client.calls and "delete" not in harness.client.calls
    assert "Sandbox kept: ocid1.sandbox.fake" in harness.stream.getvalue()
    assert "--sandbox-id ocid1.sandbox.fake" in harness.stream.getvalue()
    assert "python -m fraud_detective.cli" in harness.stream.getvalue()


def test_attached_sandbox_is_never_closed(harness: Harness) -> None:
    """Do not call close on an attached session, even though close itself is safe."""
    with patch.object(SandboxSession, "close", autospec=True) as close:
        harness.app().run(harness.bundle, sandbox_id="existing")
    close.assert_not_called()
    assert "create" not in harness.client.calls and "stop" not in harness.client.calls
    assert "Attached sandbox preserved: existing" in harness.stream.getvalue()


def test_snapshot_before_close(harness: Harness) -> None:
    """Exercise real session snapshot handling with a fake ACTIVE response."""
    harness.app().run(harness.bundle, snapshot=True)
    assert harness.client.calls[-3:] == ["snapshot", "stop", "delete"]
    assert "Snapshot: snapshot-fake" in harness.stream.getvalue()


def test_slow_close_keeps_successful_report(harness: Harness) -> None:
    """Warn with manual deletion guidance and return the report after slow closure."""
    with patch.object(
        SandboxSession, "close", side_effect=SandboxError("still STOPPING...")
    ):
        path = harness.app().run(harness.bundle)
    assert path.is_file() and path.with_suffix(".json").is_file()
    text = harness.stream.getvalue()
    assert "WARNING:" in text and "ocid1.sandbox.fake" in text
    assert "delete it from the OCI Console once it is STOPPED" in text
    assert "ERROR:" not in text


def test_bad_bundle_prints_once_and_cleans_up(harness: Harness) -> None:
    """Reject bad zip data before model use, then still close the created session."""
    harness.bundle.write_text("not a zip", encoding="utf-8")
    write_reference(harness.bundle)
    with pytest.raises(BundleError, match="not a zip"):
        harness.app().run(harness.bundle)
    assert harness.client.calls[-2:] == ["stop", "delete"]
    assert harness.model.requests == []
    assert harness.stream.getvalue().count("ERROR:") == 1
    assert "Traceback" not in harness.stream.getvalue()
    assert "6. Cleanup" in harness.stream.getvalue()


def test_zero_amount_reads_as_no_direct_loss(harness: Harness) -> None:
    """Show a finding without a loss of its own as such, not as 0.00 EUR."""
    data = report_data()
    data["findings"].append(
        {**data["findings"][0], "title": "Conflicting roles", "amount_at_risk_eur": 0}
    )
    script = investigation_script()
    script[-1] = response("report-1", message(json.dumps(data)))
    harness.model = ModelFake(script)
    path = harness.app().run(harness.bundle)
    text = " ".join(plain(harness.stream.getvalue()).split())
    assert "F2 [high] Conflicting roles · no direct loss" in text
    assert "0.00 EUR" not in text
    assert "no direct loss" in path.read_text(encoding="utf-8")


def test_missing_reference_hash_stops_before_the_sandbox(harness: Harness) -> None:
    """Refuse a bundle without its reference hash, before allocating anything."""
    harness.bundle.with_suffix(".sha256").unlink()
    with pytest.raises(BundleError, match="reference hash not found"):
        harness.app().run(harness.bundle)
    assert harness.client.calls == [] and harness.model.requests == []
    assert harness.stream.getvalue().count("ERROR:") == 1
    assert "2. Sandbox" not in harness.stream.getvalue()


def test_changed_bundle_stops_before_the_sandbox(harness: Harness) -> None:
    """Refuse a bundle changed after the extraction, before allocating anything."""
    with zipfile.ZipFile(harness.bundle, "a") as archive:
        archive.writestr("ap/extra.csv", "added later\n")
    with pytest.raises(BundleError, match="does not match the reference hash"):
        harness.app().run(harness.bundle)
    assert harness.client.calls == [] and harness.model.requests == []
    assert harness.stream.getvalue().count("ERROR:") == 1


def test_expected_sha256_option_replaces_the_file(harness: Harness) -> None:
    """Accept the reference hash on the command line instead of the .sha256 file."""
    digest = hashlib.sha256(harness.bundle.read_bytes()).hexdigest()
    harness.bundle.with_suffix(".sha256").unlink()
    status = _main(
        harness,
        ["--output-dir", str(harness.output), "--expected-sha256", digest.upper()],
    )
    assert status == 0
    assert (harness.output / "sample-report.md").is_file()
    assert _main(harness, ["--expected-sha256", "0" * 64]) == 1


@pytest.mark.parametrize("attached", [False, True])
def test_bundle_failure_respects_ownership(harness: Harness, attached: bool) -> None:
    """Preserve the selected sandbox after failure when attached or explicitly kept."""
    harness.bundle.write_text("bad zip", encoding="utf-8")
    write_reference(harness.bundle)
    with patch.object(SandboxSession, "close", autospec=True) as close:
        with pytest.raises(BundleError):
            harness.app().run(
                harness.bundle,
                keep=not attached,
                sandbox_id="existing" if attached else None,
            )
    close.assert_not_called()


@pytest.mark.parametrize("failure", ["api", "report", "interrupt"])
def test_model_failure_and_ctrl_c_cleanup(harness: Harness, failure: str) -> None:
    """Clean up after API errors, bad report JSON or KeyboardInterrupt."""
    if failure == "api":
        harness.model = ModelFake(
            [
                APIError(
                    "Model unavailable\nretry later",
                    request=SimpleNamespace(),
                    body=None,
                )
            ]
        )
        expected = APIError
    elif failure == "interrupt":
        harness.model = ModelFake([KeyboardInterrupt()])
        expected = KeyboardInterrupt
    else:
        harness.model = ModelFake(
            [
                response("answer", message("Findings")),
                response("report", message("bad JSON")),
            ]
        )
        expected = ReportError
    with pytest.raises(expected):
        harness.app().run(harness.bundle)
    assert harness.client.calls[-2:] == ["stop", "delete"]
    errors = [
        line for line in harness.stream.getvalue().splitlines() if "ERROR:" in line
    ]
    assert len(errors) == 1 and "Traceback" not in errors[0]


def test_slow_close_does_not_hide_original_error(harness: Harness) -> None:
    """Keep an investigation failure as a failure when cleanup also needs attention."""
    harness.bundle.write_text("bad zip", encoding="utf-8")
    write_reference(harness.bundle)
    with patch.object(
        SandboxSession, "close", side_effect=SandboxError("still STOPPING")
    ):
        with pytest.raises(BundleError, match="not a zip"):
            harness.app().run(harness.bundle)
    text = harness.stream.getvalue()
    assert text.count("ERROR:") == 1 and "WARNING:" in text


def test_snapshot_failure_still_closes_owned_session(harness: Harness) -> None:
    """Treat a requested snapshot failure as an error while ensuring closure."""
    with patch.object(
        SandboxSession, "snapshot", side_effect=SandboxError("snapshot failed")
    ):
        with pytest.raises(SandboxError, match="snapshot failed"):
            harness.app().run(harness.bundle, snapshot=True)
    assert harness.client.calls[-2:] == ["stop", "delete"]
    assert harness.stream.getvalue().count("ERROR:") == 1


def test_invalid_settings_allocate_no_resources(harness: Harness) -> None:
    """Validate settings before creating or attaching a sandbox."""
    harness.settings = replace(harness.settings, model_id="")
    with pytest.raises(ValueError, match="model.model_id"):
        harness.app().run(harness.bundle)
    assert harness.client.calls == [] and harness.model.requests == []


def test_output_error_still_closes_session(harness: Harness) -> None:
    """Clean up if a report destination is occupied by a regular file."""
    harness.output.write_text("occupied", encoding="utf-8")
    with pytest.raises(OSError):
        harness.app().run(harness.bundle)
    assert harness.client.calls[-2:] == ["stop", "delete"]
    assert harness.stream.getvalue().count("ERROR:") == 1


def test_many_nonterminal_states_are_throttled(harness: Harness) -> None:
    """Reduce repeated real-manager callbacks using a patched progress clock."""
    assert harness.stream.isatty() is False
    harness.client.queue_states(["CREATING"] * 100 + ["RUNNING"])
    with (
        patch("fraud_detective.sandbox.time.sleep"),
        patch("fraud_detective.cli.monotonic", side_effect=range(1000)),
    ):
        harness.app().run(harness.bundle)
    lines = harness.stream.getvalue().splitlines()
    assert len([line for line in lines if line.strip().startswith("CREATING,")]) == 4
    assert len([line for line in lines if line.strip().startswith("RUNNING,")]) == 1
    assert (
        "\r" not in harness.stream.getvalue()
        and "\033[K" not in harness.stream.getvalue()
    )


def test_state_changes_print_immediately(harness: Harness) -> None:
    """Print first state, periodic updates and state changes on redirected streams."""
    times = [0, 1, 29, 30, 31, 59, 60, 61, 62, 63]
    with patch("fraud_detective.cli.monotonic", side_effect=times):
        progress = cli._Progress(harness.stream)
        for index in range(7):
            progress(f"CREATING, {times[index]} s")
        progress("RUNNING, 61 s")
        progress("STOPPING, 62 s")
        progress("STOPPING, 63 s")
        progress.close()
    assert [line.strip() for line in harness.stream.getvalue().splitlines()] == [
        "CREATING, 0 s",
        "CREATING, 30 s",
        "CREATING, 60 s",
        "RUNNING, 61 s",
        "STOPPING, 62 s",
    ]


def test_terminal_progress_rewrites_and_finishes_each_step(harness: Harness) -> None:
    """Keep state messages on one terminal line and terminate it before the next step."""
    harness.stream = TerminalStream()
    harness.client.queue_states(["CREATING"] * 20 + ["RUNNING"])
    with patch("fraud_detective.sandbox.time.sleep"):
        harness.app().run(harness.bundle)
    text = plain(harness.stream.getvalue())
    assert len(re.findall(r"\r[^\n\r]*CREATING,", text)) == 20
    assert not re.search(r"\n[^\n\r]*CREATING,", text)
    assert re.search(r"\r[^\n\r]*(CREATING|RUNNING),[^\n\r]*\033\[K\n", text)
    assert re.search(r"\r[^\n\r]*deleting\033\[K\n", text)


def test_terminal_progress_finishes_after_creation_error(harness: Harness) -> None:
    """End an active status line even when creation fails before returning a session."""
    harness.stream = TerminalStream()

    def fail_create(**kwargs: object) -> None:
        """Emit one state and fail without allocating a real resource."""
        kwargs["on_progress"]("CREATING, 0 s")
        raise SandboxError("cannot start")

    with patch.object(harness.manager, "create", side_effect=fail_create):
        with pytest.raises(SandboxError, match="cannot start"):
            harness.app().run(harness.bundle)
    text = plain(harness.stream.getvalue())
    assert re.search(r"\033\[K\n[^\n]*ERROR: cannot start\n", text)


def _main(harness: Harness, arguments: list[str]) -> int:
    """Run the real parser and main, replacing only external dependency factories."""
    with (
        patch("sys.argv", ["fraud_detective.cli", str(harness.bundle), *arguments]),
        patch("sys.stdout", harness.stream),
        patch("fraud_detective.cli.Settings.load", return_value=harness.settings),
        patch("fraud_detective.cli.OciClients") as clients,
        patch(
            "fraud_detective.cli.SandboxManager.from_settings",
            return_value=harness.manager,
        ) as manager,
        patch("fraud_detective.cli.ModelClientFactory") as model_factory,
    ):
        model_factory.return_value.create.return_value = harness.model
        status = cli.main()
        if not harness.settings.validate():
            clients.assert_called_once_with(harness.settings)
            manager.assert_called_once_with(harness.settings, clients.return_value)
            model_factory.assert_called_once_with(harness.settings)
        else:
            clients.assert_not_called()
            manager.assert_not_called()
            model_factory.assert_not_called()
    return status


def test_main_options_and_forced_final_answer(harness: Harness) -> None:
    """Pass all run options through the real argument parser and orchestrator."""
    assert (
        _main(
            harness,
            [
                "--output-dir",
                str(harness.output),
                "--task",
                "Custom task",
                "--max-steps",
                "1",
                "--keep",
                "--snapshot",
            ],
        )
        == 0
    )
    assert (harness.output / "sample-report.md").is_file()
    digest = hashlib.sha256(harness.bundle.read_bytes()).hexdigest()
    assert harness.model.requests[0]["input"] == [
        {"role": "user", "content": cli.task_with_integrity("Custom task", digest)}
    ]
    assert harness.model.requests[1]["tool_choice"] == "none"
    assert "snapshot" in harness.client.calls and "stop" not in harness.client.calls


def test_main_defaults_and_attachment(harness: Harness) -> None:
    """Use the default task and honor --sandbox-id without allocating a sandbox."""
    assert (
        _main(
            harness, ["--output-dir", str(harness.output), "--sandbox-id", "existing"]
        )
        == 0
    )
    digest = hashlib.sha256(harness.bundle.read_bytes()).hexdigest()
    content = harness.model.requests[0]["input"][0]["content"]
    assert content == cli.task_with_integrity(DEFAULT_TASK, digest)
    assert content.startswith(DEFAULT_TASK) and digest in content
    assert "create" not in harness.client.calls and "stop" not in harness.client.calls
    arguments = cli._parser().parse_args([str(harness.bundle)])
    assert arguments.output_dir == Path("out") and arguments.max_steps == 15


def test_main_invalid_settings_exit_one(harness: Harness) -> None:
    """Print configuration problems without creating external clients."""
    harness.settings = replace(harness.settings, model_id="", oci_region="")
    assert _main(harness, []) == 1
    assert "model.model_id is not set" in harness.stream.getvalue()
    assert "oci.region is not set" in harness.stream.getvalue()
    assert harness.client.calls == []


def test_main_bad_bundle_exit_one(harness: Harness) -> None:
    """Print one expected error and return one after cleaning up the sandbox."""
    harness.bundle.write_text("bad zip", encoding="utf-8")
    write_reference(harness.bundle)
    assert _main(harness, []) == 1
    assert harness.stream.getvalue().count("ERROR:") == 1
    assert harness.client.calls[-2:] == ["stop", "delete"]


def test_main_ctrl_c_exit_code(harness: Harness) -> None:
    """Return the conventional interruption status after cleanup."""
    harness.model = ModelFake([KeyboardInterrupt()])
    assert _main(harness, []) == 130
    assert harness.client.calls[-2:] == ["stop", "delete"]
    assert harness.stream.getvalue().count("ERROR:") == 1


def test_main_slow_close_exits_zero(harness: Harness) -> None:
    """Preserve CLI success after close raises SandboxError, as required by the prompt."""
    with patch.object(
        SandboxSession, "close", side_effect=SandboxError("still STOPPING...")
    ):
        status = _main(harness, ["--output-dir", str(harness.output)])
    assert status == 0
    assert (harness.output / "sample-report.md").is_file()
    assert "WARNING:" in harness.stream.getvalue()
    assert (
        "delete it from the OCI Console once it is STOPPED" in harness.stream.getvalue()
    )
    assert "ERROR:" not in harness.stream.getvalue()
