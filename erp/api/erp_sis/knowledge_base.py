# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt
"""API for the configurable Knowledge Base (in-app /docs).

Admin endpoints power the ops configuration UI (Người dùng & Hệ thống).
Public endpoints feed the read-only /docs reader with the live published content.
"""

import frappe
import json
import os
import uuid

from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)

ARTICLE_DT = "SIS Knowledge Base Article"
CATEGORY_DT = "SIS Knowledge Base Category"

SNAPSHOT_FIELDS = (
    "title_vn",
    "title_en",
    "summary_vn",
    "summary_en",
    "content_vn",
    "content_en",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _request_data():
    """Merge params from form_dict, multipart form, and JSON body.

    Works around the JWT middleware wiping ``form_dict`` and supports both
    multipart (with content images) and JSON request bodies.
    """
    data = {}
    try:
        data.update({k: v for k, v in dict(frappe.local.form_dict).items() if k != "cmd"})
    except Exception:
        pass

    try:
        if frappe.request and frappe.request.form:
            for key in frappe.request.form.keys():
                data[key] = frappe.request.form.get(key)
    except Exception:
        pass

    try:
        json_body = frappe.request.get_json(silent=True) if frappe.request else None
        if isinstance(json_body, dict):
            for key, value in json_body.items():
                if key != "cmd":
                    data[key] = value
    except Exception:
        pass

    return data


def _resolve_campus(data):
    campus_id = data.get("campus_id") or get_current_campus_from_context()
    if not campus_id:
        campus_id = frappe.db.get_value("SIS Campus", {}, "name")
    return campus_id


def _parse_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _category_payload(name):
    cat = frappe.get_doc(CATEGORY_DT, name)
    return {
        "name": cat.name,
        "code": cat.code,
        "title_vn": cat.title_vn,
        "title_en": cat.title_en,
        "parent_category": cat.parent_category,
        "icon": cat.icon,
        "display_order": cat.display_order or 0,
        "is_active": bool(cat.is_active),
    }


def _article_summary(name):
    a = frappe.get_doc(ARTICLE_DT, name)
    return {
        "name": a.name,
        "category": a.category,
        "slug": a.slug,
        "title_vn": a.title_vn,
        "title_en": a.title_en,
        "display_order": a.display_order or 0,
        "status": a.status,
        "has_unpublished_changes": bool(a.has_unpublished_changes),
        "published_version": a.published_version,
        "published_at": str(a.published_at) if a.published_at else None,
        "updated_at": str(a.updated_at) if a.updated_at else None,
    }


def _article_detail(name):
    a = frappe.get_doc(ARTICLE_DT, name)
    detail = _article_summary(name)
    detail.update({
        "summary_vn": a.summary_vn,
        "summary_en": a.summary_en,
        "content_vn": a.content_vn,
        "content_en": a.content_en,
        "versions": [
            {
                "version_no": v.version_no,
                "is_live": bool(v.is_live),
                "note": v.note,
                "snapshot_at": str(v.snapshot_at) if v.snapshot_at else None,
                "snapshot_by": v.snapshot_by,
            }
            for v in sorted(a.versions or [], key=lambda x: x.version_no or 0, reverse=True)
        ],
    })
    return detail


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=False)
def get_knowledge_base_categories():
    """List all categories for the current campus (flat; build tree on FE)."""
    try:
        data = _request_data()
        campus_id = _resolve_campus(data)
        names = frappe.get_all(
            CATEGORY_DT,
            filters={"campus_id": campus_id},
            order_by="display_order asc, title_vn asc",
            pluck="name",
        )
        return list_response([_category_payload(n) for n in names])
    except Exception as e:
        frappe.logger().error(f"[KB] get_categories error: {e}")
        return error_response(f"Failed to load categories: {e}", code="KB_CAT_LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def create_knowledge_base_category():
    try:
        data = _request_data()
        campus_id = _resolve_campus(data)
        code = str(data.get("code", "")).strip().lower()
        title_vn = str(data.get("title_vn", "")).strip()
        title_en = str(data.get("title_en", "")).strip()
        if not code or not title_vn or not title_en:
            return validation_error_response(
                "Code, title (VN) and title (EN) are required",
                {"code": ["Required"], "title_vn": ["Required"], "title_en": ["Required"]},
            )
        cat = frappe.get_doc({
            "doctype": CATEGORY_DT,
            "campus_id": campus_id,
            "code": code,
            "title_vn": title_vn,
            "title_en": title_en,
            "parent_category": data.get("parent_category") or None,
            "icon": data.get("icon") or None,
            "display_order": int(data.get("display_order") or 0),
            "is_active": 1 if data.get("is_active") in (None, "", "1", 1, True, "true") else 0,
        })
        cat.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_category_payload(cat.name), "Category created")
    except Exception as e:
        frappe.logger().error(f"[KB] create_category error: {e}")
        return error_response(f"Failed to create category: {e}", code="KB_CAT_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update_knowledge_base_category():
    try:
        data = _request_data()
        name = data.get("category_id") or data.get("name")
        if not name or not frappe.db.exists(CATEGORY_DT, name):
            return not_found_response("Category not found")
        cat = frappe.get_doc(CATEGORY_DT, name)
        for field in ("code", "title_vn", "title_en", "parent_category", "icon"):
            if field in data:
                setattr(cat, field, data.get(field) or None)
        if "display_order" in data:
            cat.display_order = int(data.get("display_order") or 0)
        if "is_active" in data:
            cat.is_active = 1 if _parse_bool(data.get("is_active")) else 0
        cat.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_category_payload(cat.name), "Category updated")
    except Exception as e:
        frappe.logger().error(f"[KB] update_category error: {e}")
        return error_response(f"Failed to update category: {e}", code="KB_CAT_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def delete_knowledge_base_category():
    try:
        data = _request_data()
        name = data.get("category_id") or data.get("name")
        if not name or not frappe.db.exists(CATEGORY_DT, name):
            return not_found_response("Category not found")
        if frappe.db.exists(ARTICLE_DT, {"category": name}):
            return error_response(
                "Cannot delete a category that still has articles", code="KB_CAT_NOT_EMPTY"
            )
        if frappe.db.exists(CATEGORY_DT, {"parent_category": name}):
            return error_response(
                "Cannot delete a category that has sub-categories", code="KB_CAT_HAS_CHILDREN"
            )
        frappe.delete_doc(CATEGORY_DT, name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Category deleted")
    except Exception as e:
        frappe.logger().error(f"[KB] delete_category error: {e}")
        return error_response(f"Failed to delete category: {e}", code="KB_CAT_DELETE_ERROR")


# ---------------------------------------------------------------------------
# Articles (admin)
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=False)
def get_knowledge_base_articles():
    """List articles (admin) with optional category/status filters."""
    try:
        data = _request_data()
        campus_id = _resolve_campus(data)
        filters = {"campus_id": campus_id}
        if data.get("category"):
            filters["category"] = data.get("category")
        if data.get("status") and data.get("status") != "all":
            filters["status"] = data.get("status")
        names = frappe.get_all(
            ARTICLE_DT,
            filters=filters,
            order_by="category asc, display_order asc, title_vn asc",
            pluck="name",
        )
        return list_response([_article_summary(n) for n in names])
    except Exception as e:
        frappe.logger().error(f"[KB] get_articles error: {e}")
        return error_response(f"Failed to load articles: {e}", code="KB_ART_LIST_ERROR")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_knowledge_base_article():
    try:
        data = _request_data()
        name = data.get("article_id") or data.get("name")
        if not name or not frappe.db.exists(ARTICLE_DT, name):
            return not_found_response("Article not found")
        return single_item_response(_article_detail(name))
    except Exception as e:
        frappe.logger().error(f"[KB] get_article error: {e}")
        return error_response(f"Failed to load article: {e}", code="KB_ART_GET_ERROR")


def _apply_article_fields(article, data):
    for field in ("category", "slug", "title_vn", "title_en",
                  "summary_vn", "summary_en", "content_vn", "content_en"):
        if field in data:
            setattr(article, field, data.get(field))
    if "display_order" in data:
        article.display_order = int(data.get("display_order") or 0)


@frappe.whitelist(allow_guest=False)
def create_knowledge_base_article():
    """Create an article as a draft. Pass publish=1 to publish immediately."""
    try:
        data = _request_data()
        campus_id = _resolve_campus(data)
        title_vn = str(data.get("title_vn", "")).strip()
        title_en = str(data.get("title_en", "")).strip()
        category = data.get("category")
        slug = str(data.get("slug", "")).strip().lower()
        errors = {}
        if not title_vn:
            errors["title_vn"] = ["Required"]
        if not title_en:
            errors["title_en"] = ["Required"]
        if not category:
            errors["category"] = ["Required"]
        if not slug:
            errors["slug"] = ["Required"]
        if errors:
            return validation_error_response("Missing required fields", errors)

        article = frappe.get_doc({
            "doctype": ARTICLE_DT,
            "campus_id": campus_id,
            "status": "draft",
        })
        _apply_article_fields(article, data)
        article.insert(ignore_permissions=True)

        if _parse_bool(data.get("publish")):
            article.publish(note=data.get("version_note"))
        frappe.db.commit()
        return single_item_response(_article_detail(article.name), "Article created")
    except Exception as e:
        frappe.logger().error(f"[KB] create_article error: {e}")
        return error_response(f"Failed to create article: {e}", code="KB_ART_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update_knowledge_base_article():
    """Save the working draft. Pass publish=1 to also publish."""
    try:
        data = _request_data()
        name = data.get("article_id") or data.get("name")
        if not name or not frappe.db.exists(ARTICLE_DT, name):
            return not_found_response("Article not found")
        article = frappe.get_doc(ARTICLE_DT, name)
        _apply_article_fields(article, data)
        article.save(ignore_permissions=True)

        if _parse_bool(data.get("publish")):
            article.publish(note=data.get("version_note"))
        frappe.db.commit()
        return single_item_response(_article_detail(article.name), "Article saved")
    except Exception as e:
        frappe.logger().error(f"[KB] update_article error: {e}")
        return error_response(f"Failed to update article: {e}", code="KB_ART_UPDATE_ERROR")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def publish_knowledge_base_article():
    try:
        data = _request_data()
        name = data.get("article_id") or data.get("name")
        if not name or not frappe.db.exists(ARTICLE_DT, name):
            return not_found_response("Article not found")
        article = frappe.get_doc(ARTICLE_DT, name)
        article.publish(note=data.get("version_note"))
        frappe.db.commit()
        return single_item_response(_article_detail(article.name), "Article published")
    except Exception as e:
        frappe.logger().error(f"[KB] publish_article error: {e}")
        return error_response(f"Failed to publish article: {e}", code="KB_ART_PUBLISH_ERROR")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def unpublish_knowledge_base_article():
    try:
        data = _request_data()
        name = data.get("article_id") or data.get("name")
        if not name or not frappe.db.exists(ARTICLE_DT, name):
            return not_found_response("Article not found")
        article = frappe.get_doc(ARTICLE_DT, name)
        article.unpublish()
        frappe.db.commit()
        return single_item_response(_article_detail(article.name), "Article unpublished")
    except Exception as e:
        frappe.logger().error(f"[KB] unpublish_article error: {e}")
        return error_response(f"Failed to unpublish article: {e}", code="KB_ART_UNPUBLISH_ERROR")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def restore_knowledge_base_version():
    try:
        data = _request_data()
        name = data.get("article_id") or data.get("name")
        version_no = data.get("version_no")
        if not name or not frappe.db.exists(ARTICLE_DT, name):
            return not_found_response("Article not found")
        if version_no is None:
            return validation_error_response("version_no is required", {"version_no": ["Required"]})
        article = frappe.get_doc(ARTICLE_DT, name)
        article.restore_version(version_no)
        frappe.db.commit()
        return single_item_response(_article_detail(article.name), "Version restored to draft")
    except Exception as e:
        frappe.logger().error(f"[KB] restore_version error: {e}")
        return error_response(f"Failed to restore version: {e}", code="KB_ART_RESTORE_ERROR")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def delete_knowledge_base_article():
    try:
        data = _request_data()
        name = data.get("article_id") or data.get("name")
        if not name or not frappe.db.exists(ARTICLE_DT, name):
            return not_found_response("Article not found")
        frappe.delete_doc(ARTICLE_DT, name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message="Article deleted")
    except Exception as e:
        frappe.logger().error(f"[KB] delete_article error: {e}")
        return error_response(f"Failed to delete article: {e}", code="KB_ART_DELETE_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def upload_kb_content_image():
    """Upload an inline content image; returns a public file URL."""
    try:
        files = frappe.request.files
        if not files or "image" not in files:
            return validation_error_response("No image provided", {"image": ["Required"]})
        uploaded = files["image"]
        allowed = ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/bmp", "image/webp"]
        if uploaded.content_type not in allowed:
            return validation_error_response(
                "Only image files are allowed", {"image": ["Invalid type"]}
            )
        content = uploaded.read()
        if len(content) > 10 * 1024 * 1024:
            return validation_error_response("Image must be < 10MB", {"image": ["Too large"]})
        ext = os.path.splitext(uploaded.filename or "")[1] or ".png"
        new_name = f"kb_{uuid.uuid4()}{ext}"
        upload_dir = frappe.get_site_path("public", "files", "Knowledge_Base")
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, new_name), "wb") as f:
            f.write(content)
        return single_item_response({"url": f"/files/Knowledge_Base/{new_name}"}, "Uploaded")
    except Exception as e:
        frappe.logger().error(f"[KB] upload_content_image error: {e}")
        return error_response(f"Failed to upload image: {e}", code="KB_IMG_UPLOAD_ERROR")


# ---------------------------------------------------------------------------
# Public (/docs reader)
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=False)
def get_published_knowledge_base_tree():
    """Return the category tree with published articles for the /docs reader."""
    try:
        data = _request_data()
        campus_id = _resolve_campus(data)

        categories = frappe.get_all(
            CATEGORY_DT,
            filters={"campus_id": campus_id, "is_active": 1},
            fields=["name", "code", "title_vn", "title_en", "parent_category",
                    "icon", "display_order"],
            order_by="display_order asc, title_vn asc",
        )
        articles = frappe.get_all(
            ARTICLE_DT,
            filters={"campus_id": campus_id, "status": "published"},
            fields=["name", "category", "slug", "title_vn", "title_en",
                    "display_order", "published_at"],
            order_by="display_order asc, title_vn asc",
        )

        articles_by_cat = {}
        for a in articles:
            articles_by_cat.setdefault(a.category, []).append({
                "name": a.name,
                "slug": a.slug,
                "title_vn": a.title_vn,
                "title_en": a.title_en,
                "order": a.display_order or 0,
                "published_at": str(a.published_at) if a.published_at else None,
            })

        by_name = {c.name: c for c in categories}

        def serialize(cat):
            return {
                "id": cat.name,
                "code": cat.code,
                "title_vn": cat.title_vn,
                "title_en": cat.title_en,
                "icon": cat.icon,
                "order": cat.display_order or 0,
                "articles": articles_by_cat.get(cat.name, []),
                "subCategories": [
                    serialize(child) for child in categories
                    if child.parent_category == cat.name
                ],
            }

        tree = [
            serialize(c) for c in categories
            if not c.parent_category or c.parent_category not in by_name
        ]
        return list_response(tree)
    except Exception as e:
        frappe.logger().error(f"[KB] get_published_tree error: {e}")
        return error_response(f"Failed to load knowledge base: {e}", code="KB_TREE_ERROR")


