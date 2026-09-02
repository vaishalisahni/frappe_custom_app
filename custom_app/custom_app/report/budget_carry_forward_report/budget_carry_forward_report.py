# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, get_first_day, get_last_day, add_months, nowdate

# Reuse the budget / actual / committed maths from the Committed vs Actual report so
# both reports always agree on what a month's budget and spend are.
from custom_app.custom_app.report.budget_committed_actual_report.budget_committed_actual_report import (
    get_accounts_with_budget,
    get_actual_amount,
    get_budget_amount,
)


def execute(filters=None):
    fiscal_year = frappe.get_doc("Fiscal Year", filters.get("fiscal_year"))
    months = get_months_in_fiscal_year(fiscal_year)

    data = get_data(filters, months)
    summary_view = filters.get("view") == "Summary"

    if summary_view:
        columns = get_summary_columns()
        data = summarise(data, months)
    else:
        columns = get_columns(months)

    chart = get_chart(data, months) if not summary_view else None
    report_summary = get_report_summary(data, months, summary_view)

    return columns, data, None, chart, report_summary


def get_months_in_fiscal_year(fiscal_year):
    """
    Months of the fiscal year, stopping at the current month.

    Carry forward is only meaningful up to today — future months have no spend
    yet, so showing them would carry the full budget forward into empty columns.
    A past fiscal year is shown in full.
    """
    months = []
    start_date = getdate(fiscal_year.year_start_date)
    end_date = getdate(fiscal_year.year_end_date)

    today = getdate(nowdate())
    if start_date <= today <= end_date:
        end_date = get_last_day(today)

    current_date = get_first_day(start_date)

    while current_date <= end_date:
        months.append({
            "month_name": current_date.strftime("%B")[:3],
            "month_start": get_first_day(current_date),
            "month_end": get_last_day(current_date),
        })
        current_date = add_months(current_date, 1)

    return months


def get_summary_columns():
    """Condensed view: one line per account instead of five columns a month."""
    return [
        {"label": _("Account"), "fieldname": "account", "fieldtype": "Link",
         "options": "Account", "width": 300},
        {"label": _("Budget to Date"), "fieldname": "total_budget",
         "fieldtype": "Currency", "width": 150},
        {"label": _("Utilised"), "fieldname": "total_utilised",
         "fieldtype": "Currency", "width": 150},
        {"label": _("Available Now"), "fieldname": "available_now",
         "fieldtype": "Currency", "width": 150},
        {"label": _("Utilised %"), "fieldname": "utilised_pct",
         "fieldtype": "Percent", "width": 110},
    ]


def get_columns(months):
    """Account, then five running columns per month."""
    columns = [
        {
            "label": _("Account"),
            "fieldname": "account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 250,
        }
    ]

    for month in months:
        month_name = month["month_name"]
        key = month_name.lower()

        columns.append({
            "label": _(f"{month_name} Opening (C/F)"),
            "fieldname": f"{key}_opening",
            "fieldtype": "Currency",
            "width": 120,
        })
        columns.append({
            "label": _(f"{month_name} Budget"),
            "fieldname": f"{key}_budget",
            "fieldtype": "Currency",
            "width": 120,
        })
        columns.append({
            "label": _(f"{month_name} Available"),
            "fieldname": f"{key}_available",
            "fieldtype": "Currency",
            "width": 120,
        })
        columns.append({
            "label": _(f"{month_name} Utilised"),
            "fieldname": f"{key}_utilised",
            "fieldtype": "Currency",
            "width": 120,
        })
        columns.append({
            "label": _(f"{month_name} Closing (C/F)"),
            "fieldname": f"{key}_closing",
            "fieldtype": "Currency",
            "width": 120,
        })

    return columns


def get_open_commitment_amount(account, cost_center, start_date, end_date, company):
    """
    PR/EC raised that has NOT yet turned into actual spend.

    Deliberately excludes anything get_actual_amount() already counts, otherwise
    the same rupee is deducted twice and the carry forward is understated:
      - Expense Claims that are Finance Approved  -> already actual
      - Material Requests that have been ordered  -> spend lands via Purchase Invoice

    Rejected / Cancelled claims are excluded too: that money will never be spent,
    so it must stay available rather than be held back.
    """
    total = 0

    mr_conditions = [
        "mr.docstatus = 1",
        "ifnull(mr.per_ordered, 0) = 0",
        "mr.status not in ('Stopped', 'Cancelled')",
        "mr.transaction_date BETWEEN %(start_date)s AND %(end_date)s",
        "mri.expense_account = %(account)s",
    ]
    if cost_center:
        mr_conditions.append("mri.cost_center = %(cost_center)s")
    if company:
        mr_conditions.append("mr.company = %(company)s")

    mr = frappe.db.sql(f"""
        SELECT SUM(mri.amount) AS total_amount
        FROM `tabMaterial Request Item` mri
        INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
        WHERE {" AND ".join(mr_conditions)}
    """, {
        "account": account, "cost_center": cost_center,
        "start_date": start_date, "end_date": end_date, "company": company,
    }, as_dict=True)
    total += flt(mr[0].total_amount) if mr and mr[0].total_amount else 0

    ec_conditions = [
        "ec.docstatus = 1",
        "ifnull(ec.workflow_state, '') not in ('Finance Approved', 'Rejected', 'Cancelled')",
        "ec.posting_date BETWEEN %(start_date)s AND %(end_date)s",
        "ecd.default_account = %(account)s",
    ]
    if cost_center:
        ec_conditions.append("ecd.cost_center = %(cost_center)s")
    if company:
        ec_conditions.append("ec.company = %(company)s")

    ec = frappe.db.sql(f"""
        SELECT SUM(ecd.amount) AS total_amount
        FROM `tabExpense Claim Detail` ecd
        INNER JOIN `tabExpense Claim` ec ON ec.name = ecd.parent
        WHERE {" AND ".join(ec_conditions)}
    """, {
        "account": account, "cost_center": cost_center,
        "start_date": start_date, "end_date": end_date, "company": company,
    }, as_dict=True)
    total += flt(ec[0].total_amount) if ec and ec[0].total_amount else 0

    return total


