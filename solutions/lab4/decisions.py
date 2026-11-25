"""
Author: L. Saetta
Date Last Modified: 2026-11-25
License: MIT
Description: Lab 4 (optional): decision support on the forensic report. The
    OpenAI Decisions API answers bounded questions about the saved report:
    for each finding, the probability of a deliberate act and of an amount
    that can still be stopped; for the case, the next action. It returns
    typed answers with probabilities, in seconds, and no explanation.

Usage:

    python -m fraud_detective.decisions out/halden-ap-q3-2026-report.json
"""

import argparse
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import sys
from time import monotonic
from typing import Any, Callable, TextIO

from openai import APIError, OpenAI

from fraud_detective.config import Settings
from fraud_detective.llm import DecisionsClientFactory

#: The fields of the saved report sent to the Decisions API.
REPORT_FIELDS = (
    "summary",
    "overall_risk",
    "total_exposure_eur",
    "findings",
    "cleared_items",
)

#: Probabilities at or above this read "likely". Set by people, not by the model.
LIKELY = 0.7

#: Probabilities at or below this read "unlikely". Set by people, not by the model.
UNLIKELY = 0.3

#: The next actions offered for the case: (value, description).
ACTIONS = (
    (
        "stop_payments_and_escalate",
        "Hold the payments that can still be stopped, and escalate to legal and HR now.",
    ),
    ("investigate_further", "Gather more evidence before any action."),
    (
        "correct_and_recover",
        "Treat it as a processing error: correct it and recover the money, "
        "without escalation.",
    ),
    ("no_action", "Nothing in the report requires action."),
)

#: The fixed note of every output.
DECISION_NOTE = (
    "Indicators from the OpenAI Decisions API, computed from the report only. "
    "The thresholds are set by people, and the decision stays with the "
    "investigators."
)


class DecisionError(Exception):
    """The report cannot be used, or the answers do not match the questions."""


def _finding_ref(number: int, finding: dict) -> str:
    """How a question names a finding: its number and title."""
    return f'finding F{number} ("{finding.get("title", "")}")'


def build_questions(report: dict) -> list[dict]:
    """The questions for a report: two per finding, then one for the case.

    Args:
        report: The saved report, with its findings.

    Returns:
        Questions for ``client.decisions.create``, each with a unique name.
    """
    questions: list[dict] = []
    for number, finding in enumerate(report["findings"], start=1):
        ref = _finding_ref(number, finding)
        questions.append(
            {
                "type": "predicate",
                "name": f"F{number}_deliberate",
                "instructions": (
                    f"Based only on the report, does the evidence of {ref} "
                    "indicate a deliberate act rather than a processing error?"
                ),
            }
        )
        questions.append(
            {
                "type": "predicate",
                "name": f"F{number}_stoppable",
                "instructions": (
                    f"Based only on the report, is part of the amount at risk of "
                    f"{ref} not yet paid, so that it can still be stopped before it "
                    "leaves the company?"
                ),
            }
        )
    questions.append(
        {
            "type": "choice",
            "name": "case_action",
            "choices": [
                {"value": value, "description": description}
                for value, description in ACTIONS
            ],
            "instructions": (
                "Based only on the report, which next action should the "
                "investigators take on the case as a whole?"
            ),
        }
    )
    return questions


@dataclass(frozen=True)
class FindingAdvice:
    """The answers about one finding; None where the model refused.

    Attributes:
        number: The finding number, from 1.
        title: The finding title.
        deliberate: Probability of a deliberate act rather than an error.
        stoppable: Probability that part of the amount can still be stopped.
    """

    number: int
    title: str
    deliberate: float | None
    stoppable: float | None


@dataclass(frozen=True)
class CaseAdvice:  # pylint: disable=too-many-instance-attributes
    """The answers about a report.

    Attributes:
        findings: One entry per finding, in report order.
        action: The suggested next action, or None if the model refused.
        action_confidence: The confidence of the suggested action.
        action_probabilities: The probability of each action.
        model: The Decisions API model.
        elapsed_seconds: Duration of the request.
        input_tokens: Input tokens of the request.
    """

    findings: tuple[FindingAdvice, ...]
    action: str | None
    action_confidence: float | None
    action_probabilities: dict[str, float] = field(default_factory=dict)
    model: str = ""
    elapsed_seconds: float = 0.0
    input_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        """The advice as JSON-ready values, with the thresholds and the note."""
        return {
            **asdict(self),
            "thresholds": {"likely": LIKELY, "unlikely": UNLIKELY},
            "note": DECISION_NOTE,
        }


