// Copyright (c) 2026, . and contributors
// For license information, please see license.txt

frappe.query_reports["Budget Carry Forward Report"] = {
	"filters": [
		{
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company"),
            "reqd": 1
        },
        {
            "fieldname": "cost_center",
            "label": __("Cost Center"),
            "fieldtype": "Link",
            "options": "Cost Center",
            "reqd": 0,
            get_query: function () {
				let company = frappe.query_report.get_filter_value("company");

				if (!company) {
					return {};
				}

				return {
					filters: {
						company: company
					}
				};
			}
        },
        {
            "fieldname": "fiscal_year",
            "label": __("Fiscal Year"),
            "fieldtype": "Link",
            "options": "Fiscal Year",
            "default": frappe.defaults.get_user_default("fiscal_year"),
            "reqd": 1
        },
        {
            "fieldname": "view",
            "label": __("View"),
            "fieldtype": "Select",
            "options": "Monthly Detail\nSummary",
            "default": "Monthly Detail"
        },
        {
            "fieldname": "include_committed",
            "label": __("Treat PR/EC Raised as Utilised"),
            "fieldtype": "Check",
            "default": 0
        }
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!column.fieldname) return value;

		// overspend / negative carry forward stands out
		const is_balance = column.fieldname.endsWith("_closing")
			|| column.fieldname.endsWith("_opening")
			|| column.fieldname === "available_now";

		if (is_balance && data && flt(data[column.fieldname]) < 0) {
			return `<span style="color:var(--red-500);font-weight:600">${value}</span>`;
		}

		// what's actually spendable this month is the number people look for
		if (column.fieldname.endsWith("_available")) {
			return `<span style="font-weight:600">${value}</span>`;
		}

		// carried-in balance is context, not this month's money
		if (column.fieldname.endsWith("_opening")) {
			return `<span style="color:var(--text-muted)">${value}</span>`;
		}

		if (column.fieldname.endsWith("_utilised") && data
			&& flt(data[column.fieldname]) > 0) {
			return `<span style="color:var(--orange-600)">${value}</span>`;
		}

		if (column.fieldname === "utilised_pct" && data) {
			const pct = flt(data.utilised_pct);
			if (pct > 100) {
				return `<span style="color:var(--red-500);font-weight:600">${value}</span>`;
			}
			if (pct >= 80) {
				return `<span style="color:var(--orange-600)">${value}</span>`;
			}
		}

		return value;
	}
};
