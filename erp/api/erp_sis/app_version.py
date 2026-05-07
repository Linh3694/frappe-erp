"""
API để quản lý version của mobile apps (WIS Staff Portal)
Dùng cho việc check update vì app là Unlisted trên App Store

================================================================================
Bench console — copy từng khối (không copy dòng ---)

Mở:  cd /path/to/frappe-bench && bench --site TEN_SITE console

--- [1] Sau khi sửa file app_version.py: reload module + test (không HTTP) ---
from importlib import reload
from erp.api.erp_sis import app_version as av
reload(av)

print(av.APP_VERSIONS)
print(av.get_latest_version("wis_staff", "ios"))
print(av.get_latest_version("wis_staff", "android"))
print(av.check_update("wis_staff", "ios", "1.5.10"))
print(av.check_update("wis_staff", "android", "1.5.10"))

--- [2] Gửi push “có bản cập nhật” tới mọi máy workspace-mobile (sau khi đã sửa version trong file + deploy) ---
# Cần session Administrator hoặc System Manager. Dry-run trước, bỏ dry_run để gửi thật.

frappe.set_user("Administrator")
from erp.api.erp_sis.app_version import APP_VERSIONS
from erp.api.erp_sis.mobile_push_notification import broadcast_workspace_app_update

ios = APP_VERSIONS["wis_staff"]["ios"]
android = APP_VERSIONS["wis_staff"]["android"]

print(
    broadcast_workspace_app_update(
        new_version=ios["version"],
        store_url_ios=ios["store_url"],
        store_url_android=android["store_url"],
        dry_run=1,
        sync=0,
    )
)
# Gửi thật: đổi dry_run=0 . Nhiều máy sẽ vào queue ``long`` (xem mobile_push_notification.py).

================================================================================
"""
import frappe
from frappe import _

# Cấu hình version cho các apps
# Cập nhật version ở đây mỗi khi release app mới
APP_VERSIONS = {
    "wis_staff": {
        "ios": {
            "version": "1.5.26",  # Version mới nhất trên App Store
            "min_version": "1.0.0",  # Version tối thiểu bắt buộc (force update nếu thấp hơn)
            "store_url": "https://apps.apple.com/app/id6746143732",
        },
        "android": {
            "version": "1.5.26",  # Version mới nhất trên Play Store
            "min_version": "1.0.0",  # Version tối thiểu bắt buộc
            "store_url": "https://play.google.com/store/apps/details?id=com.hailinh.n23.workspace",
        },
    }
}


@frappe.whitelist(allow_guest=True)
def get_latest_version(app_id: str = "wis_staff", platform: str = "ios"):
    """
    Lấy version mới nhất của app
    
    Args:
        app_id: ID của app (default: wis_staff)
        platform: ios hoặc android
    
    Returns:
        {
            "version": "1.2.27",
            "min_version": "1.0.0",
            "store_url": "https://...",
            "force_update": false
        }
    """
    try:
        if app_id not in APP_VERSIONS:
            return {
                "success": False,
                "error": f"App '{app_id}' not found"
            }
        
        platform = platform.lower()
        if platform not in ["ios", "android"]:
            return {
                "success": False,
                "error": f"Invalid platform '{platform}'. Must be 'ios' or 'android'"
            }
        
        app_config = APP_VERSIONS[app_id].get(platform)
        if not app_config:
            return {
                "success": False,
                "error": f"Platform '{platform}' not configured for app '{app_id}'"
            }
        
        return {
            "success": True,
            "version": app_config["version"],
            "min_version": app_config["min_version"],
            "store_url": app_config["store_url"],
        }
    
    except Exception as e:
        frappe.log_error(f"Error getting app version: {str(e)}", "App Version API")
        return {
            "success": False,
            "error": str(e)
        }


@frappe.whitelist(allow_guest=True)
def check_update(app_id: str = "wis_staff", platform: str = "ios", current_version: str = "0.0.0"):
    """
    Kiểm tra xem có cần update không
    
    Args:
        app_id: ID của app
        platform: ios hoặc android
        current_version: Version hiện tại của user
    
    Returns:
        {
            "needs_update": true/false,
            "force_update": true/false,
            "latest_version": "1.2.27",
            "store_url": "https://..."
        }
    """
    try:
        result = get_latest_version(app_id, platform)
        
        if not result.get("success"):
            return result
        
        latest_version = result["version"]
        min_version = result["min_version"]
        store_url = result["store_url"]
        
        # So sánh versions
        needs_update = _compare_versions(current_version, latest_version)
        force_update = _compare_versions(current_version, min_version)
        
        return {
            "success": True,
            "needs_update": needs_update,
            "force_update": force_update,
            "current_version": current_version,
            "latest_version": latest_version,
            "min_version": min_version,
            "store_url": store_url,
        }
    
    except Exception as e:
        frappe.log_error(f"Error checking update: {str(e)}", "App Version API")
        return {
            "success": False,
            "error": str(e)
        }


def _compare_versions(current: str, target: str) -> bool:
    """
    So sánh 2 versions
    Returns True nếu target > current (cần update)
    """
    def normalize(v):
        parts = v.split(".")
        return [int(p) for p in parts] + [0] * (3 - len(parts))
    
    try:
        current_parts = normalize(current)
        target_parts = normalize(target)
        
        for i in range(3):
            if target_parts[i] > current_parts[i]:
                return True
            if target_parts[i] < current_parts[i]:
                return False
        
        return False
    except:
        return False

