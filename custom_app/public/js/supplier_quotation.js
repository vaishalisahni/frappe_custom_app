// Keep the rate that came from the Purchase Request.
//
// Selecting a vendor makes ERPNext re-fetch the Price List Rate for every
// item from the buying price list. Where an Item Price exists, that wipes the
// rate carried over from the Material Request (e.g. 43,750 becomes 12,538).
//
// Here we snapshot the rates before the fetch and restore them afterwards, so
// only the automatic overwrite is undone -- the user can still edit the rate
// by hand, which a Supplier Quotation must allow.

frappe.ui.form.on('Supplier Quotation', {
    supplier(frm) {
        if (!frm.doc.items || !frm.doc.items.length) return;

        // Taken synchronously, before the (asynchronous) price fetch runs.
        const before = {};
        frm.doc.items.forEach((row) => {
            if (flt(row.rate)) {
                before[row.name] = flt(row.rate);
            }
        });
        if (!Object.keys(before).length) return;

        frappe.after_ajax(() => {
            setTimeout(() => restore_request_rates(frm, before), 300);
        });
    }
});

function restore_request_rates(frm, before) {
    let restored = 0;

    (frm.doc.items || []).forEach((row) => {
        const original = before[row.name];
        if (!original) return;
        if (flt(row.rate) === flt(original)) return;

        // price_list_rate must be reset too, otherwise ERPNext recalculates
        // rate back from the fetched price on the next refresh.
        frappe.model.set_value(row.doctype, row.name, 'price_list_rate', original);
        frappe.model.set_value(row.doctype, row.name, 'rate', original);
        restored++;
    });

    if (restored) {
        frm.refresh_field('items');
        frappe.show_alert({
            message: __('Rate from the Purchase Request has been kept for {0} item(s).', [restored]),
            indicator: 'blue'
        }, 7);
    }
}
