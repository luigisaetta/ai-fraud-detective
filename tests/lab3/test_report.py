"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Verify strict forensic reports, tolerant citation parsing and
    Markdown rendering.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.lab3.fakes import ModelFake, message, report_data, response, settings
from tests.unit.fakes import FakeSandboxClient
from fraud_detective.agent import AgentResult
from fraud_detective.report import (
    REPORT_REQUEST,
    REPORT_SCHEMA,
    REVIEW_NOTE,
    ClearedItem,
    Evidence,
    EvidenceChecker,
    Finding,
    FraudReport,
    ReportError,
    ReportWriter,
    render_markdown,
)
from fraud_detective.sandbox import SandboxError, SandboxSession
from fraud_detective.tools import BUNDLE_DIR, ToolRegistry

LEVELS = ["high", "medium", "low"]


def _result() -> AgentResult:
    """Build completed accounting for the report continuation request."""
    return AgentResult("Findings", "investigation-last", "answered", 2, (), 10, 5)


def _assert_strict(schema: dict) -> None:
    """Check strict objects at every nesting level, including array items."""
    if schema["type"] == "object":
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == set(schema["required"])
        for child in schema["properties"].values():
            _assert_strict(child)
    elif schema["type"] == "array":
        _assert_strict(schema["items"])


def _finding_schema() -> dict:
    """The schema of one finding."""
    return REPORT_SCHEMA["properties"]["findings"]["items"]


def test_schema_is_strict_at_every_level() -> None:
    """Require strict nested schemas, the level choices and EUR amounts."""
    _assert_strict(REPORT_SCHEMA)
    properties = REPORT_SCHEMA["properties"]
    assert set(properties) == {
        "summary",
        "overall_risk",
        "total_exposure_eur",
        "findings",
        "cleared_items",
        "timeline",
        "next_steps",
    }
    assert properties["overall_risk"]["enum"] == LEVELS
    assert properties["total_exposure_eur"]["type"] == "number"
    finding = _finding_schema()["properties"]
    assert finding["severity"]["enum"] == LEVELS
    assert finding["confidence"]["enum"] == LEVELS
    assert finding["amount_at_risk_eur"]["type"] == "number"
    assert {"supplier_bank_change", "duplicate_payment", "other"} <= set(
        finding["scheme"]["enum"]
    )
    assert set(finding["evidence"]["items"]["properties"]) == {
        "location",
        "observation",
    }


def test_writer_continues_server_conversation() -> None:
    """Send the report request and last id without resending investigation history."""
    client = ModelFake([response("report", message(json.dumps(report_data())))])
    report = ReportWriter(client, "test-model").write(_result())
    assert isinstance(report, FraudReport)
    assert report.total_exposure_eur == 19205.5
    assert isinstance(report.findings[0], Finding)
    assert report.findings[0].evidence == (
        Evidence("ap/invoices.csv:2", "NB-1 entered and approved by MFERRI."),
    )
    assert report.evidence == report.findings[0].evidence
    assert report.cleared_items == (
        ClearedItem("Monthly rent of 18,500 EUR", "Lease agreement PO."),
    )
    assert client.requests == [
        {
            "model": "test-model",
            "previous_response_id": "investigation-last",
            "input": REPORT_REQUEST,
            "store": True,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "fraud_report",
                    "schema": REPORT_SCHEMA,
                    "strict": True,
                }
            },
        }
    ]


