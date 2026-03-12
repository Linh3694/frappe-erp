import frappe
from frappe.model.document import Document
from frappe import _


def _clear_class_log_options_cache(doc):
    """Xóa cache get_class_log_options khi SIS Class Log Score thay đổi"""
    try:
        cache_key_all = "class_log_options:v2:all"
        frappe.cache().delete_key(cache_key_all)
        if doc.education_stage:
            cache_key_stage = f"class_log_options:v2:{doc.education_stage}"
            frappe.cache().delete_key(cache_key_stage)
        frappe.logger().info(f"✅ Cleared class_log_options cache after SIS Class Log Score change: {doc.name}")
    except Exception as e:
        frappe.logger().warning(f"Cache clear failed: {e}")


class SISClassLogScore(Document):
    def validate(self):
        """Đảm bảo title_vn và title_en là duy nhất trong cùng type + education_stage"""
        if not self.title_vn or not self.title_vn.strip():
            return

        title_vn = self.title_vn.strip()
        title_en = (self.title_en or "").strip()

        def _filters():
            f = [
                ["type", "=", self.type],
                ["is_active", "=", 1],
            ]
            if self.name:
                f.append(["name", "!=", self.name])
            if self.education_stage:
                f.append(["education_stage", "=", self.education_stage])
            else:
                f.append(["or", [["education_stage", "=", ""], ["education_stage", "is", "not set"]]])
            return f

        # Kiểm tra trùng title_vn
        f_vn = _filters() + [["title_vn", "=", title_vn]]
        if frappe.get_all("SIS Class Log Score", filters=f_vn, limit=1):
            frappe.throw(
                _("Tên (VI) \"{0}\" đã tồn tại trong cùng loại và cấp học").format(title_vn)
            )

        # Kiểm tra trùng title_en (chỉ khi có giá trị)
        if title_en:
            f_en = _filters() + [["title_en", "=", title_en]]
            if frappe.get_all("SIS Class Log Score", filters=f_en, limit=1):
                frappe.throw(
                    _("Tên (EN) \"{0}\" đã tồn tại trong cùng loại và cấp học").format(title_en)
                )

    def after_insert(self):
        _clear_class_log_options_cache(self)

    def on_update(self):
        _clear_class_log_options_cache(self)

    def on_trash(self):
        _clear_class_log_options_cache(self)