def likelihood(probability: float | None) -> str:
    """Read a probability against the thresholds set by people.

    Args:
        probability: A probability, or None for a refused question.

    Returns:
        ``likely``, ``unlikely``, ``uncertain`` or ``refused``.
    """
    if probability is None:
        return "refused"
    if probability >= LIKELY:
        return "likely"
    if probability <= UNLIKELY:
        return "unlikely"
    return "uncertain"


class DecisionAdvisor:
    """Asks the Decisions API the questions about a saved report.

    Args:
        client: An OpenAI client for the Decisions API.
        model_id: The Decisions API model.
        clock: Returns seconds; used to time the request.
    """

    def __init__(
        self,
        client: OpenAI,
        model_id: str,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._client = client
        self._model_id = model_id
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Settings) -> "DecisionAdvisor":
        """Build the advisor from ``[decisions]`` in the settings.

        Raises:
            ValueError: The Decisions settings are incomplete.
        """
        problems = settings.validate_decisions()
        if problems:
            raise ValueError("; ".join(problems))
        client = DecisionsClientFactory(settings).create()
        return cls(client, settings.decisions_model_id)

    def advise(self, report: dict) -> CaseAdvice:
        """Ask all the questions about a report in one request.

        Args:
            report: The saved report.

        Returns:
            The answers, by finding and for the case.

        Raises:
            DecisionError: An answer is missing for a question.
        """
        data = {key: report[key] for key in REPORT_FIELDS if key in report}
        start = self._clock()
        decision = self._client.decisions.create(
            model=self._model_id,
            input=[{"role": "user", "content": [{"type": "input_json", "data": data}]}],
            questions=build_questions(report),
        )
        elapsed = self._clock() - start
        answers = {answer.name: answer for answer in decision.answers}
        findings = tuple(
            FindingAdvice(
                number=number,
                title=str(finding.get("title", "")),
                deliberate=_probability(answers, f"F{number}_deliberate"),
                stoppable=_probability(answers, f"F{number}_stoppable"),
            )
            for number, finding in enumerate(report["findings"], start=1)
        )
        action = _answer(answers, "case_action")
        chosen = action.type == "choice"
        usage = getattr(decision, "usage", None)
        return CaseAdvice(
            findings=findings,
            action=str(action.choice) if chosen else None,
            action_confidence=action.confidence if chosen else None,
            action_probabilities=(
                {str(item.value): item.probability for item in action.probabilities}
                if chosen
                else {}
            ),
            model=str(getattr(decision, "model", "") or self._model_id),
            elapsed_seconds=round(elapsed, 2),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
        )


def _answer(answers: dict[str, Any], name: str) -> Any:
    """The answer to a named question."""
    if name not in answers:
        raise DecisionError(f"the Decisions API returned no answer for {name}")
    return answers[name]


def _probability(answers: dict[str, Any], name: str) -> float | None:
    """The probability of a predicate, or None if the model refused it."""
    answer = _answer(answers, name)
    return answer.probability if answer.type == "predicate" else None


def load_report(path: Path) -> dict:
    """Read a report saved by the CLI of Lab 3.

    Raises:
        DecisionError: The file is not a report with findings.
    """
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DecisionError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        raise DecisionError(f"{path} is not a report: it has no list of findings")
    if not report["findings"]:
        raise DecisionError(f"{path} has no findings to decide on")
    return report


def _percent(probability: float | None) -> str:
    """A probability with its reading, for example ``0.86 likely``."""
    if probability is None:
        return "refused"
    return f"{probability:.2f} {likelihood(probability)}"


