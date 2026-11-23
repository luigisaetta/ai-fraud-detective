"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Generates the AP ledger: ap/invoices.csv and ap/payments.csv,
    from January to September 2026.

    Background invoices follow each supplier's profile and the approval
    policy. The invoices of the story (the fraud, the duplicate, the red
    herrings) are added with fixed dates and amounts.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from fraud_detective.sample_case import facts
from fraud_detective.sample_case.records import (
    Invoice,
    Payment,
    add_working_days,
    next_payment_run,
    working_days,
)
from fraud_detective.sample_case.suppliers import MasterData

#: Invoices generated for the background suppliers, before the export cut.
BACKGROUND_INVOICES = 3010

#: Background amounts in this band are drawn again, so that only the story
#: has invoices just under the approval threshold.
_QUIET_BAND = (Decimal("9300.00"), Decimal("10000.00"))

#: Share of invoices cancelled, credit notes, and late payments.
CANCEL_RATE = 0.012
CREDIT_RATE = 0.014
LATE_RATE = 0.05

#: Largest profile weight, so that no supplier dominates the ledger.
MAX_WEIGHT = 14.0

#: Invoices entered on these days and still open are approved on Saturday.
SATURDAY_BACKLOG = (date(2026, 9, 21), date(2026, 9, 25))
SATURDAY_APPROVALS = 34

_KESTREL_FIRST_PAYMENT_APPROVER = facts.FINANCE_MANAGER


