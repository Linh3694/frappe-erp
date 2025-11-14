"""
Script để disable standard Frappe webhooks cho User doctype
Chỉ dùng custom hook để gửi webhook với đầy đủ fields
"""

import frappe

def disable_standard_user_webhooks():
    """
    Disable tất cả standard Frappe webhooks cho User doctype
    vì đã có custom hook gửi đầy đủ fields
    """
    try:
        # Tìm tất cả webhooks cho User
        webhooks = frappe.get_all(
            "Webhook",
            filters={
                "webhook_doctype": "User",
                "enabled": 1
            },
            fields=["name", "request_url", "webhook_docevent"]
        )
        
        print(f"\n🔍 Found {len(webhooks)} active User webhooks:")
        for webhook in webhooks:
            print(f"  - {webhook.name}: {webhook.webhook_docevent} → {webhook.request_url}")
        
        if not webhooks:
            print("✅ No active User webhooks found")
            return
        
        # Disable chúng
        for webhook in webhooks:
            doc = frappe.get_doc("Webhook", webhook.name)
            doc.enabled = 0
            doc.save()
            print(f"  ✅ Disabled: {webhook.name}")
        
        frappe.db.commit()
        print(f"\n✅ Disabled {len(webhooks)} webhooks")
        print("💡 Custom hook in user_hooks.py sẽ xử lý việc gửi webhook với đầy đủ fields")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        frappe.db.rollback()


if __name__ == "__main__":
    frappe.init(site="mysite.local")
    frappe.connect()
    disable_standard_user_webhooks()
    frappe.destroy()