@frappe.whitelist(allow_guest=False)
def get_published_knowledge_base_article():
    """Return the live published content for a (category code, slug)."""
    try:
        data = _request_data()
        campus_id = _resolve_campus(data)
        category_code = data.get("category_code") or data.get("category")
        slug = data.get("slug")
        if not category_code or not slug:
            return validation_error_response(
                "category_code and slug are required",
                {"category_code": ["Required"], "slug": ["Required"]},
            )

        category_name = frappe.db.get_value(
            CATEGORY_DT, {"campus_id": campus_id, "code": category_code}, "name"
        )
        if not category_name:
            return not_found_response("Category not found")

        article_name = frappe.db.get_value(
            ARTICLE_DT,
            {"campus_id": campus_id, "category": category_name, "slug": slug, "status": "published"},
            "name",
        )
        if not article_name:
            return not_found_response("Article not found")

        article = frappe.get_doc(ARTICLE_DT, article_name)
        live = article.get_live_version()
        source = live if live else article
        return single_item_response({
            "name": article.name,
            "category_code": category_code,
            "slug": article.slug,
            "title_vn": source.title_vn,
            "title_en": source.title_en,
            "summary_vn": source.summary_vn,
            "summary_en": source.summary_en,
            "content_vn": source.content_vn,
            "content_en": source.content_en,
            "published_at": str(article.published_at) if article.published_at else None,
        })
    except Exception as e:
        frappe.logger().error(f"[KB] get_published_article error: {e}")
        return error_response(f"Failed to load article: {e}", code="KB_PUB_ART_ERROR")