@pytest.mark.parametrize(
    "text", ["not JSON", "", "[]", "null", "{}", "```json\n{}\n```"]
)
def test_invalid_json_and_wrong_root(text: str) -> None:
    """Reject malformed JSON, wrong roots and fenced output with ReportError."""
    writer = ReportWriter(ModelFake([response("r", message(text))]), "test-model")
    with pytest.raises(ReportError):
        writer.write(_result())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("overall_risk", "certain"),
        ("summary", 5),
        ("total_exposure_eur", "1000"),
        ("total_exposure_eur", True),
        ("total_exposure_eur", -5),
        ("findings", "a list"),
        ("cleared_items", [{"item": "x"}]),
        ("timeline", [{"time": "now", "event": "x", "evidence": []}]),
        ("next_steps", [None]),
        ("unexpected", "extra"),
    ],
)
def test_schema_mismatches(field: str, value: object) -> None:
    """Validate types, required fields, enums, amounts and additional fields."""
    data = report_data()
    data[field] = value
    client = ModelFake([response("r", message(json.dumps(data)))])
    with pytest.raises(ReportError):
        ReportWriter(client, "test-model").write(_result())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scheme", "embezzlement"),
        ("severity", "critical"),
        ("confidence", "certain"),
        ("amount_at_risk_eur", "9480"),
        ("evidence", [{"location": "a:1"}]),
        ("evidence", [{"location": "a:1", "observation": "x", "extra": "no"}]),
    ],
)
def test_finding_mismatches(field: str, value: object) -> None:
    """Validate every field of a finding, its enums and its evidence."""
    data = report_data()
    data["findings"][0][field] = value
    client = ModelFake([response("r", message(json.dumps(data)))])
    with pytest.raises(ReportError):
        ReportWriter(client, "test-model").write(_result())


def test_integer_amounts_and_no_findings_are_valid() -> None:
    """Accept whole-euro amounts and a review that finds nothing."""
    data = {**report_data(), "total_exposure_eur": 0, "findings": []}
    report = FraudReport.from_dict(data)
    assert report.findings == () and report.evidence == ()


def test_roundtrip_annotations_and_immutability() -> None:
    """Round-trip local annotations without accepting model-supplied verification."""
    original = report_data()
    before = deepcopy(original)
    report = FraudReport.from_dict(original)
    assert original == before
    finding = report.findings[0]
    checked_finding = replace(
        finding, evidence=(replace(finding.evidence[0], verified=True),)
    )
    checked = replace(report, findings=(checked_finding,))
    assert FraudReport.from_dict(checked.to_dict()) == checked
    with pytest.raises(FrozenInstanceError):
        setattr(checked, "overall_risk", "low")
    with pytest.raises(FrozenInstanceError):
        setattr(checked.findings[0].evidence[0], "verified", False)
    data = checked.to_dict()
    data["findings"][0]["evidence"][0]["verified"] = "yes"
    with pytest.raises(ReportError):
        FraudReport.from_dict(data)
    client = ModelFake([response("r", message(json.dumps(checked.to_dict())))])
    with pytest.raises(ReportError):
        ReportWriter(client, "test-model").write(_result())


def test_fragmented_json_and_incomplete_response() -> None:
    """Join JSON fragments exactly and reject explicitly incomplete responses."""
    text = json.dumps(report_data())
    client = ModelFake([response("r", message(text[:25], text[25:]))])
    assert (
        ReportWriter(client, "test-model").write(_result()).summary
        == report_data()["summary"]
    )
    client = ModelFake([response("r", message(text), status="incomplete")])
    with pytest.raises(ReportError, match="incomplete"):
        ReportWriter(client, "test-model").write(_result())


