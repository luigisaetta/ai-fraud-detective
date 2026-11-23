"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Generates the supplier master data: ap/suppliers.csv,
    ap/supplier_bank_accounts.csv and ap/supplier_changes.log.

    The five suppliers of the story are fixed; the others are random. Every
    change in the log is applied to the master data, so the files agree.
"""

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fraud_detective.sample_case import facts
from fraud_detective.sample_case.records import (
    BankAccount,
    Change,
    Supplier,
    fake_iban,
    working_days,
)

#: Number of suppliers.
SUPPLIERS = 180

#: Suppliers that are no longer used.
INACTIVE = 10

_COUNTRIES = (
    ("IT", 60), ("DE", 15), ("FR", 6), ("NL", 5), ("AT", 5), ("CZ", 5), ("PL", 4)
)  # fmt: skip

_LEGAL_FORMS = {
    "IT": ("S.r.l.", "S.p.A."),
    "DE": ("GmbH", "AG"),
    "FR": ("SAS", "SARL"),
    "NL": ("B.V.",),
    "AT": ("GmbH",),
    "CZ": ("s.r.o.", "a.s."),
    "PL": ("Sp. z o.o.",),
}

_PHONE_PREFIX = {
    "IT": "+39 02", "DE": "+49 89", "FR": "+33 4", "NL": "+31 10",
    "AT": "+43 512", "CZ": "+420 59", "PL": "+48 32",
}  # fmt: skip

_SITES = {
    "IT": ("MI01", "BG01", "BS01", "VR01", "BO01", "TO01"),
    "DE": ("MUC1", "STR1", "NUE1"),
    "FR": ("LYO1", "GRE1"),
    "NL": ("RTM1", "EIN1"),
    "AT": ("INN1", "LNZ1"),
    "CZ": ("OST1", "BRN1"),
    "PL": ("KAT1", "WRO1"),
}

_BANKS = {
    "IT": ("Banca Padana", "Credito Lombardo", "Banca del Garda", "Cassa Emiliana"),
    "DE": ("Rheinische Handelsbank", "Bayerische Gewerbebank"),
    "FR": ("Banque Rhodanienne",),
    "NL": ("Maas Handelsbank",),
    "AT": ("Tiroler Gewerbebank",),
    "CZ": ("Moravska Obchodni Banka",),
    "PL": ("Slaski Bank Handlowy",),
}

_STEMS = (
    "Alpina Arcadia Aster Aurora Bergamo Borea Brenta Calypso Castor Cervino "
    "Cobalt Corvo Danubia Delta Dolomit Elba Emilia Eridano Ferro Fiordo Garda "
    "Helix Iride Isonzo Jura Kappa Kronos Ladin Lario Lumen Magna Meridian "
    "Mincio Monviso Nova Oglio Orion Padana Pegaso Polaris Quadra Rhenus Rubicon "
    "Saturn Serio Sirio Solaris Taro Tecna Ticino Titan Union Vega Velino "
    "Vesta Westfal Zenit Zephyr Atlas Boreal Corona Draco Etna Falco Gemma "
    "Hydra Icaro Lyra Mistral Nadir Ostro Pavia Rigel Scirocco Tauri Ursa"
).split()

#: Category, share, amount range in EUR, PO rate, descriptions.
_CATEGORIES = (
    ("Raw materials", 18, (2500, 38000), 0.98,
     ("Steel coils", "Aluminium profiles", "Polymer granules", "Copper wire")),
    ("Components", 30, (400, 9000), 0.97,
     ("Bearings and seals", "Fasteners", "Electric motors", "Valves and fittings")),
    ("Logistics", 12, (300, 5200), 0.9,
     ("Road freight", "Inbound transport", "Courier services")),
    ("Maintenance", 14, (250, 4800), 0.75,
     ("Machine maintenance", "Electrical maintenance", "HVAC service")),
    ("IT services", 8, (300, 8500), 0.6,
     ("Software subscription", "IT support", "Network services")),
    ("Professional services", 8, (1200, 8800), 0.4,
     ("Consulting services", "Legal services", "Audit support")),
    ("Office and facilities", 6, (90, 1800), 0.5,
     ("Office supplies", "Cleaning services", "Canteen services")),
    ("Utilities", 4, (1500, 24000), 0.0,
     ("Electricity", "Natural gas", "Water")),
)  # fmt: skip

#: Typical number of invoices a year, by profile weight (Pareto-like).
_FIXED_PROFILES = {
    facts.CALDER: ("Rent", Decimal("18500.00"), 0.0, 1.0),
    facts.KESTREL: ("Logistics", Decimal("3200.00"), 0.0, 0.9),
    facts.BRENNER: ("Components", Decimal("9800.00"), 0.0, 1.0),
    facts.OSTRAVA: ("Raw materials", Decimal("41000.00"), 0.0, 1.0),
    facts.NORTHBRIDGE: ("Office and facilities", Decimal("700.00"), 0.0, 1.0),
}


@dataclass
class MasterData:
    """The supplier master data, with every change applied.

    Attributes:
        suppliers: Suppliers by id, in id order.
        accounts: All bank accounts, current and past, in id order.
        changes: The 2026 change log, in time order.
        descriptions: Invoice descriptions of each supplier (not exported).
    """

    suppliers: dict[str, Supplier]
    accounts: list[BankAccount]
    changes: list[Change]
    descriptions: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def account_on(self, supplier_id: str, day: date) -> BankAccount:
        """The bank account of a supplier that was valid on ``day``.

        Args:
            supplier_id: The supplier.
            day: The payment date.

        Returns:
            The account whose validity covers the day.

        Raises:
            LookupError: No account was valid on that day.
        """
        for account in self.accounts:
            if (
                account.supplier_id == supplier_id
                and account.start_date <= day
                and (account.end_date is None or day < account.end_date)
            ):
                return account
        raise LookupError(f"no bank account for {supplier_id} on {day}")


class SupplierBuilder:
    """Builds the supplier master data.

    Args:
        rnd: The random generator.
        fraud_iban: The account the fraudster moves Northbridge to.
    """

    def __init__(self, rnd: random.Random, fraud_iban: str) -> None:
        self._rnd = rnd
        self._fraud_iban = fraud_iban
        self._names: set[str] = set()
        self._pending_accounts: list[BankAccount] = []
        self._changes: list[Change] = []

    def build(self) -> MasterData:
        """Build suppliers, accounts and the change log.

        Returns:
            The master data, consistent with its change log.
        """
        suppliers, descriptions = self._suppliers()
        for supplier in suppliers.values():
            self._pending_accounts.append(
                BankAccount(
                    "", supplier.supplier_id,
                    fake_iban(supplier.country, self._rnd),
                    self._rnd.choice(_BANKS[supplier.country]),
                    supplier.creation_date,
                )
            )  # fmt: skip
        self._old_accounts(suppliers)
        self._routine_changes(suppliers)
        self._bank_change(
            suppliers[facts.OSTRAVA],
            datetime.combine(facts.OSTRAVA_CHANGE_DATE, time(11, 24, 9)),
            facts.MASTER_DATA,
            "New bank details on supplier letter, confirmed by call-back",
            facts.OSTRAVA_VERIFICATION,
            facts.AP_SUPERVISOR,
        )
        self._fraud_changes(suppliers[facts.NORTHBRIDGE])
        accounts = self._number_accounts(suppliers)
        changes = sorted(self._changes, key=lambda change: change.timestamp)
        return MasterData(suppliers, accounts, changes, descriptions)

    # ----------------------------------------------------------- suppliers

    def _suppliers(self) -> tuple[dict[str, Supplier], dict[str, tuple[str, ...]]]:
        """The suppliers, fixed and random, by id."""
        fixed = self._fixed_suppliers()
        free = [
            number
            for number in range(1001, 2400)
            if f"S{number}" not in facts.FIXED_SUPPLIERS
        ]
        numbers = sorted(self._rnd.sample(free, SUPPLIERS - len(fixed)))
        suppliers = dict(fixed)
        descriptions = {
            facts.CALDER: ("Monthly rent, lease agreement LA-2024-03",),
            facts.KESTREL: ("Road freight", "Inbound transport", "Pallet storage"),
            facts.BRENNER: ("Hydraulic cylinders", "Hydraulic power unit parts"),
            facts.OSTRAVA: ("Steel coils", "Hot rolled steel sheets"),
            facts.NORTHBRIDGE: ("Cleaning services",),
        }
        for number in numbers:
            supplier, texts = self._random_supplier(f"S{number}")
            suppliers[supplier.supplier_id] = supplier
            descriptions[supplier.supplier_id] = texts
        inactive = self._rnd.sample(
            [sid for sid in suppliers if sid not in facts.FIXED_SUPPLIERS], INACTIVE
        )
        for supplier_id in inactive:
            suppliers[supplier_id].status = "INACTIVE"
            suppliers[supplier_id].weight = 0.0
        return dict(sorted(suppliers.items())), descriptions

    def _fixed_suppliers(self) -> dict[str, Supplier]:
        """The five suppliers of the story."""
        specs = (
            (facts.CALDER, "Calder Property Partners S.r.l.", "IT", "MI01",
             date(2015, 3, 2), 15, "calderproperty.example"),
            (facts.KESTREL, "Kestrel Logistics B.V.", "NL", "RTM1",
             date(2016, 5, 17), 30, "kestrel-logistics.example"),
            (facts.BRENNER, "Brenner Hydraulik GmbH", "AT", "INN1",
             date(2018, 9, 24), 60, "brenner-hydraulik.example"),
            (facts.OSTRAVA, "Ostrava Steel Works a.s.", "CZ", "OST1",
             date(2017, 2, 6), 60, "ostravasteel.example"),
            (facts.NORTHBRIDGE, "Northbridge Facility Services S.r.l.", "IT",
             "BG01", date(2023, 1, 16), 30, facts.NORTHBRIDGE_DOMAIN),
        )  # fmt: skip
        suppliers = {}
        for supplier_id, name, country, site, created, terms, domain in specs:
            category, amount, weight, po_rate = _FIXED_PROFILES[supplier_id]
            self._names.add(name)
            suppliers[supplier_id] = Supplier(
                supplier_id, name, site, self._tax_id(country), country, "ACTIVE",
                created, self._creator(created), terms, "", f"accounts@{domain}",
                self._phone(country), category, amount, weight, po_rate,
            )  # fmt: skip
        return suppliers

    def _random_supplier(self, supplier_id: str) -> tuple[Supplier, tuple[str, ...]]:
        """A random supplier and the descriptions of its invoices."""
        countries = [code for code, share in _COUNTRIES for _ in range(share)]
        country = self._rnd.choice(countries)
        shares = [spec for spec in _CATEGORIES for _ in range(spec[1])]
        category, _, (low, high), po_rate, texts = self._rnd.choice(shares)
        name, slug = self._unique_name(country, category.split()[0])
        created = date(2010, 1, 4) + timedelta(days=self._rnd.randint(0, 5800))
        typical = Decimal(str(round(self._rnd.uniform(low, high), -1)))
        supplier = Supplier(
            supplier_id, name, self._rnd.choice(_SITES[country]),
            self._tax_id(country), country, "ACTIVE", created,
            self._creator(created), self._rnd.choice((30, 30, 45, 60, 60, 90)), "",
            f"accounts@{slug}.example", self._phone(country), category, typical,
            self._rnd.paretovariate(1.3), po_rate,
        )  # fmt: skip
        return supplier, texts

    def _unique_name(self, country: str, sector: str) -> tuple[str, str]:
        """A company name not used yet, and the slug of its email domain."""
        stem = self._rnd.choice(_STEMS)
        while f"{stem} {sector}" in self._names:
            stem = self._rnd.choice(_STEMS) + self._rnd.choice(("tec", "line", "dyn"))
        self._names.add(f"{stem} {sector}")
        legal = self._rnd.choice(_LEGAL_FORMS[country])
        return f"{stem} {sector} {legal}", f"{stem}-{sector}".lower()

    def _tax_id(self, country: str) -> str:
        """A VAT number with the layout of the country."""
        digits = {"IT": 11, "DE": 9, "FR": 11, "NL": 9, "AT": 8, "CZ": 8, "PL": 10}
        body = "".join(self._rnd.choice("0123456789") for _ in range(digits[country]))
        prefix = {"AT": "ATU", "NL": "NL"}.get(country, country)
        return f"{prefix}{body}B01" if country == "NL" else f"{prefix}{body}"

    def _phone(self, country: str) -> str:
        """A phone number with the prefix of the country."""
        first, second = self._rnd.randint(100, 999), self._rnd.randint(1000, 9999)
        return f"{_PHONE_PREFIX[country]} {first} {second}"

    @staticmethod
    def _creator(created: date) -> str:
        """Who could create suppliers on that date."""
        if created >= date(2017, 10, 9):
            return facts.MASTER_DATA
        return facts.AP_SUPERVISOR if created >= date(2014, 9, 8) else "FMARINO"

    # ------------------------------------------------------------ accounts

    def _old_accounts(self, suppliers: dict[str, Supplier]) -> None:
        """Accounts replaced before 2026: they have an end date, no log line."""
        candidates = [
            supplier
            for supplier in suppliers.values()
            if supplier.creation_date < date(2022, 1, 1)
            and supplier.supplier_id not in facts.FIXED_SUPPLIERS
        ]
        for supplier in self._rnd.sample(candidates, 16):
            current = self._current(supplier.supplier_id)
            switch = date(2022, 1, 10) + timedelta(days=self._rnd.randint(0, 1400))
            old = BankAccount(
                "", supplier.supplier_id, current.iban, current.bank_name,
                current.start_date, switch,
            )  # fmt: skip
            current.iban = fake_iban(supplier.country, self._rnd)
            current.start_date = switch
            self._pending_accounts.append(old)

    def _current(self, supplier_id: str) -> BankAccount:
        """The open account of a supplier."""
        for account in self._pending_accounts:
            if account.supplier_id == supplier_id and account.end_date is None:
                return account
        raise LookupError(supplier_id)

    def _bank_change(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        supplier: Supplier,
        moment: datetime,
        user: str,
        reason: str,
        verification: str,
        approver: str,
        iban: str | None = None,
        bank: str | None = None,
    ) -> None:
        """Close the open account of a supplier and open a new one."""
        current = self._current(supplier.supplier_id)
        current.end_date = moment.date()
        new = BankAccount(
            "", supplier.supplier_id, iban or fake_iban(supplier.country, self._rnd),
            bank or self._rnd.choice(_BANKS[supplier.country]), moment.date(),
        )  # fmt: skip
        self._pending_accounts.append(new)
        self._changes.append(
            Change(
                moment, user, supplier.supplier_id, "bank_account_id",
                f"@{id(current)}", f"@{id(new)}", reason, verification, approver,
            )
        )  # fmt: skip

    def _number_accounts(self, suppliers: dict[str, Supplier]) -> list[BankAccount]:
        """Give ids to the accounts in opening order and fix the references."""
        ordered = sorted(
            self._pending_accounts,
            key=lambda account: (account.start_date, account.supplier_id),
        )
        names = {}
        for index, account in enumerate(ordered):
            account.bank_account_id = f"BA-{1001 + index}"
            names[f"@{id(account)}"] = account.bank_account_id
            if account.end_date is None:
                suppliers[account.supplier_id].bank_account_id = account.bank_account_id
        self._changes = [
            Change(
                change.timestamp, change.user, change.supplier_id, change.field_name,
                names.get(change.old, change.old), names.get(change.new, change.new),
                change.reason, change.verification_ref, change.approved_by,
            )
            for change in self._changes
        ]  # fmt: skip
        return sorted(ordered, key=lambda account: account.bank_account_id)

    # ------------------------------------------------------------- changes

    def _office_moment(self, day: date) -> datetime:
        """A random time of the working day."""
        seconds = self._rnd.randint(8 * 3600 + 1800, 17 * 3600 + 1800)
        return datetime.combine(day, time()) + timedelta(seconds=seconds)

    def _change_days(self) -> list[date]:
        """Days when the master data specialist and an approver are both in."""
        away = facts.MASTER_DATA_AWAY
        return [
            day
            for day in working_days(facts.EXPORT_START, facts.EXPORT_END)
            if not away[0] <= day <= away[1]
        ]

    def _routine_changes(self, suppliers: dict[str, Supplier]) -> None:
        """New suppliers, contacts, terms, status and legitimate bank changes."""
        days = self._change_days()
        pool = [
            supplier
            for supplier in suppliers.values()
            if supplier.supplier_id not in facts.FIXED_SUPPLIERS
        ]
        single = [
            supplier
            for supplier in pool
            if sum(
                a.supplier_id == supplier.supplier_id for a in self._pending_accounts
            )
            == 1
        ]
        newcomers = self._rnd.sample(single, 6)
        rest = [supplier for supplier in pool if supplier not in newcomers]
        picks = iter(self._rnd.sample(rest, len(rest)))
        for supplier in newcomers:
            supplier.creation_date = self._rnd.choice(days)
            supplier.created_by = facts.MASTER_DATA
            supplier.status = "ACTIVE"
            supplier.weight = max(supplier.weight, 1.0)
            self._current(supplier.supplier_id).start_date = supplier.creation_date
            self._log(supplier, "record", "", "created", "New supplier onboarding")
        for supplier in [next(picks) for _ in range(14)]:
            old = supplier.contact_email
            supplier.contact_email = old.replace("accounts@", "ap@")
            self._log(supplier, "contact_email", old, supplier.contact_email,
                      "Supplier notified new contact")  # fmt: skip
        for supplier in [next(picks) for _ in range(10)]:
            old = supplier.phone
            supplier.phone = self._phone(supplier.country)
            self._log(supplier, "phone", old, supplier.phone, "Supplier letter")
        for supplier in [next(picks) for _ in range(9)]:
            old = f"NET{supplier.payment_terms}"
            longer = [days for days in (45, 60, 90) if days > supplier.payment_terms]
            supplier.payment_terms = longer[0] if longer else 60
            self._log(supplier, "payment_terms", old, f"NET{supplier.payment_terms}",
                      "Renegotiated terms, purchasing agreement",
                      approver=facts.FINANCE_MANAGER)  # fmt: skip
        for supplier in [s for s in suppliers.values() if s.status == "INACTIVE"][:6]:
            self._log(supplier, "status", "ACTIVE", "INACTIVE",
                      "No activity in the last 24 months")  # fmt: skip
        for supplier in [next(picks) for _ in range(6)]:
            old = supplier.site_code
            supplier.site_code = self._rnd.choice(_SITES[supplier.country])
            if supplier.site_code != old:
                self._log(supplier, "site_code", old, supplier.site_code,
                          "Supplier moved to a new site")  # fmt: skip
        for index, supplier in enumerate([next(picks) for _ in range(3)]):
            day = self._rnd.choice([d for d in days if d < date(2026, 7, 1)])
            self._bank_change(
                supplier, self._office_moment(day), facts.MASTER_DATA,
                "New bank details on supplier letter, confirmed by call-back",
                f"VCB-{2205 + index * 31}", facts.AP_SUPERVISOR,
            )  # fmt: skip

    def _log(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        supplier: Supplier,
        field_name: str,
        old: str,
        new: str,
        reason: str,
        approver: str = facts.AP_SUPERVISOR,
    ) -> None:
        """Add a routine change, made by the master data specialist."""
        day = (
            supplier.creation_date
            if field_name == "record"
            else self._rnd.choice(self._change_days())
        )
        self._changes.append(
            Change(
                self._office_moment(day), facts.MASTER_DATA, supplier.supplier_id,
                field_name, old, new, reason, "", approver,
            )
        )  # fmt: skip

    def _fraud_changes(self, northbridge: Supplier) -> None:
        """The fraudster's changes to Northbridge, without verification."""
        moment = datetime.combine(facts.BANK_CHANGE_DATE, time(9, 47, 12))
        self._bank_change(
            northbridge, moment, facts.FRAUDSTER, "Supplier request by email", "",
            facts.FRAUDSTER, iban=self._fraud_iban, bank="Banca Adriatica",
        )  # fmt: skip
        old_terms = f"NET{northbridge.payment_terms}"
        northbridge.payment_terms = facts.FRAUD_TERMS
        self._changes.append(
            Change(
                moment + timedelta(minutes=3, seconds=41), facts.FRAUDSTER,
                northbridge.supplier_id, "payment_terms", old_terms,
                f"NET{facts.FRAUD_TERMS}", "Supplier request by email", "",
                facts.FRAUDSTER,
            )
        )  # fmt: skip
