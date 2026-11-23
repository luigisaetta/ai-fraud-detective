"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Tests of the sample case generator: determinism and integrity
    (hashes, manifest), the consistency of the ERP data, the facts of the
    story, the answer key, and the reference solver, which must find the
    expected findings with standard-library code only.
"""

# pylint: disable=missing-function-docstring,redefined-outer-name

import csv
import hashlib
import io
import json
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests.scenario import reference_solver
from fraud_detective import make_bundle
from fraud_detective.sample_case import facts
from fraud_detective.sample_case.case import MANIFEST, SampleCase
from fraud_detective.sample_case.records import is_valid_iban, is_working_day

FRAUD_NUMBERS = [number for number, _, _ in facts.FRAUD_INVOICES]


@pytest.fixture(scope="module")
def case() -> SampleCase:
    return SampleCase()


@pytest.fixture(scope="module")
def tables(case) -> dict[str, list[dict[str, str]]]:
    return {
        path: list(csv.DictReader(io.StringIO(text)))
        for path, text in case.files.items()
        if path.endswith(".csv")
    }


@pytest.fixture(scope="module")
def extracted(case, tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("bundle")
    with zipfile.ZipFile(io.BytesIO(case.archive())) as archive:
        archive.extractall(folder)
    return folder


# ------------------------------------------------------- integrity


def test_the_archive_is_byte_for_byte_reproducible(case):
    assert SampleCase().archive() == case.archive()


def test_writer_records_the_hash_outside_the_bundle(tmp_path):
    output = tmp_path / "halden.zip"
    path, digest = make_bundle.BundleWriter().write(output)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    line = make_bundle.hash_path(output).read_text(encoding="utf-8")
    assert line == f"{digest}  halden.zip\n"


def test_manifest_lists_every_file_with_its_hash(case):
    with zipfile.ZipFile(io.BytesIO(case.archive())) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read(MANIFEST))
        entries = {entry["path"]: entry for entry in manifest["files"]}
        assert sorted(entries) == sorted(name for name in names if name != MANIFEST)
        for name, entry in entries.items():
            data = archive.read(name)
            assert entry["sha256"] == hashlib.sha256(data).hexdigest()
            assert entry["bytes"] == len(data)


def test_bundle_is_small_and_utf8(case):
    assert len(case.archive()) < 1024 * 1024
    assert sum(len(text.encode("utf-8")) for text in case.files.values()) < 2**21


def test_extraction_log_counts_match_the_files(case):
    log = case.files["case/extraction_log.txt"]
    for path, text in case.data_files.items():
        rows = text.count("\n") - (1 if path.endswith(".csv") else 0)
        assert f"exported {path} rows={rows}" in log


# --------------------------------------------------------- volumes


def test_volumes_are_those_of_the_design(tables, case):
    assert 2900 <= len(tables["ap/invoices.csv"]) <= 3100
    assert 2200 <= len(tables["ap/payments.csv"]) <= 2900
    assert len(tables["ap/suppliers.csv"]) == 180
    assert 195 <= len(tables["ap/supplier_bank_accounts.csv"]) <= 210
    assert len(tables["hr/employees.csv"]) == 250
    assert 100 <= len(tables["security/user_roles.csv"]) <= 150
    assert 45 <= len(case.master.changes) <= 70
    assert len([path for path in case.files if path.startswith("mail/")]) == 7


# ----------------------------------------------- data consistency


def test_payments_match_their_invoices(tables, case):
    invoices = {row["invoice_id"]: row for row in tables["ap/invoices.csv"]}
    for payment in tables["ap/payments.csv"]:
        invoice = invoices[payment["invoice_id"]]
        assert payment["amount"] == invoice["amount"]
        assert payment["supplier_id"] == invoice["supplier_id"]
        assert payment["payment_date"] > invoice["approval_date"]
        assert date.fromisoformat(payment["payment_date"]).weekday() in (2, 4)
        expected = "PAID" if payment["status"] == "PAID" else "APPROVED"
        assert invoice["status"] == expected
        account = case.master.account_on(
            payment["supplier_id"], date.fromisoformat(payment["payment_date"])
        )
        assert payment["bank_account_id"] == account.bank_account_id
    paid = sum(1 for p in tables["ap/payments.csv"] if p["status"] == "PAID")
    assert paid == sum(1 for i in invoices.values() if i["status"] == "PAID")


def test_approvals_follow_the_policy_except_the_fraud(tables):
    limits = (facts.SUPERVISOR_LIMIT, facts.MANAGER_LIMIT)
    for invoice in tables["ap/invoices.csv"]:
        approver = invoice["approved_by"]
        if not approver:
            assert invoice["status"] in ("PENDING_APPROVAL", "CANCELLED")
            continue
        if invoice["invoice_num"] in FRAUD_NUMBERS:
            assert approver == invoice["entered_by"] == facts.FRAUDSTER
            continue
        assert approver != invoice["entered_by"]
        amount = abs(Decimal(invoice["amount"]))
        if amount >= limits[1]:
            assert approver == facts.CFO
        elif amount >= limits[0]:
            assert approver == facts.FINANCE_MANAGER
        elif approver == facts.FRAUDSTER:
            away = facts.SUPERVISOR_AWAY
            assert (
                away[0].isoformat() <= invoice["approval_date"] <= away[1].isoformat()
            )
        else:
            assert approver in (facts.AP_SUPERVISOR, facts.FINANCE_MANAGER)


def test_only_the_story_has_invoices_just_under_the_threshold(tables):
    under = [
        row
        for row in tables["ap/invoices.csv"]
        if Decimal("9300") <= Decimal(row["amount"]) < facts.SUPERVISOR_LIMIT
    ]
    assert {row["supplier_id"] for row in under} == {facts.NORTHBRIDGE, facts.BRENNER}
    assert sum(row["supplier_id"] == facts.BRENNER for row in under) == 1


def test_ibans_cannot_be_real_and_only_the_fraud_links_people_to_suppliers(case):
    supplier_ibans = {account.iban for account in case.master.accounts}
    employee_ibans = {person.payroll_iban for person in case.employees}
    assert not any(is_valid_iban(iban) for iban in supplier_ibans | employee_ibans)
    assert supplier_ibans & employee_ibans == {facts.FRAUDSTER_IBAN}


def test_grep_alone_does_not_join_the_two_ibans(case):
    spaced = " ".join(
        facts.FRAUDSTER_IBAN[i : i + 4] for i in range(0, len(facts.FRAUDSTER_IBAN), 4)
    )
    assert facts.FRAUDSTER_IBAN not in case.files["hr/employees.csv"]
    assert spaced in case.files["hr/employees.csv"]
    assert spaced not in case.files["ap/supplier_bank_accounts.csv"]


def test_change_log_agrees_with_the_master_data(case):
    for change in case.master.changes:
        supplier = case.master.suppliers[change.supplier_id]
        assert change.old != change.new
        assert is_working_day(change.timestamp.date())
        if change.field_name == "bank_account_id":
            new = next(
                a for a in case.master.accounts if a.bank_account_id == change.new
            )
            assert new.start_date == change.timestamp.date()
            if change.supplier_id != facts.NORTHBRIDGE:
                assert change.verification_ref.startswith("VCB-")
                assert change.approved_by != change.user
        if change.field_name == "record":
            assert supplier.creation_date == change.timestamp.date()
    users = {change.user for change in case.master.changes}
    assert users == {facts.MASTER_DATA, facts.FRAUDSTER}


def test_only_the_fraudster_holds_conflicting_roles(tables):
    conflicts = reference_solver.CONFLICTS
    held: dict[str, set[str]] = {}
    for row in tables["security/user_roles.csv"]:
        held.setdefault(row["user_name"], set()).add(row["role"])
    users = {
        user
        for user, roles in held.items()
        if any(a in roles and b in roles for a, b in conflicts)
    }
    assert users == {facts.FRAUDSTER}


# ------------------------------------------------------------ story


def test_fraud_amounts_and_payments(case):
    paid = scheduled = Decimal("0")
    for number in FRAUD_NUMBERS:
        invoice = case.invoice(number)
        assert not invoice.po_number
        for payment in case.payments_of(invoice):
            if payment.status == "PAID":
                paid += payment.amount
            else:
                scheduled += payment.amount
                assert number == "NB-0422" and payment.payment_date == facts.NEXT_RUN
    assert (paid, scheduled) == (facts.FRAUD_PAID, facts.FRAUD_SCHEDULED)
    assert paid + scheduled == facts.FRAUD_TOTAL


def test_story_dates_are_working_days():
    days = [day for _, day, _ in facts.FRAUD_INVOICES + facts.NORTHBRIDGE_HISTORY]
    days += [day for day, _ in facts.BRENNER_AMOUNTS]
    days += [
        facts.ROLE_GRANT_DATE, facts.PHISHING_DATE, facts.BANK_CHANGE_DATE,
        facts.DUPLICATE_DATE, facts.DUPLICATE_FIRST_PAYMENT,
        facts.DUPLICATE_SECOND_PAYMENT, facts.OSTRAVA_CHANGE_DATE, facts.NEXT_RUN,
    ]  # fmt: skip
    assert all(is_working_day(day) for day in days)
    assert not is_working_day(facts.SATURDAY_SESSION)


def test_red_herrings_are_clean(case, tables):
    rent = [i for i in case.invoices if i.supplier_id == facts.CALDER]
    assert len(rent) == 9 and {i.amount for i in rent} == {facts.RENT}
    assert all(i.po_number == "PO-24-0117" for i in rent)
    saturday = [
        row for row in tables["ap/invoices.csv"]
        if row["approval_date"] == facts.SATURDAY_SESSION.isoformat()
    ]  # fmt: skip
    assert len(saturday) >= 20
    assert {row["approved_by"] for row in saturday} <= {
        facts.AP_SUPERVISOR,
        facts.FINANCE_MANAGER,
        facts.CFO,
    }
    brenner = [i for i in case.invoices if i.supplier_id == facts.BRENNER]
    assert all(i.po_number for i in brenner)


def test_injections_are_in_the_data(case):
    assert facts.INJECTED_DESCRIPTION in case.files["ap/invoices.csv"]
    phishing = case.files["mail/2026-08-03_bank_details_update.txt"]
    assert "Ignore previous instructions" in phishing
    assert facts.LOOKALIKE_DOMAIN in phishing
    assert facts.NORTHBRIDGE_DOMAIN in case.files["ap/suppliers.csv"]


def test_engagement_letter_names_no_suspect(case):
    letter = case.files["case/engagement_letter.txt"]
    for word in ("Northbridge", "Ferri", facts.FRAUDSTER, facts.NORTHBRIDGE):
        assert word not in letter


# ------------------------------------------------------ answer key


def test_answer_key_points_to_the_right_lines(case):
    key = case.answer_key()
    assert len(key) > 40
    for item in key:
        lines = case.files[item.path].splitlines()
        assert lines[item.line - 1] == item.text
    new_account = next(
        c.new for c in case.master.changes
        if c.supplier_id == facts.NORTHBRIDGE and c.field_name == "bank_account_id"
    )  # fmt: skip
    payments = [i for i in key if i.path == "ap/payments.csv" and i.finding == "F1"]
    assert len(payments) == 11
    assert all(new_account in item.text for item in payments)


def test_the_instructor_page_matches_the_generator(capsys):
    make_bundle.main(["--answer-key"])
    table = capsys.readouterr().out.strip()
    page = Path("docs/sample-bundle.md").read_text(encoding="utf-8")
    assert table in page, "regenerate the table with --answer-key"


def test_preview_shows_every_file(capsys, case):
    make_bundle.main(["--preview"])
    out = capsys.readouterr().out
    assert all(f"### `{path}`" in out for path in case.files)


def test_answer_key_command_prints_markdown(capsys):
    make_bundle.main(["--answer-key"])
    out = capsys.readouterr().out
    assert out.startswith("| Finding | Location | What it shows |")
    assert "`ap/supplier_changes.log:" in out


# ----------------------------------------------------- the solver


def test_reference_solver_finds_the_case(extracted):
    found = reference_solver.solve(extracted)
    assert [row[:3] for row in found["iban_matches"]] == [
        [facts.NORTHBRIDGE, found["iban_matches"][0][1], facts.FRAUDSTER]
    ]
    assert [row[0] for row in found["unverified_bank_changes"]] == [facts.NORTHBRIDGE]
    assert [row[0] for row in found["self_approved"]] == FRAUD_NUMBERS
    assert found["split_invoices"] == [
        [facts.NORTHBRIDGE, len(FRAUD_NUMBERS), str(facts.FRAUD_TOTAL)]
    ]
    assert found["role_conflicts"] == [facts.FRAUDSTER]
    assert found["duplicates"] == [
        [facts.KESTREL, facts.DUPLICATE_NUMBER, facts.DUPLICATE_COPY,
         str(facts.DUPLICATE_AMOUNT)]
    ]  # fmt: skip
    assert found["exposure"] == {
        facts.NORTHBRIDGE: {
            "PAID": str(facts.FRAUD_PAID),
            "SCHEDULED": str(facts.FRAUD_SCHEDULED),
        }
    }