def test_tolerant_citations_and_missing_evidence(tmp_path: Path) -> None:
    """Recognize all prompt formats, mixed lists, wrappers and Unicode ranges."""
    session = SandboxSession(FakeSandboxClient(tmp_path), "fake", owns_sandbox=False)
    session.write_file(
        f"{BUNDLE_DIR}/ap/invoices.csv", "invoice,amount\nNB-1,9480.00\n\n"
    )
    tools = ToolRegistry(session)
    valid = [
        "ap/invoices.csv:2",
        "`ap/invoices.csv:2`",
        "ap/invoices.csv:2-4",
        "ap/invoices.csv:2–4",
        "ap/invoices.csv:2, 9",
        "ap/invoices.csv:2,29-34",
        "  'ap/invoices.csv:2'  ",
        '"ap/invoices.csv:2"',
        "ap/invoices.csv:2—4",
        "ap/invoices.csv:2–4, 9, 20—25",
        " `ap/invoices.csv: 2, 9-12, 20–24` ",
        "ap/invoices.csv:3",
    ]
    invalid = [
        "missing.csv:1",
        "ap/invoices.csv:99",
        "ap/invoices.csv",
        "ap/invoices.csv:0",
        "ap/invoices.csv:1,no",
        "/etc/passwd:1",
        "../secret:1",
        "ap/invoices.csv:two",
        "ap/invoices.csv:2,",
        "",
        None,
    ]
    base = FraudReport.from_dict(report_data())
    half = len(valid) // 2
    findings = (
        replace(
            base.findings[0],
            evidence=tuple(Evidence(loc, "Observation") for loc in valid[:half]),
        ),
        replace(
            base.findings[0],
            title="Second finding",
            evidence=tuple(
                Evidence(loc, "Observation") for loc in valid[half:] + invalid
            ),
        ),
    )
    report = replace(base, findings=findings)
    with patch.object(tools, "call", wraps=tools.call) as call:
        checked = EvidenceChecker(tools).check(report)
    assert [item.verified for item in checked.evidence] == [True] * len(valid) + [
        False
    ] * len(invalid)
    assert all(item.verified is None for item in report.evidence)
    for invocation in call.call_args_list:
        assert invocation.args[0] == "read_file"
        assert invocation.args[1]["start_line"] == invocation.args[1]["end_line"]
    assert call.call_args_list[0].args[1] == {
        "path": "ap/invoices.csv",
        "start_line": 2,
        "end_line": 2,
    }
    with patch.object(tools, "call", side_effect=SandboxError("disconnected")):
        checked = EvidenceChecker(tools).check(report)
    assert all(item.verified is False for item in checked.evidence)


def test_markdown_sections_and_verification_marks() -> None:
    """Render all sections, metadata, amounts, marks and escaped table cells."""
    base = FraudReport.from_dict(report_data())
    finding = replace(
        base.findings[0],
        evidence=(
            Evidence("ap/invoices.csv:2", "ERROR | <script>\nmore", True),
            Evidence("missing:1", "Not found", False),
            Evidence("unchecked:1", "Unchecked"),
        ),
    )
    report = replace(base, findings=(finding,))
    metadata = {
        "bundle": "sample.zip",
        "bundle_sha256": "ab" * 32,
        "date": "2026-11-20",
        "model": "test-model",
        "sandbox": "fake",
        "steps": "2",
        "tool_calls": "1",
        "tokens": "10/5",
    }
    text = render_markdown(report, metadata)
    for heading in (
        "# Forensic Review Report",
        "## Summary",
        "## Findings",
        "### F1. Supplier bank account changed to an employee IBAN",
        "## Cleared items",
        "## Timeline",
        "## Next steps",
    ):
        assert heading in text
    assert REVIEW_NOTE in text
    assert "19,205.50 EUR" in text and "high" in text
    assert "supplier_bank_change" in text
    assert "Lease agreement PO." in text
    assert "✔" in text and "✘" in text and "—" in text
    assert "ERROR \\| &lt;script&gt;<br>more" in text
    assert "1. Stop the scheduled payment." in text
    assert "| Tool Calls | 1 |" in text and "| Bundle SHA-256 |" in text
    assert all(value in text for value in metadata.values())
    assert "first cited line exists" in text


def test_zero_amount_renders_as_no_direct_loss() -> None:
    """Never print a finding without a loss of its own as 0.00 EUR."""
    data = report_data()
    data["findings"][0]["amount_at_risk_eur"] = 0
    text = render_markdown(FraudReport.from_dict(data), {})
    assert "**Amount at risk:** no direct loss" in text
    assert "0.00 EUR" not in text.split("## Findings")[1]


def test_writer_from_settings() -> None:
    """Use the provided client factory with the configured model identifier."""
    configured = settings()
    client = ModelFake([response("r", message(json.dumps(report_data())))])
    with patch("fraud_detective.report.ModelClientFactory") as factory:
        factory.return_value.create.return_value = client
        writer = ReportWriter.from_settings(configured)
        factory.assert_called_once_with(configured)
        factory.return_value.create.assert_called_once_with()
    writer.write(_result())
    assert client.requests[0]["model"] == configured.model_id
