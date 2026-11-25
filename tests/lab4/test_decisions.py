"""
Author: L. Saetta
Date Last Modified: 2026-11-25
License: MIT
Description: Test the decision support of Lab 4 with a fake Decisions API
    client: the questions, the request, the answers, refusals, the output
    files and the command line. No network calls.
"""

from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from openai.types import Decision
import pytest

from fraud_detective import decisions
from fraud_detective.config import ModelProvider
from fraud_detective.decisions import (
    ACTIONS,
    DECISION_NOTE,
    LIKELY,
    REPORT_FIELDS,
    UNLIKELY,
    CaseAdvice,
    DecisionAdvisor,
    DecisionError,
    FindingAdvice,
    build_questions,
    likelihood,
    load_report,
    output_paths,
    render_markdown,
)
from tests.lab3.fakes import settings as base_settings


def _report() -> dict:
    """A saved report with two findings, as written by the CLI of Lab 3."""
    finding = {
        "scheme": "other",
        "severity": "high",
        "amount_at_risk_eur": 100.0,
        "confidence": "high",
        "description": "Described.",
        "evidence": [{"location": "a.csv:2", "observation": "Seen.", "verified": True}],
    }
    return {
        "bundle_sha256": "ab" * 32,
        "review_note": "Verify the findings.",
        "summary": "Two findings.",
        "overall_risk": "high",
        "total_exposure_eur": 150.0,
        "findings": [
            {**finding, "title": "Payments diverted | to a clerk"},
            {**finding, "title": "Duplicate payment", "amount_at_risk_eur": 50.0},
        ],
        "cleared_items": [{"item": "Rent", "reason": "Monthly."}],
        "timeline": [],
        "next_steps": ["Hold the payment."],
    }


def _answers(**overrides: Any) -> list[dict]:
    """Answers to the questions of _report(), in an order different from them."""
    answers = {
        "case_action": {
            "type": "choice",
            "name": "case_action",
            "choice": "stop_payments_and_escalate",
            "confidence": 0.97,
            "probabilities": [
                {"value": value, "probability": 0.97 if index == 0 else 0.01}
                for index, (value, _) in enumerate(ACTIONS)
            ],
        },
        "F2_stoppable": {
            "type": "predicate",
            "name": "F2_stoppable",
            "probability": 0.0,
        },
        "F1_deliberate": {
            "type": "predicate",
            "name": "F1_deliberate",
            "probability": 0.86,
        },
        "F1_stoppable": {
            "type": "predicate",
            "name": "F1_stoppable",
            "probability": 1.0,
        },
        "F2_deliberate": {
            "type": "predicate",
            "name": "F2_deliberate",
            "probability": 0.05,
        },
    }
    answers.update(overrides)
    return [answer for answer in answers.values() if answer is not None]


class FakeDecisionsClient:
    """Records each request and returns a Decision built from given answers."""

    def __init__(self, answers: list[dict]) -> None:
        self.requests: list[dict] = []
        self._answers = answers
        self.decisions = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Decision:
        self.requests.append(kwargs)
        return Decision.model_validate(
            {
                "model": kwargs["model"],
                "answers": self._answers,
                "usage": {
                    "input_tokens": 3774,
                    "input_tokens_details": {
                        "cached_tokens": 0,
                        "cache_write_tokens": 0,
                    },
                    "output_tokens": 0,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 3774,
                },
            }
        )


class Clock:
    """Returns 10.0, then 11.5: a request of 1.5 seconds."""

    def __init__(self) -> None:
        self._times = iter([10.0, 11.5])

    def __call__(self) -> float:
        return next(self._times)


def _advisor(
    answers: list[dict] | None = None,
) -> tuple[DecisionAdvisor, FakeDecisionsClient]:
    client = FakeDecisionsClient(_answers() if answers is None else answers)
    return DecisionAdvisor(client, "gpt-6-luna", clock=Clock()), client


