"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Generates the employees (hr/employees.csv) and the ERP roles
    (security/user_roles.csv) of Halden Manufacturing.

    The finance team is fixed by the story; the other employees are random.
    Only the fraudster holds conflicting roles.
"""

import random
from datetime import date, timedelta

from fraud_detective.sample_case import facts
from fraud_detective.sample_case.records import Employee, RoleGrant, fake_iban

#: Number of employees.
EMPLOYEES = 250

_FIRST_NAMES = (
    "Alessandro Alessia Alberto Anna Antonio Beatrice Carlo Chiara Claudio "
    "Cristina Daniele Elisa Emanuele Federica Filippo Francesca Gabriele Giada "
    "Giorgio Giovanna Ilaria Jacopo Laura Leonardo Lorenzo Lucia Manuela Marta "
    "Massimo Matteo Michela Monica Nicola Paola Pietro Riccardo Roberta Sara "
    "Simone Stefania Stefano Tommaso Valentina Valerio Vittoria"
).split()

_LAST_NAMES = (
    "Barbieri Benedetti Bernardi Bruno Caruso Cattaneo Costa D'Angelo De Luca "
    "Fabbri Farina Ferrara Fontana Galli Gentile Giordano Guerra Leone "
    "Lombardi Longo Mancini Mariani Martinelli Marchetti Mazza Monti Morelli "
    "Neri Orlando Palumbo Parisi Pellegrini Rizzo Romano Russo Santoro Sala "
    "Serra Silvestri Testa Valentini Villa Vitale Zanetti"
).split()

#: Department, share of employees, job titles.
_DEPARTMENTS = (
    ("Production", 140, ("Machine Operator", "Assembler", "Shift Lead", "Welder")),
    ("Logistics", 25, ("Warehouse Operator", "Logistics Planner", "Forklift Driver")),
    ("Sales", 25, ("Account Manager", "Sales Assistant", "Area Manager")),
    ("Engineering", 25, ("Mechanical Engineer", "Quality Engineer", "Technician")),
    ("Purchasing", 7, ("Buyer", "Purchasing Assistant")),
    ("HR", 6, ("HR Specialist", "Payroll Specialist")),
    ("IT", 8, ("System Engineer", "Help Desk Analyst", "Developer")),
)

#: The people of the story: user name, full name, department, title, hire date.
_KEY_PEOPLE = (
    (facts.FRAUDSTER, "Marco Ferri", "Finance", "AP Clerk", date(2019, 3, 11)),
    (facts.AP_SUPERVISOR, "Silvia Colombo", "Finance", "AP Supervisor", date(2014, 9, 1)),
    (facts.FINANCE_MANAGER, "Andrea Moretti", "Finance", "Finance Manager", date(2016, 2, 15)),
    (facts.CFO, "Paola Esposito", "Finance", "Chief Financial Officer", date(2018, 6, 4)),
    (facts.MASTER_DATA, "Paolo Ricci", "Finance", "Master Data Specialist", date(2017, 10, 2)),
    ("GRINALDI", "Giulia Rinaldi", "Finance", "AP Clerk", date(2021, 4, 12)),
    ("LBIANCHI", "Luca Bianchi", "Finance", "AP Clerk", date(2015, 1, 19)),
    ("EGALLO", "Elena Gallo", "Finance", "AP Clerk", date(2022, 9, 5)),
    ("DCONTI", "Davide Conti", "Finance", "AP Clerk", date(2020, 11, 2)),
    (facts.TREASURY, "Roberto Greco", "Finance", "Treasury Specialist", date(2013, 5, 6)),
    ("FMARINO", "Francesca Marino", "Finance", "Accountant", date(2012, 3, 1)),
    ("GRICCI", "Giorgio Ricci", "Finance", "Controller", date(2011, 7, 18)),
    (facts.IT_SECURITY, "Daniela Marini", "IT", "IT Security Administrator", date(2016, 11, 7)),
    ("LFONTANA", "Laura Fontana", "IT", "IT Manager", date(2010, 4, 12)),
)  # fmt: skip


class PeopleBuilder:
    """Builds the employees and their ERP roles.

    Args:
        rnd: The random generator.
    """

    def __init__(self, rnd: random.Random) -> None:
        self._rnd = rnd

    def employees(self) -> list[Employee]:
        """All employees, ordered by employee id (that is, by hire date).

        Returns:
            250 employees; the fraudster has the payroll IBAN of the story.
        """
        people = [
            (hired, user, name, dept, title) for user, name, dept, title, hired in _KEY_PEOPLE
        ]  # fmt: skip
        taken = {user for _, user, _, _, _ in people}
        for department, count, titles in _DEPARTMENTS:
            for _ in range(count):
                name, user = self._new_name(taken)
                hired = date(2003, 1, 1) + timedelta(days=self._rnd.randint(0, 8300))
                people.append((hired, user, name, department, self._rnd.choice(titles)))
        people.sort()
        employees = []
        for index, (hired, user, name, dept, title) in enumerate(people[:EMPLOYEES]):
            iban = (
                facts.FRAUDSTER_IBAN
                if user == facts.FRAUDSTER
                else fake_iban("IT", self._rnd)
            )
            employees.append(
                Employee(f"E{10001 + index}", name, user, dept, title, hired, iban)
            )
        return employees

    def _new_name(self, taken: set[str]) -> tuple[str, str]:
        """A random full name with a user name not used yet."""
        while True:
            first = self._rnd.choice(_FIRST_NAMES)
            last = self._rnd.choice(_LAST_NAMES)
            user = (first[0] + last.replace("'", "").replace(" ", "")).upper()[:8]
            if user not in taken:
                taken.add(user)
                return f"{first} {last}", user

    def roles(self, employees: list[Employee]) -> list[RoleGrant]:
        """The ERP roles, ordered by user name and grant date.

        Args:
            employees: The employees, to pick the ERP users among them.

        Returns:
            About 120 role grants.
        """
        grants = self._finance_roles()
        tickets = iter(range(41200, 49999, 37))
        others = [
            person
            for person in employees
            if person.department
            in ("Purchasing", "Logistics", "IT", "Engineering", "Sales")
            and person.user_name not in (facts.IT_SECURITY, "LFONTANA")
        ]
        for person in others:
            for role in self._roles_for(person.department):
                granted = max(person.hire_date, date(2018, 1, 8)) + timedelta(
                    days=self._rnd.randint(3, 40)
                )
                grants.append(
                    RoleGrant(
                        person.user_name,
                        role,
                        granted,
                        facts.IT_SECURITY,
                        f"TCK-{next(tickets)}",
                    )
                )
        return sorted(grants, key=lambda grant: (grant.user_name, grant.granted_date))

    def _roles_for(self, department: str) -> list[str]:
        """The roles of a non-finance ERP user."""
        if department == "Purchasing":
            return ["Purchase Order Entry", "AP Inquiry"]
        roll = self._rnd.random()
        if department == "Logistics":
            return ["Goods Receipt", "Inventory Inquiry"] if roll < 0.8 else []
        if department == "Sales":
            return ["Sales Order Entry", "Customer Inquiry"] if roll < 0.6 else []
        if department == "IT":
            return ["ERP Support (read only)"] if roll < 0.6 else []
        return ["Purchase Requisition"] if roll < 0.5 else []

    @staticmethod
    def _finance_roles() -> list[RoleGrant]:
        """The roles of the finance team, fixed by the story."""
        sec = facts.IT_SECURITY
        boss, manager = facts.AP_SUPERVISOR, facts.FINANCE_MANAGER
        grants = [
            RoleGrant(facts.FRAUDSTER, "Invoice Entry", date(2019, 3, 18), sec, "TCK-18233"),
            RoleGrant(facts.FRAUDSTER, "AP Inquiry", date(2019, 3, 18), sec, "TCK-18233"),
            RoleGrant(
                facts.FRAUDSTER, "Supplier Maintenance", facts.ROLE_GRANT_DATE, sec,
                "TCK-55102", "covering P. Ricci during summer holidays",
            ),
            RoleGrant(
                facts.FRAUDSTER, "Invoice Approver", facts.ROLE_GRANT_DATE, sec,
                "TCK-55102", "temporary delegation, summer holidays",
            ),
            RoleGrant(boss, "Invoice Approver", date(2014, 9, 8), sec, "TCK-09114"),
            RoleGrant(boss, "AP Inquiry", date(2014, 9, 8), sec, "TCK-09114"),
            RoleGrant(manager, "Invoice Approver", date(2016, 2, 22), sec, "TCK-11870"),
            RoleGrant(manager, "GL Inquiry", date(2016, 2, 22), sec, "TCK-11870"),
            RoleGrant(facts.CFO, "Invoice Approver", date(2018, 6, 11), sec, "TCK-15422"),
            RoleGrant(facts.CFO, "GL Inquiry", date(2018, 6, 11), sec, "TCK-15422"),
            RoleGrant(
                facts.MASTER_DATA, "Supplier Maintenance", date(2017, 10, 9), sec,
                "TCK-13305",
            ),
            RoleGrant(facts.MASTER_DATA, "AP Inquiry", date(2017, 10, 9), sec, "TCK-13305"),
            RoleGrant(facts.TREASURY, "Payment Run", date(2013, 5, 13), sec, "TCK-07001"),
            RoleGrant(facts.TREASURY, "AP Inquiry", date(2013, 5, 13), sec, "TCK-07001"),
            RoleGrant("FMARINO", "GL Inquiry", date(2018, 1, 15), sec, "TCK-14010"),
            RoleGrant("FMARINO", "GL Journal Entry", date(2018, 1, 15), sec, "TCK-14010"),
            RoleGrant("GRICCI", "GL Inquiry", date(2018, 1, 15), sec, "TCK-14011"),
            RoleGrant("GRICCI", "AP Inquiry", date(2018, 1, 15), sec, "TCK-14011"),
            RoleGrant(sec, "System Administrator", date(2016, 11, 14), "GRICCI", "TCK-12950"),
        ]  # fmt: skip
        clerk_dates = {
            "GRINALDI": date(2021, 4, 19),
            "LBIANCHI": date(2018, 1, 22),
            "EGALLO": date(2022, 9, 12),
            "DCONTI": date(2020, 11, 9),
        }
        for index, (user, granted) in enumerate(clerk_dates.items()):
            ticket = f"TCK-{30410 + index * 1117}"
            grants.append(RoleGrant(user, "Invoice Entry", granted, sec, ticket))
            grants.append(RoleGrant(user, "AP Inquiry", granted, sec, ticket))
        return grants
