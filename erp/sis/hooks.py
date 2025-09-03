# SIS Module Hooks

app_name = "erp"
app_title = "ERP"
app_publisher = "Frappe Technologies"
app_description = "ERP"
app_email = "info@frappe.io"
app_license = "MIT"


# Permission query for SIS module
permission_query_conditions = {
    "SIS Photo": "erp.sis.utils.permission_query.get_permission_query_conditions",
    "SIS Campus": "erp.sis.utils.permission_query.get_permission_query_conditions",
    "SIS Class": "erp.sis.utils.permission_query.get_permission_query_conditions",
    "SIS School Year": "erp.sis.utils.permission_query.get_permission_query_conditions",
}

# DocType hooks
doc_events = {
    "User": {
        "after_insert": "erp.sis.utils.campus_permissions.create_user_campus_preference",
    }
}
