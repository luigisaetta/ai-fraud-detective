"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: A reference solution of the sample case, written the way the
    agent should work: Python standard library only (csv, sqlite3 in memory,
    decimal, re), runnable in the sandbox with Python 3.11.

    It proves that the findings can be reached with code. The tests run it
    on the generated bundle; tests/scenario/sandbox_check.py runs it in a
    real sandbox. It never imports the fraud_detective package, so it can be copied
    alone.

Usage:

    python3 reference_solver.py /workspace/bundle
"""

import csv
import json
import re
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

#: Tables loaded from the bundle: table name -> CSV file.
TABLES = {
    "suppliers": "ap/suppliers.csv",
    "accounts": "ap/supplier_bank_accounts.csv",
    "invoices": "ap/invoices.csv",
    "payments": "ap/payments.csv",
    "employees": "hr/employees.csv",
    "roles": "security/user_roles.csv",
}

#: Role pairs that the policy forbids for one user.
CONFLICTS = (
    ("Supplier Maintenance", "Invoice Entry"),
    ("Supplier Maintenance", "Invoice Approver"),
    ("Supplier Maintenance", "Payment Run"),
    ("Invoice Entry", "Invoice Approver"),
)

QUARTER_START = "2026-07-01"
THRESHOLD = 10000
BAND_LOW = 9000

_LOG_FIELD = re.compile(r'(\w+)=("[^"]*"|\S+)')


def normalize_iban(value: str) -> str:
    """An IBAN without spaces, in upper case."""
    return re.sub(r"\s+", "", value or "").upper()


def load(bundle: Path) -> sqlite3.Connection:
    """Load the CSV tables into an in-memory SQLite database."""
    conn = sqlite3.connect(":memory:")
    conn.create_function("norm", 1, normalize_iban)
    for table, path in TABLES.items():
        with open(bundle / path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            conn.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
            marks = ", ".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO {table} VALUES ({marks})",
                ([row[column] for column in columns] for row in reader),
            )
    return conn


def change_log(bundle: Path) -> list[dict[str, str]]:
    """Parse ap/supplier_changes.log into one dict per line."""
    changes = []
    text = (bundle / "ap/supplier_changes.log").read_text(encoding="utf-8")
    for line in text.splitlines():
        stamp, _, rest = line.partition(" ")
        fields = {key: value.strip('"') for key, value in _LOG_FIELD.findall(rest)}
        fields["timestamp"] = stamp
        changes.append(fields)
    return changes


def solve(bundle: Path) -> dict:  # pylint: disable=too-many-locals
    """Find the anomalies of the case.

    Args:
        bundle: The extracted bundle directory.

    Returns:
        The findings, as plain JSON-ready values.
    """
    conn = load(bundle)
    iban_matches = conn.execute(
        "SELECT a.supplier_id, a.bank_account_id, e.user_name, a.start_date "
        "FROM accounts a JOIN employees e ON norm(a.iban) = norm(e.payroll_iban)"
    ).fetchall()
    unverified = [
        change
        for change in change_log(bundle)
        if change["field"] == "bank_account_id" and not change["verification_ref"]
    ]
    self_approved = conn.execute(
        "SELECT invoice_num, supplier_id, entered_by FROM invoices "
        "WHERE approved_by <> '' AND entered_by = approved_by ORDER BY invoice_id"
    ).fetchall()
    split = conn.execute(
        "SELECT supplier_id, COUNT(*), GROUP_CONCAT(amount, '|') FROM invoices "
        "WHERE po_number = '' AND status <> 'CANCELLED' AND invoice_date >= ? "
        "AND CAST(amount AS REAL) >= ? AND CAST(amount AS REAL) < ? "
        "GROUP BY supplier_id HAVING COUNT(*) >= 3",
        (QUARTER_START, BAND_LOW, THRESHOLD),
    ).fetchall()
    roles: dict[str, set[str]] = {}
    for user, role in conn.execute("SELECT user_name, role FROM roles"):
        roles.setdefault(user, set()).add(role)
    conflicts = sorted(
        user
        for user, held in roles.items()
        if any(first in held and second in held for first, second in CONFLICTS)
    )
    duplicates = conn.execute(
        "SELECT a.supplier_id, a.invoice_num, b.invoice_num, a.amount "
        "FROM invoices a JOIN invoices b ON a.supplier_id = b.supplier_id "
        "AND a.amount = b.amount AND a.invoice_id < b.invoice_id "
        "AND (b.invoice_num LIKE a.invoice_num || '_' "
        "OR a.invoice_num LIKE b.invoice_num || '_') "
        "WHERE a.status = 'PAID' AND b.status = 'PAID'"
    ).fetchall()
    exposure = {}
    for supplier_id, account_id, _, _ in iban_matches:
        totals = {"PAID": Decimal("0"), "SCHEDULED": Decimal("0")}
        for amount, status in conn.execute(
            "SELECT amount, status FROM payments WHERE bank_account_id = ?",
            (account_id,),
        ):
            totals[status] += Decimal(amount)
        exposure[supplier_id] = {key: str(value) for key, value in totals.items()}
    return {
        "iban_matches": [list(row) for row in iban_matches],
        "unverified_bank_changes": [
            [c["supplier"], c["user"], c["approved_by"], c["timestamp"]]
            for c in unverified
        ],
        "self_approved": [list(row) for row in self_approved],
        "split_invoices": [
            [supplier, count, str(sum(Decimal(a) for a in amounts.split("|")))]
            for supplier, count, amounts in split
        ],
        "role_conflicts": conflicts,
        "duplicates": [list(row) for row in duplicates],
        "exposure": exposure,
    }


if __name__ == "__main__":
    print(json.dumps(solve(Path(sys.argv[1])), indent=2))
