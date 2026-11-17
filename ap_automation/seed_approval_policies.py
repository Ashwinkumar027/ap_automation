import frappe

def seed():
    companies = frappe.get_all("Company", pluck="name")
    if not companies:
        companies = ["Aionion Capital Market Services Private Limited"]

    for company in companies:
        # Find or create department for company
        dept_name = frappe.db.get_value("Department", {"department_name": "Administration", "company": company}, "name")
        if not dept_name:
            dept_name = frappe.db.get_value("Department", {"department_name": "Administration"}, "name")
        if not dept_name:
            d = frappe.new_doc("Department")
            d.department_name = "Administration"
            d.company = company
            d.insert(ignore_permissions=True)
            dept_name = d.name

        # 1. Admin Department Policy: Assistant Manager -> Admin Manager -> Director
        existing_admin = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": company, "department": dept_name, "document_lane": "AP Purchase Order"},
            "name"
        )
        if not existing_admin:
            mat = frappe.new_doc("AP Approval Matrix")
            mat.company = company
            mat.department = dept_name
            mat.document_lane = "AP Purchase Order"
            mat.min_amount = 0
            mat.max_amount = 0
            mat.is_active = 1
            mat.append("approval_levels", {
                "level_number": 1,
                "level_name": "Assistant Manager Review",
                "approver_role": "Assistant Admin Manager",
                "action_type": "Full Approval"
            })
            mat.append("approval_levels", {
                "level_number": 2,
                "level_name": "Admin Manager Review",
                "approver_role": "Admin Manager",
                "action_type": "Full Approval"
            })
            mat.append("approval_levels", {
                "level_number": 3,
                "level_name": "Director Final Approval",
                "approver_role": "AP Director",
                "action_type": "Full Approval"
            })
            mat.insert(ignore_permissions=True)
            print(f"Created Admin PO policy for {company}: {mat.name}")
        else:
            print(f"Admin PO policy already exists for {company}: {existing_admin}")

        # 2. Default Company Policy for Other Departments: Manager -> Director
        existing_default = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": company, "department": ["in", ["", None]], "document_lane": "AP Purchase Order"},
            "name"
        )
        if not existing_default:
            mat2 = frappe.new_doc("AP Approval Matrix")
            mat2.company = company
            mat2.department = None
            mat2.document_lane = "AP Purchase Order"
            mat2.min_amount = 0
            mat2.max_amount = 0
            mat2.is_active = 1
            mat2.append("approval_levels", {
                "level_number": 1,
                "level_name": "Department Manager Review",
                "approver_role": "Admin Manager",
                "action_type": "Full Approval"
            })
            mat2.append("approval_levels", {
                "level_number": 2,
                "level_name": "Director Final Approval",
                "approver_role": "AP Director",
                "action_type": "Full Approval"
            })
            mat2.insert(ignore_permissions=True)
            print(f"Created Default PO policy for {company}: {mat2.name}")
        else:
            print(f"Default PO policy already exists for {company}: {existing_default}")

    frappe.db.commit()