def test_questions_two_per_finding_then_the_case() -> None:
    """Ask, for each finding, about a deliberate act and a stoppable amount."""
    questions = build_questions(_report())
    names = [question["name"] for question in questions]
    assert names == [
        "F1_deliberate",
        "F1_stoppable",
        "F2_deliberate",
        "F2_stoppable",
        "case_action",
    ]
    assert [question["type"] for question in questions[:4]] == ["predicate"] * 4
    for question in questions[:2]:
        assert "F1" in question["instructions"]
        assert "Payments diverted | to a clerk" in question["instructions"]
    assert "deliberate" in questions[0]["instructions"]
    assert "processing error" in questions[0]["instructions"]
    assert "not yet paid" in questions[1]["instructions"]
    action = questions[-1]
    assert action["type"] == "choice"
    assert [choice["value"] for choice in action["choices"]] == [
        value for value, _ in ACTIONS
    ]
    assert all(choice["description"] for choice in action["choices"])
    assert all("only on the report" in q["instructions"] for q in questions)


def test_request_sends_only_the_report_fields_as_json() -> None:
    """One request, the configured model, the report as input_json for the user."""
    advisor, client = _advisor()
    advisor.advise(_report())
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request["model"] == "gpt-6-luna"
    assert request["questions"] == build_questions(_report())
    (message,) = request["input"]
    assert message["role"] == "user"
    (part,) = message["content"]
    assert part["type"] == "input_json"
    assert set(part["data"]) == set(REPORT_FIELDS)
    assert "bundle_sha256" not in part["data"]


def test_answers_are_matched_by_name() -> None:
    """Map each answer to its finding by question name, not by position."""
    advisor, _ = _advisor()
    advice = advisor.advise(_report())
    assert advice.findings == (
        FindingAdvice(1, "Payments diverted | to a clerk", 0.86, 1.0),
        FindingAdvice(2, "Duplicate payment", 0.05, 0.0),
    )
    assert advice.action == "stop_payments_and_escalate"
    assert advice.action_confidence == 0.97
    assert advice.action_probabilities["no_action"] == 0.01
    assert advice.model == "gpt-6-luna"
    assert advice.elapsed_seconds == 1.5
    assert advice.input_tokens == 3774


def test_refusals_become_none() -> None:
    """A refused question gives None; the other answers are kept."""
    refused = _answers(
        F1_deliberate={"type": "refusal", "name": "F1_deliberate"},
        case_action={"type": "refusal", "name": "case_action"},
    )
    advisor, _ = _advisor(refused)
    advice = advisor.advise(_report())
    assert advice.findings[0].deliberate is None
    assert advice.findings[0].stoppable == 1.0
    assert advice.action is None and advice.action_confidence is None
    assert not advice.action_probabilities


def test_a_missing_answer_is_an_error() -> None:
    """Stop with DecisionError when a question has no answer."""
    advisor, _ = _advisor(_answers(F2_stoppable=None))
    with pytest.raises(DecisionError, match="F2_stoppable"):
        advisor.advise(_report())


def test_likelihood_uses_the_thresholds() -> None:
    """Read probabilities against thresholds that people set."""
    assert UNLIKELY < LIKELY
    assert likelihood(LIKELY) == "likely"
    assert likelihood(1.0) == "likely"
    assert likelihood(UNLIKELY) == "unlikely"
    assert likelihood(0.0) == "unlikely"
    assert likelihood((LIKELY + UNLIKELY) / 2) == "uncertain"
    assert likelihood(None) == "refused"


def test_load_report_rejects_what_is_not_a_report(tmp_path: Path) -> None:
    """Accept a saved report; reject invalid JSON and reports without findings."""
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_report()), encoding="utf-8")
    assert load_report(good)["summary"] == "Two findings."
    for name, text in (
        ("broken.json", "{not json"),
        ("list.json", "[]"),
        ("none.json", json.dumps({"summary": "x"})),
        ("empty.json", json.dumps({**_report(), "findings": []})),
    ):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        with pytest.raises(DecisionError):
            load_report(path)