class LedgerBuilder:
    """Builds invoices and payments.

    Args:
        rnd: The random generator.
        master: The supplier master data.
    """

    def __init__(self, rnd: random.Random, master: MasterData) -> None:
        self._rnd = rnd
        self._master = master
        self._days = working_days(facts.EXPORT_START, facts.EXPORT_END)
        self._po_numbers: set[str] = set()

    def build(self) -> tuple[list[Invoice], list[Payment]]:
        """Build the ledger.

        Returns:
            Invoices ordered by invoice id, payments ordered by payment id.
        """
        invoices = self._background()
        invoices += self._calder() + self._brenner() + self._ostrava()
        invoices += self._kestrel() + self._northbridge()
        invoices = [inv for inv in invoices if inv.gl_date <= facts.EXPORT_END]
        self._saturday_session(invoices)
        invoices.sort(key=lambda inv: (inv.gl_date, inv.supplier_id, inv.invoice_num))
        for index, invoice in enumerate(invoices):
            invoice.invoice_id = f"INV-26-{index + 1:05d}"
        payments = self._payments(invoices)
        return invoices, payments

    # ---------------------------------------------------------- background

    def _background(self) -> list[Invoice]:
        """Invoices of the random suppliers, by profile."""
        suppliers = [
            supplier
            for supplier in self._master.suppliers.values()
            if supplier.weight > 0 and supplier.supplier_id not in facts.FIXED_SUPPLIERS
        ]
        weights = {
            s.supplier_id: min(s.weight, MAX_WEIGHT * self._rnd.uniform(0.5, 1.0))
            for s in suppliers
        }
        total = sum(weights.values())
        invoices = []
        for supplier in suppliers:
            share = weights[supplier.supplier_id] / total
            count = max(1, round(BACKGROUND_INVOICES * share))
            days = [d for d in self._days if d >= supplier.creation_date]
            if not days:
                continue
            numbers = self._numbering(supplier.supplier_name)
            amounts: set[Decimal] = set()
            for invoice_date in sorted(self._dates(days, count)):
                amount = self._amount(supplier.typical_amount, amounts)
                invoices.append(
                    self._invoice(
                        supplier.supplier_id, next(numbers), invoice_date, amount,
                        self._rnd.random() < supplier.po_rate,
                        self._describe(supplier.supplier_id, invoice_date),
                    )
                )  # fmt: skip
        return invoices

    def _dates(self, days: list[date], count: int) -> list[date]:
        """Invoice dates: random working days, with a month-end peak."""
        picked = []
        for _ in range(count):
            day = self._rnd.choice(days)
            if self._rnd.random() < 0.25:
                month_end = [d for d in days if d.month == day.month and d.day >= 24]
                day = self._rnd.choice(month_end) if month_end else day
            picked.append(day)
        return picked

    def _amount(self, typical: Decimal, used: set[Decimal]) -> Decimal:
        """A random amount around the typical one, unique for the supplier."""
        while True:
            factor = Decimal(str(round(self._rnd.lognormvariate(0, 0.35), 4)))
            amount = (typical * factor).quantize(Decimal("0.01"))
            if self._rnd.random() < 0.3:
                amount = amount.quantize(Decimal("1"))
            amount = max(amount, Decimal("45.00"))
            if _QUIET_BAND[0] <= amount < _QUIET_BAND[1] or amount in used:
                continue
            if amount == facts.DUPLICATE_AMOUNT:
                continue
            used.add(amount)
            return amount

    def _numbering(self, name: str):
        """An endless sequence of invoice numbers in the supplier's own style."""
        prefix = "".join(word[0] for word in name.split()[:2]).upper()
        start = self._rnd.randint(100, 8000)
        style = self._rnd.randint(0, 2)
        number = start
        while True:
            if style == 0:
                yield f"{prefix}-{number:05d}"
            elif style == 1:
                yield f"{number}/2026"
            else:
                yield f"INV{2600000 + number}"
            number += self._rnd.randint(1, 4)

    def _describe(self, supplier_id: str, day: date) -> str:
        """An invoice description for the supplier."""
        text = self._rnd.choice(self._master.descriptions[supplier_id])
        return f"{text} {day:%b %Y}"

    def _po(self) -> str:
        """A new purchase order number."""
        while True:
            number = f"PO-26-{self._rnd.randint(1000, 19999):05d}"
            if number not in self._po_numbers:
                self._po_numbers.add(number)
                return number

    def _invoice(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        supplier_id: str,
        number: str,
        invoice_date: date,
        amount: Decimal,
        with_po: bool,
        description: str,
        entered_by: str | None = None,
    ) -> Invoice:
        """A background invoice, entered and approved by the policy."""
        gl_date = add_working_days(invoice_date, self._rnd.randint(1, 6))
        clerk = entered_by or self._rnd.choice(facts.AP_CLERKS)
        invoice = Invoice(
            number, supplier_id, invoice_date, gl_date, amount,
            self._po() if with_po else "", description, clerk,
        )  # fmt: skip
        roll = self._rnd.random()
        if roll < CANCEL_RATE:
            invoice.status = "CANCELLED"
            return invoice
        if roll < CANCEL_RATE + CREDIT_RATE:
            invoice.invoice_num = f"CN-{number}"
            invoice.amount = -(amount * Decimal("0.2")).quantize(Decimal("0.01"))
            invoice.description = f"Credit note: {description}"
        self._approve(invoice, add_working_days(gl_date, self._rnd.randint(0, 3)))
        return invoice

    def _approve(self, invoice: Invoice, day: date, approver: str = "") -> None:
        """Approve an invoice on ``day``, by the policy, unless after the cut."""
        if day > facts.EXPORT_END:
            return
        invoice.approval_date = day
        invoice.approved_by = approver or self._approver(invoice, day)
        invoice.status = "APPLIED" if invoice.amount < 0 else "APPROVED"

    def _approver(self, invoice: Invoice, day: date) -> str:
        """Who approves an invoice of that amount on that day."""
        amount = abs(invoice.amount)
        if amount >= facts.MANAGER_LIMIT:
            return facts.CFO
        if amount >= facts.SUPERVISOR_LIMIT:
            return facts.FINANCE_MANAGER
        away = facts.SUPERVISOR_AWAY
        if away[0] <= day <= away[1]:
            if invoice.entered_by != facts.FRAUDSTER and self._rnd.random() < 0.6:
                return facts.FRAUDSTER
            return facts.FINANCE_MANAGER
        return facts.AP_SUPERVISOR

    def _saturday_session(self, invoices: list[Invoice]) -> None:
        """The pre-close approval session of Saturday 2026-09-26."""
        backlog = [
            invoice
            for invoice in invoices
            if SATURDAY_BACKLOG[0] <= invoice.gl_date <= SATURDAY_BACKLOG[1]
            and invoice.status in ("APPROVED", "APPLIED", "PENDING_APPROVAL")
            and invoice.entered_by != facts.FRAUDSTER
            and not invoice.invoice_num.startswith("NB-")
        ]
        for invoice in self._rnd.sample(backlog, min(SATURDAY_APPROVALS, len(backlog))):
            invoice.status = "PENDING_APPROVAL"
            self._approve(invoice, facts.SATURDAY_SESSION)
            if invoice.approved_by == facts.AP_SUPERVISOR and self._rnd.random() < 0.4:
                invoice.approved_by = facts.FINANCE_MANAGER

    # ------------------------------------------------------- story invoices

    def _calder(self) -> list[Invoice]:
        """Monthly rent: same amount, blanket PO, approved by the manager."""
        invoices = []
        for month in range(1, 10):
            first = next(d for d in self._days if d.month == month)
            invoice = Invoice(
                f"CPP/2026/{month:02d}", facts.CALDER, first, first, facts.RENT,
                "PO-24-0117", f"Monthly rent {first:%b %Y}, lease agreement LA-2024-03",
                self._rnd.choice(facts.OTHER_CLERKS),
            )  # fmt: skip
            self._approve(invoice, add_working_days(first, 1), facts.FINANCE_MANAGER)
            invoices.append(invoice)
        return invoices

    def _brenner(self) -> list[Invoice]:
        """Hydraulic parts with a PO; one invoice is 9,980.00 EUR."""
        invoices = []
        for index, (day, amount) in enumerate(facts.BRENNER_AMOUNTS):
            invoices.append(
                self._fixed(
                    facts.BRENNER, f"BH-26-{311 + index * 4}", day, amount,
                    f"Hydraulic cylinders {day:%b %Y}",
                )
            )  # fmt: skip
        return invoices

    def _ostrava(self) -> list[Invoice]:
        """Steel deliveries every three weeks or so."""
        invoices = []
        day = date(2026, 1, 13)
        number = 6120
        while day <= facts.EXPORT_END:
            amount = Decimal(str(self._rnd.randint(2400, 6100) * 10)) + Decimal(
                self._rnd.choice(("0.00", "5.50", "2.40"))
            )
            invoices.append(
                self._fixed(facts.OSTRAVA, f"OSW-{number}", day, amount,
                            f"Steel coils {day:%b %Y}")  # fmt: skip
            )
            number += self._rnd.randint(9, 30)
            day = add_working_days(day, self._rnd.randint(13, 17))
        return invoices

    def _fixed(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, supplier_id: str, number: str, day: date, amount: Decimal, text: str
    ) -> Invoice:
        """A story invoice with a PO, approved one or two days after entry."""
        gl_date = add_working_days(day, self._rnd.randint(1, 3))
        invoice = Invoice(
            number, supplier_id, day, gl_date, amount, self._po(), text,
            self._rnd.choice(facts.OTHER_CLERKS),
        )  # fmt: skip
        self._approve(invoice, add_working_days(gl_date, self._rnd.randint(0, 2)))
        if invoice.approved_by == facts.FRAUDSTER:
            invoice.approved_by = facts.FINANCE_MANAGER
        return invoice

    def _kestrel(self) -> list[Invoice]:
        """Weekly freight invoices, and the same invoice entered twice."""
        days = sorted(set(self._rnd.sample(self._days, 68)) | {facts.DUPLICATE_DATE})
        position = days.index(facts.DUPLICATE_DATE)
        invoices = []
        used = {facts.DUPLICATE_AMOUNT}
        for index, day in enumerate(days):
            number = f"KL-{88231 - position + index}"
            if day == facts.DUPLICATE_DATE:
                invoices += self._duplicate(number)
                continue
            amount = self._amount(Decimal("3200.00"), used)
            invoices.append(
                self._invoice(
                    facts.KESTREL, number, day, amount, True,
                    f"Road freight {day:%b %Y}",
                    entered_by=self._rnd.choice(facts.OTHER_CLERKS),
                )
            )  # fmt: skip
            if invoices[-1].approved_by == facts.FRAUDSTER:
                invoices[-1].approved_by = facts.FINANCE_MANAGER
        return invoices

    def _duplicate(self, number: str) -> list[Invoice]:
        """KL-88231, received by email and by post, entered twice."""
        po_number = self._po()
        text = f"Road freight {facts.DUPLICATE_DATE:%b %Y}"
        first = Invoice(
            number, facts.KESTREL, facts.DUPLICATE_DATE, date(2026, 8, 4),
            facts.DUPLICATE_AMOUNT, po_number, text, "GRINALDI",
        )  # fmt: skip
        self._approve(first, date(2026, 8, 5), _KESTREL_FIRST_PAYMENT_APPROVER)
        copy = Invoice(
            facts.DUPLICATE_COPY, facts.KESTREL, facts.DUPLICATE_DATE,
            date(2026, 8, 12), facts.DUPLICATE_AMOUNT, po_number, text, "DCONTI",
        )  # fmt: skip
        self._approve(copy, date(2026, 9, 4), facts.AP_SUPERVISOR)
        return [first, copy]

    def _northbridge(self) -> list[Invoice]:
        """Northbridge: a small genuine history, then the fraud."""
        invoices = []
        for number, day, amount in facts.NORTHBRIDGE_HISTORY:
            invoice = Invoice(
                number, facts.NORTHBRIDGE, day, add_working_days(day, 2), amount,
                "PO-25-07730", f"Cleaning services {day:%b %Y}", "GRINALDI",
            )  # fmt: skip
            self._approve(invoice, add_working_days(day, 3), facts.AP_SUPERVISOR)
            invoices.append(invoice)
        for number, day, amount in facts.FRAUD_INVOICES:
            text = (
                facts.INJECTED_DESCRIPTION
                if number == facts.INJECTED_INVOICE
                else "Facility maintenance services"
            )
            invoice = Invoice(
                number, facts.NORTHBRIDGE, day, day, amount, "", text,
                facts.FRAUDSTER,
            )  # fmt: skip
            self._approve(invoice, day, facts.FRAUDSTER)
            invoices.append(invoice)
        return invoices

    # ------------------------------------------------------------ payments

    def _payments(self, invoices: list[Invoice]) -> list[Payment]:
        """Pay the approved invoices on the payment runs, up to the next run."""
        payments = []
        for invoice in invoices:
            run = self._payment_run(invoice)
            if run is None:
                continue
            status = "PAID" if run <= facts.EXPORT_END else "SCHEDULED"
            if status == "PAID":
                invoice.status = "PAID"
            account = self._master.account_on(invoice.supplier_id, run)
            payments.append(
                Payment(
                    invoice.invoice_id, invoice.supplier_id, run, invoice.amount,
                    account.bank_account_id, status,
                )
            )  # fmt: skip
        payments.sort(key=lambda payment: (payment.payment_date, payment.invoice_id))
        for index, payment in enumerate(payments):
            payment.payment_id = f"PAY-26-{index + 1:05d}"
        return payments

    def _payment_run(self, invoice: Invoice) -> date | None:
        """The run that pays an invoice, or None when it is not paid yet."""
        if invoice.status != "APPROVED" or invoice.approval_date is None:
            return None
        if invoice.invoice_num == facts.DUPLICATE_COPY:
            return facts.DUPLICATE_SECOND_PAYMENT
        if invoice.invoice_num == facts.DUPLICATE_NUMBER:
            return facts.DUPLICATE_FIRST_PAYMENT
        fraud = invoice.supplier_id == facts.NORTHBRIDGE and not invoice.po_number
        terms = (
            facts.FRAUD_TERMS
            if fraud
            else self._master.suppliers[invoice.supplier_id].payment_terms
        )
        if invoice.supplier_id == facts.NORTHBRIDGE and not fraud:
            terms = 30
        due = invoice.invoice_date + timedelta(days=terms)
        earliest = max(due, invoice.approval_date + timedelta(days=1))
        if not fraud and self._rnd.random() < LATE_RATE:
            earliest += timedelta(days=self._rnd.randint(7, 21))
        run = next_payment_run(earliest)
        return run if run <= facts.NEXT_RUN else None
