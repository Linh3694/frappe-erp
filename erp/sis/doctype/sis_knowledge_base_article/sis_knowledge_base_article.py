# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# Maximum number of version snapshots retained per article
MAX_VERSIONS = 2

# Fields that make up a content snapshot
SNAPSHOT_FIELDS = (
    "title_vn",
    "title_en",
    "summary_vn",
    "summary_en",
    "content_vn",
    "content_en",
)


class SISKnowledgeBaseArticle(Document):
    def before_save(self):
        """Set audit fields and recompute the unpublished-changes flag."""
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name") or current_user

        if not self.created_at:
            self.created_at = frappe.utils.now()
        if not self.created_by:
            self.created_by = teacher

        self.updated_at = frappe.utils.now()
        self.updated_by = teacher

        if self.slug:
            self.slug = self.slug.strip().lower()

        self._recompute_unpublished_changes()

    def validate(self):
        """Slug must be unique within (campus, category)."""
        if self.slug and self.category and self.campus_id:
            existing = frappe.db.exists("SIS Knowledge Base Article", {
                "slug": self.slug,
                "category": self.category,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing:
                frappe.throw(
                    f"Slug '{self.slug}' already exists in this category for this campus"
                )

    # ------------------------------------------------------------------
    # Version helpers
    # ------------------------------------------------------------------
    def get_live_version(self):
        """Return the child version row currently marked live, or None."""
        for v in (self.versions or []):
            if v.is_live:
                return v
        return None

    def _recompute_unpublished_changes(self):
        live = self.get_live_version()
        if not live:
            # Never published: dirty if there is any content to publish
            has_content = bool((self.content_vn or "").strip() or (self.content_en or "").strip())
            self.has_unpublished_changes = 1 if has_content else 0
            return
        dirty = any(
            (getattr(self, f) or "") != (getattr(live, f) or "")
            for f in SNAPSHOT_FIELDS
        )
        self.has_unpublished_changes = 1 if dirty else 0

    def publish(self, note=None):
        """Snapshot the current draft into a new live version and publish."""
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name") or current_user

        next_version_no = 1 + max([v.version_no or 0 for v in (self.versions or [])], default=0)

        # Demote any existing live version
        for v in (self.versions or []):
            v.is_live = 0

        snapshot = {f: (getattr(self, f) or "") for f in SNAPSHOT_FIELDS}
        snapshot.update({
            "version_no": next_version_no,
            "is_live": 1,
            "note": note,
            "snapshot_at": frappe.utils.now(),
            "snapshot_by": teacher,
        })
        self.append("versions", snapshot)

        self.status = "published"
        self.published_version = next_version_no
        self.published_at = frappe.utils.now()
        self.published_by = teacher

        self._prune_versions()
        self.save(ignore_permissions=True)

    def unpublish(self):
        """Take the article offline; keep version history intact."""
        for v in (self.versions or []):
            v.is_live = 0
        self.status = "draft"
        self.published_version = None
        self.published_at = None
        self.published_by = None
        self.save(ignore_permissions=True)

    def restore_version(self, version_no):
        """Copy a stored version's content back into the editable draft."""
        target = None
        for v in (self.versions or []):
            if v.version_no == int(version_no):
                target = v
                break
        if not target:
            frappe.throw(f"Version {version_no} not found")
        for f in SNAPSHOT_FIELDS:
            setattr(self, f, getattr(target, f))
        self.save(ignore_permissions=True)

    def _prune_versions(self):
        """Keep only the newest MAX_VERSIONS snapshots; never drop the live one."""
        versions = sorted(self.versions or [], key=lambda v: v.version_no or 0, reverse=True)
        if len(versions) <= MAX_VERSIONS:
            return
        keep = set()
        for v in versions[:MAX_VERSIONS]:
            keep.add(v.name)
        live = self.get_live_version()
        if live:
            keep.add(live.name)
        self.versions = [v for v in self.versions if v.name in keep]