def test_output_paths_follow_the_report() -> None:
    """Write x-decisions.md and .json next to x-report.json, or in a folder."""
    report = Path("out/case-report.json")
    assert output_paths(report, None) == (
        Path("out/case-decisions.md"),
        Path("out/case-decisions.json"),
    )
    assert output_paths(Path("other.json"), Path("elsewhere")) == (
        Path("elsewhere/other-decisions.md"),
        Path("elsewhere/other-decisions.json"),
    )


def test_markdown_shows_the_note_findings_and_action() -> None:
    """Render the note, the thresholds, one row per finding and the action."""
    advisor, _ = _advisor()
    markdown = render_markdown(advisor.advise(_report()), "case-report.json")
    assert markdown.startswith("# Decision Support")
    assert DECISION_NOTE in markdown
    assert "case-report.json" in markdown and "gpt-6-luna" in markdown
    assert f"likely >= {LIKELY}" in markdown
    assert (
        "| F1. Payments diverted \\| to a clerk | 0.86 likely | 1.00 likely |"
        in markdown
    )
    assert "| F2. Duplicate payment | 0.05 unlikely | 0.00 unlikely |" in markdown
    assert "**stop_payments_and_escalate** (confidence 0.97)" in markdown
    refused = CaseAdvice(
        findings=(FindingAdvice(1, "X", None, 0.5),),
        action=None,
        action_confidence=None,
    )
    text = render_markdown(refused, "r.json")
    assert "| F1. X | refused | 0.50 uncertain |" in text
    assert "refused to suggest an action" in text


def test_main_prints_and_writes_the_advice(tmp_path: Path) -> None:
    """Run the command line on a saved report, with a fake advisor."""
    report = tmp_path / "case-report.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    stream = io.StringIO()
    advisor, _ = _advisor()
    with patch.object(decisions.Settings, "load", return_value=base_settings()):
        status = decisions.main([str(report)], stream, lambda settings: advisor)
    assert status == 0
    text = stream.getvalue()
    for value in (
        "Decision support",
        "deliberate act 0.86 likely",
        "can still be stopped 0.00 unlikely",
        "Next action: stop_payments_and_escalate (confidence 0.97)",
        DECISION_NOTE,
        str(tmp_path / "case-decisions.md"),
    ):
        assert value in text
    saved = json.loads((tmp_path / "case-decisions.json").read_text(encoding="utf-8"))
    assert saved["findings"][0]["deliberate"] == 0.86
    assert saved["thresholds"] == {"likely": LIKELY, "unlikely": UNLIKELY}
    assert saved["note"] == DECISION_NOTE
    assert (tmp_path / "case-decisions.md").is_file()


def test_main_errors_print_one_line(tmp_path: Path) -> None:
    """Exit 1 with one ERROR line for a missing file or incomplete settings."""
    stream = io.StringIO()
    missing = str(tmp_path / "missing-report.json")
    with patch.object(decisions.Settings, "load", return_value=base_settings()):
        assert decisions.main([missing], stream, lambda s: _advisor()[0]) == 1
    assert stream.getvalue().count("ERROR:") == 1
    report = tmp_path / "case-report.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    stream = io.StringIO()
    no_key = replace(base_settings(), openai_api_key="")
    with patch.object(decisions.Settings, "load", return_value=no_key):
        assert decisions.main([str(report)], stream) == 1
    assert "ERROR: OPENAI_API_KEY (.env) is not set" in stream.getvalue()
    assert not (tmp_path / "case-decisions.md").exists()


def test_from_settings_uses_the_decisions_settings() -> None:
    """Build the client from [decisions], not from [model]."""
    settings = replace(
        base_settings(),
        model_provider=ModelProvider.OCI,
        decisions_provider=ModelProvider.OPENAI,
        decisions_model_id="gpt-6-luna",
    )
    with patch.object(decisions, "DecisionsClientFactory") as factory:
        factory.return_value.create.return_value = FakeDecisionsClient(_answers())
        advisor = DecisionAdvisor.from_settings(settings)
    factory.assert_called_once_with(settings)
    advice = advisor.advise(_report())
    assert advice.model == "gpt-6-luna"