def get_data(filters, months):
    company = filters.get("company")
    cost_center = filters.get("cost_center")
    include_committed = filters.get("include_committed")

    data = []

    for account in get_accounts_with_budget(filters):
        row = {"account": account}

        # unspent budget rolled in from the previous month
        carry_forward = 0

        for month in months:
            key = month["month_name"].lower()

            budget = flt(get_budget_amount(
                account, cost_center, month["month_start"], month["month_end"], company
            ))

            utilised = flt(get_actual_amount(
                account, cost_center, month["month_start"], month["month_end"], company
            ))

            if include_committed:
                utilised += flt(get_open_commitment_amount(
                    account, cost_center, month["month_start"], month["month_end"], company
                ))

            # round each month so the running balance cannot accumulate
            # floating point noise like 432591.89997840015
            budget = flt(budget, 2)
            utilised = flt(utilised, 2)
            available = flt(carry_forward + budget, 2)
            closing = flt(available - utilised, 2)

            row[f"{key}_opening"] = carry_forward
            row[f"{key}_budget"] = budget
            row[f"{key}_available"] = available
            row[f"{key}_utilised"] = utilised
            row[f"{key}_closing"] = closing

            # whatever is left becomes next month's opening; a negative value is
            # kept on purpose so an overspend eats into the next month
            carry_forward = closing

        data.append(row)

    return data


def summarise(data, months):
    """Collapse the monthly grid into one row per account."""
    rows = []
    for r in data:
        total_budget = flt(sum(r[f"{m['month_name'].lower()}_budget"] for m in months), 2)
        total_utilised = flt(sum(r[f"{m['month_name'].lower()}_utilised"] for m in months), 2)
        available_now = r[f"{months[-1]['month_name'].lower()}_closing"] if months else 0

        rows.append({
            "account": r["account"],
            "total_budget": total_budget,
            "total_utilised": total_utilised,
            "available_now": available_now,
            "utilised_pct": flt((total_utilised / total_budget * 100), 2) if total_budget else 0,
        })
    return rows


def get_chart(data, months):
    """Budget vs Utilised vs closing carry forward, totalled across accounts."""
    if not months:
        return None

    labels, budget, utilised, closing = [], [], [], []

    for month in months:
        key = month["month_name"].lower()
        labels.append(month["month_name"])
        budget.append(flt(sum(r[f"{key}_budget"] for r in data), 2))
        utilised.append(flt(sum(r[f"{key}_utilised"] for r in data), 2))
        closing.append(flt(sum(r[f"{key}_closing"] for r in data), 2))

    return {
        "data": {
            "labels": labels,
            "datasets": [
                {"name": _("Budget"), "values": budget},
                {"name": _("Utilised"), "values": utilised},
                {"name": _("Carried Forward"), "values": closing},
            ],
        },
        "type": "bar",
        "colors": ["#7cd6fd", "#ff5858", "#5e64ff"],
        "barOptions": {"stacked": 0},
        "fieldtype": "Currency",
    }


def get_report_summary(data, months, summary_view):
    """KPI cards above the grid."""
    if not months or not data:
        return None

    if summary_view:
        total_budget = flt(sum(r["total_budget"] for r in data), 2)
        total_utilised = flt(sum(r["total_utilised"] for r in data), 2)
        available_now = flt(sum(r["available_now"] for r in data), 2)
    else:
        keys = [m["month_name"].lower() for m in months]
        total_budget = flt(sum(r[f"{k}_budget"] for r in data for k in keys), 2)
        total_utilised = flt(sum(r[f"{k}_utilised"] for r in data for k in keys), 2)
        available_now = flt(sum(r[f"{keys[-1]}_closing"] for r in data), 2)

    pct = flt((total_utilised / total_budget * 100), 1) if total_budget else 0

    return [
        {"value": total_budget, "label": _("Budget to Date"),
         "datatype": "Currency", "indicator": "Blue"},
        {"value": total_utilised, "label": _("Utilised"),
         "datatype": "Currency", "indicator": "Orange"},
        {"value": available_now, "label": _("Available Now (C/F)"),
         "datatype": "Currency", "indicator": "Green" if available_now >= 0 else "Red"},
        {"value": pct, "label": _("Utilised %"),
         "datatype": "Percent", "indicator": "Red" if pct > 100 else "Green"},
    ]
