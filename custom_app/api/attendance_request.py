"""
Attendance Request visibility.

ERPNext/HRMS shares every Leave Application with the employee's leave
approver, which is why approvers can act on them even when User Permissions
would otherwise hide the record. Attendance Request has no such approver
field and no sharing, so approvers currently cannot see their reportees'
requests at all once a Company or Employee user permission is in play.

This module mirrors the Leave Application behaviour for Attendance Request:
the request is shared, with submit rights, to the employee's leave approver.

HR is deliberately NOT handled by sharing. HR users already have the HR
User / HR Manager role, so what they can see is decided by their Company
user permission - which is the correct, company-scoped behaviour. Use
audit_hr_visibility() to find HR users whose permissions block them.
"""

import frappe
from frappe import _


def _leave_approver(employee):
    if not employee:
        return None
    return frappe.db.get_value("Employee", employee, "leave_approver")


def share_with_leave_approver(doc, method=None):
    """
    doc_event: Attendance Request on_update

    Mirrors hrms.hr.utils.share_doc_with_approver - only shares when the
    approver cannot already act on the document, so no redundant DocShare
    rows are created for approvers who are covered by user permissions.
    """
    approver = _leave_approver(doc.employee)
    if not approver:
        return

    if not frappe.has_permission(doc=doc, ptype="submit", user=approver):
        frappe.share.add_docshare(
            doc.doctype, doc.name, approver, submit=1,
            flags={"ignore_share_permission": True},
        )

    # If the employee's approver changed since this document was last saved,
    # drop the old share so a former approver keeps no access.
    before = doc.get_doc_before_save()
    if before and before.get("employee") != doc.employee:
        old_approver = _leave_approver(before.get("employee"))
        if old_approver and old_approver != approver:
            frappe.share.remove(doc.doctype, doc.name, old_approver)
