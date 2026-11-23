"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: The records of the AP export (one dataclass per file), the
    IBAN helpers and the company calendar.
"""

import random
import string
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from triage.sample_case.facts import HOLIDAYS

#: Days of the week with a payment run: Wednesday and Friday.
RUN_WEEKDAYS = (2, 4)

#: Length of the BBAN part of an IBAN, and whether it starts with letters.
_BBAN_LAYOUT = {
    "IT": (23, 1),
    "DE": (18, 0),
    "AT": (16, 0),
    "CZ": (20, 0),
    "FR": (23, 0),
    "PL": (24, 0),
    "NL": (14, 4),
}


def money(value: Decimal) -> str:
    """An amount as the ERP exports it, for example ``9480.00``."""
    return f"{value:.2f}"


@dataclass(frozen=True)
class Employee:
    """A row of hr/employees.csv."""

    HEADER = (
        "employee_id,full_name,user_name,department,job_title,hire_date,payroll_iban"
    )

    employee_id: str
    full_name: str
    user_name: str
    department: str
    job_title: str
    hire_date: date
    payroll_iban: str

    def row(self) -> list[str]:
        """The CSV fields; the IBAN is printed in groups of four, as HR keeps it."""
        return [
            self.employee_id,
            self.full_name,
            self.user_name,
            self.department,
            self.job_title,
            self.hire_date.isoformat(),
            spaced_iban(self.payroll_iban),
        ]


@dataclass(frozen=True)
class RoleGrant:
    """A row of security/user_roles.csv."""

    HEADER = "user_name,role,granted_date,granted_by,ticket,note"

    user_name: str
    role: str
    granted_date: date
    granted_by: str
    ticket: str
    note: str = ""

    def row(self) -> list[str]:
        """The CSV fields."""
        return [
            self.user_name,
            self.role,
            self.granted_date.isoformat(),
            self.granted_by,
            self.ticket,
            self.note,
        ]


@dataclass
class Supplier:  # pylint: disable=too-many-instance-attributes
    """A row of ap/suppliers.csv, plus the profile used to generate invoices.

    The profile fields (category, typical amount, weight, PO rate) are not
    exported.
    """

    HEADER = (
        "supplier_id,supplier_name,site_code,tax_id,country,status,creation_date,"
        "created_by,payment_terms,bank_account_id,contact_email,phone"
    )

    supplier_id: str
    supplier_name: str
    site_code: str
    tax_id: str
    country: str
    status: str
    creation_date: date
    created_by: str
    payment_terms: int
    bank_account_id: str
    contact_email: str
    phone: str
    category: str = ""
    typical_amount: Decimal = Decimal("1000.00")
    weight: float = 1.0
    po_rate: float = 0.9

    def row(self) -> list[str]:
        """The CSV fields."""
        return [
            self.supplier_id,
            self.supplier_name,
            self.site_code,
            self.tax_id,
            self.country,
            self.status,
            self.creation_date.isoformat(),
            self.created_by,
            f"NET{self.payment_terms}",
            self.bank_account_id,
            self.contact_email,
            self.phone,
        ]


@dataclass
class BankAccount:
    """A row of ap/supplier_bank_accounts.csv."""

    HEADER = "bank_account_id,supplier_id,iban,bank_name,start_date,end_date"

    bank_account_id: str
    supplier_id: str
    iban: str
    bank_name: str
    start_date: date
    end_date: date | None = None

    def row(self) -> list[str]:
        """The CSV fields; the IBAN is compact, as the ERP stores it."""
        return [
            self.bank_account_id,
            self.supplier_id,
            self.iban,
            self.bank_name,
            self.start_date.isoformat(),
            self.end_date.isoformat() if self.end_date else "",
        ]


@dataclass(frozen=True)
class Change:  # pylint: disable=too-many-instance-attributes
    """A line of ap/supplier_changes.log."""

    timestamp: datetime
    user: str
    supplier_id: str
    field_name: str
    old: str
    new: str
    reason: str
    verification_ref: str
    approved_by: str

    def line(self) -> str:
        """The log line, in key=value form."""
        return (
            f"{self.timestamp:%Y-%m-%dT%H:%M:%S} user={self.user} "
            f"supplier={self.supplier_id} field={self.field_name} "
            f'old="{self.old}" new="{self.new}" reason="{self.reason}" '
            f'verification_ref="{self.verification_ref}" '
            f"approved_by={self.approved_by}"
        )


@dataclass
class Invoice:  # pylint: disable=too-many-instance-attributes
    """A row of ap/invoices.csv."""

    HEADER = (
        "invoice_id,invoice_num,supplier_id,invoice_date,gl_date,amount,currency,"
        "po_number,description,entered_by,approved_by,approval_date,status"
    )

    invoice_num: str
    supplier_id: str
    invoice_date: date
    gl_date: date
    amount: Decimal
    po_number: str
    description: str
    entered_by: str
    approved_by: str = ""
    approval_date: date | None = None
    status: str = "PENDING_APPROVAL"
    invoice_id: str = ""
    currency: str = "EUR"
    extra: dict[str, str] = field(default_factory=dict)

    def row(self) -> list[str]:
        """The CSV fields."""
        return [
            self.invoice_id,
            self.invoice_num,
            self.supplier_id,
            self.invoice_date.isoformat(),
            self.gl_date.isoformat(),
            money(self.amount),
            self.currency,
            self.po_number,
            self.description,
            self.entered_by,
            self.approved_by,
            self.approval_date.isoformat() if self.approval_date else "",
            self.status,
        ]


@dataclass
class Payment:  # pylint: disable=too-many-instance-attributes
    """A row of ap/payments.csv."""

    HEADER = (
        "payment_id,invoice_id,supplier_id,payment_date,amount,bank_account_id,"
        "payment_method,payment_batch,status"
    )

    invoice_id: str
    supplier_id: str
    payment_date: date
    amount: Decimal
    bank_account_id: str
    status: str
    payment_id: str = ""
    payment_method: str = "SEPA_CT"

    def row(self) -> list[str]:
        """The CSV fields."""
        return [
            self.payment_id,
            self.invoice_id,
            self.supplier_id,
            self.payment_date.isoformat(),
            money(self.amount),
            self.bank_account_id,
            self.payment_method,
            f"PR-{self.payment_date.isoformat()}",
            self.status,
        ]


# ---------------------------------------------------------------- IBANs


def _iban_check(country: str, bban: str) -> int:
    """The correct ISO 13616 check digits of an IBAN."""
    digits = "".join(str(int(char, 36)) for char in bban + country + "00")
    return 98 - int(digits) % 97


def is_valid_iban(iban: str) -> bool:
    """Whether the check digits of an IBAN are correct."""
    compact = iban.replace(" ", "").upper()
    moved = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in moved)) % 97 == 1


def fake_iban(country: str, rnd: random.Random) -> str:
    """A random IBAN with a realistic layout and wrong check digits.

    The wrong check digits guarantee that it cannot be a real account.

    Args:
        country: Two-letter country code, one of the supported layouts.
        rnd: The random generator.

    Returns:
        The IBAN in compact form.
    """
    length, letters = _BBAN_LAYOUT[country]
    head = "".join(rnd.choice(string.ascii_uppercase) for _ in range(letters))
    bban = head + "".join(rnd.choice(string.digits) for _ in range(length - letters))
    valid = _iban_check(country, bban)
    wrong = (valid + rnd.randint(1, 90)) % 97
    wrong = wrong if wrong >= 2 else wrong + 2
    if wrong == valid:
        wrong = 2 if valid != 2 else 3
    return f"{country}{wrong:02d}{bban}"


def spaced_iban(iban: str) -> str:
    """An IBAN in groups of four characters, as printed on paper."""
    return " ".join(iban[index : index + 4] for index in range(0, len(iban), 4))


# ------------------------------------------------------------- calendar


def is_working_day(day: date) -> bool:
    """Monday to Friday, except public holidays."""
    return day.weekday() < 5 and day not in HOLIDAYS


def working_days(start: date, end: date) -> list[date]:
    """The working days from ``start`` to ``end``, both included."""
    days = []
    day = start
    while day <= end:
        if is_working_day(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def add_working_days(start: date, count: int) -> date:
    """The working day ``count`` working days after ``start``."""
    day = start
    while count > 0:
        day += timedelta(days=1)
        if is_working_day(day):
            count -= 1
    return day


def next_payment_run(earliest: date) -> date:
    """The first payment run (Wednesday or Friday) on or after ``earliest``."""
    day = earliest
    while not (day.weekday() in RUN_WEEKDAYS and is_working_day(day)):
        day += timedelta(days=1)
    return day