def render_markdown(advice: CaseAdvice, report_name: str) -> str:
    """The advice as a Markdown document.

    Args:
        advice: The answers.
        report_name: The file name of the report they are about.

    Returns:
        Markdown with the note, the metadata, one row per finding and the action.
    """
    lines = ["# Decision Support", "", f"> {DECISION_NOTE}", ""]
    lines += ["| Metadata | Value |", "| --- | --- |"]
    lines += [
        f"| Report | {report_name} |",
        f"| Model | {advice.model} |",
        f"| Duration | {advice.elapsed_seconds:.2f} s |",
        f"| Input tokens | {advice.input_tokens} |",
        f"| Thresholds | likely >= {LIKELY}, unlikely <= {UNLIKELY} |",
    ]
    lines += ["", "## Findings", ""]
    lines += [
        "| Finding | Deliberate act | Can still be stopped |",
        "| --- | --- | --- |",
    ]
    for item in advice.findings:
        title = item.title.replace("|", "\\|")
        lines.append(
            f"| F{item.number}. {title} | {_percent(item.deliberate)} "
            f"| {_percent(item.stoppable)} |"
        )
    lines += ["", "## Next action", ""]
    if advice.action is None:
        lines.append("The model refused to suggest an action.")
    else:
        lines.append(f"**{advice.action}** (confidence {advice.action_confidence:.2f})")
        lines += ["", "| Action | Probability |", "| --- | --- |"]
        lines += [
            f"| {value} | {probability:.2f} |"
            for value, probability in advice.action_probabilities.items()
        ]
    return "\n".join(lines) + "\n"


def output_paths(report_path: Path, output_dir: Path | None) -> tuple[Path, Path]:
    """Where to write the advice: next to the report unless a folder is given.

    ``x-report.json`` gives ``x-decisions.md`` and ``x-decisions.json``.
    """
    stem = report_path.stem.removesuffix("-report")
    folder = output_dir if output_dir is not None else report_path.parent
    return folder / f"{stem}-decisions.md", folder / f"{stem}-decisions.json"


def print_advice(advice: CaseAdvice, stream: TextIO) -> None:
    """Print the answers, one line per finding, then the action and the note."""
    stream.write(
        f"Model   {advice.model} · {advice.elapsed_seconds:.2f} s · "
        f"{advice.input_tokens} input tokens\n\n"
    )
    for item in advice.findings:
        stream.write(
            f"F{item.number} {item.title}\n"
            f"   deliberate act {_percent(item.deliberate)} · "
            f"can still be stopped {_percent(item.stoppable)}\n"
        )
    if advice.action is None:
        stream.write("\nNext action: refused\n")
    else:
        stream.write(
            f"\nNext action: {advice.action} "
            f"(confidence {advice.action_confidence:.2f})\n"
        )
    stream.write(f"\n{DECISION_NOTE}\n")


def _parser() -> argparse.ArgumentParser:
    """The command line options."""
    parser = argparse.ArgumentParser(
        prog="python -m fraud_detective.decisions",
        description="Decision support on a forensic report (Lab 4).",
    )
    parser.add_argument("report", type=Path, help="report JSON saved by the CLI")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="folder for the output (default: the folder of the report)",
    )
    return parser


def main(
    argv: list[str] | None = None,
    stream: TextIO = sys.stdout,
    advisor_factory: Callable[[Settings], DecisionAdvisor] = (
        DecisionAdvisor.from_settings
    ),
) -> int:
    """Run the decision support on a saved report.

    Args:
        argv: The command line arguments; the real ones when None.
        stream: Where to print.
        advisor_factory: Builds the advisor from the settings (tests replace it).

    Returns:
        0 on success, 1 on an error, which is printed on one line.
    """
    arguments = _parser().parse_args(argv)
    stream.write("AI FRAUD DETECTIVE · Decision support\n")
    stream.write(f"Report  {arguments.report}\n")
    try:
        report = load_report(arguments.report)
        advice = advisor_factory(Settings.load()).advise(report)
        markdown_path, json_path = output_paths(arguments.report, arguments.output_dir)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_markdown(advice, arguments.report.name), encoding="utf-8"
        )
        json_path.write_text(
            json.dumps(advice.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (DecisionError, APIError, OSError, ValueError) as error:
        stream.write(f"ERROR: {error}\n")
        return 1
    print_advice(advice, stream)
    stream.write(f"\nMarkdown  {markdown_path}\nJSON      {json_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
