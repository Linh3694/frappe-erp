"""
Parent Portal — API hồ sơ Guardian.

Endpoint trong file này chỉ thao tác trên Guardian đang đăng nhập, không nhận
guardian_id từ client để tránh cập nhật nhầm hồ sơ phụ huynh khác.
"""

from __future__ import annotations

import io
import os
import re
import uuid

import frappe
from PIL import Image, ImageOps

from erp.api.parent_portal.otp_auth import get_parent_portal_user_from_request
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    success_response,
    validation_error_response,
)


_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic"}
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024
_AVATAR_SIZE = 512
_UPLOAD_FOLDER = "GuardianAvatar"


def _resolve_current_guardian_name() -> str | None:
    """Lấy document name của CRM Guardian từ Parent Portal JWT/session."""

    user_email = get_parent_portal_user_from_request()
    if not user_email or user_email == "Guest":
        return None
    if "@parent.wellspring.edu.vn" not in user_email:
        return None

    guardian_id = user_email.split("@", 1)[0]
    return frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")


def _get_upload_file():
    files = getattr(frappe.request, "files", None)
    if not files:
        return None
    return files.get("image") or files.get("guardian_image") or files.get("avatar")


def _read_file_content(file_obj) -> bytes:
    if hasattr(file_obj, "stream"):
        file_obj.stream.seek(0)
        return file_obj.stream.read()
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    return file_obj.read()


def _extension_from_filename(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def _safe_guardian_id(guardian_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", guardian_id or "guardian").strip("_") or "guardian"


def _normalize_guardian_image(content: bytes) -> tuple[bytes, dict]:
    """Chuẩn hoá ảnh về WebP vuông để UI avatar hiển thị ổn định."""

    original_size = len(content)
    image = Image.open(io.BytesIO(content))
    image = ImageOps.exif_transpose(image)

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")

    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((_AVATAR_SIZE, _AVATAR_SIZE), Image.Resampling.LANCZOS)

    output = io.BytesIO()
    image.save(output, format="WEBP", quality=88, method=6)
    normalized = output.getvalue()

    return normalized, {
        "original_size": original_size,
        "compressed_size": len(normalized),
        "width": _AVATAR_SIZE,
        "height": _AVATAR_SIZE,
        "format": "WEBP",
    }


def _remove_previous_guardian_image(file_url: str | None) -> None:
    if not file_url or not file_url.startswith(f"/files/{_UPLOAD_FOLDER}/"):
        return
    file_path = frappe.get_site_path("public", file_url.lstrip("/"))
    if os.path.exists(file_path):
        os.remove(file_path)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def upload_guardian_image():
    """Upload và chuẩn hoá ảnh đại diện cho Guardian đang đăng nhập."""

    logs: list[str] = []
    try:
        guardian_name = _resolve_current_guardian_name()
        if not guardian_name:
            return forbidden_response(
                message="Vui lòng đăng nhập để cập nhật ảnh phụ huynh",
                code="PARENT_NOT_FOUND",
            )

        file_obj = _get_upload_file()
        if not file_obj:
            return validation_error_response(
                "Thiếu file ảnh",
                {"image": ["File ảnh là bắt buộc"]},
                code="MISSING_IMAGE",
            )

        filename = getattr(file_obj, "filename", "") or "guardian_image"
        extension = _extension_from_filename(filename)
        if extension not in _ALLOWED_EXTENSIONS:
            return validation_error_response(
                "Loại file không hợp lệ",
                {"image": ["Chỉ chấp nhận JPG, PNG, WebP hoặc HEIC"]},
                code="INVALID_IMAGE_TYPE",
            )

        content = _read_file_content(file_obj)
        if not content:
            return validation_error_response(
                "File ảnh rỗng",
                {"image": ["File ảnh không có dữ liệu"]},
                code="EMPTY_IMAGE",
            )
        if len(content) > _MAX_UPLOAD_SIZE:
            return validation_error_response(
                "Kích thước ảnh quá lớn",
                {"image": ["Ảnh tối đa 10MB"]},
                code="IMAGE_TOO_LARGE",
            )

        try:
            normalized_content, image_info = _normalize_guardian_image(content)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Parent Portal Guardian Image Normalize")
            return validation_error_response(
                "Không đọc được file ảnh",
                {"image": ["Vui lòng chọn ảnh hợp lệ"]},
                code="INVALID_IMAGE_CONTENT",
            )

        guardian = frappe.get_doc("CRM Guardian", guardian_name)
        safe_guardian_id = _safe_guardian_id(getattr(guardian, "guardian_id", guardian.name))
        final_filename = f"guardian_{safe_guardian_id}_{uuid.uuid4().hex}.webp"

        upload_dir = frappe.get_site_path("public", "files", _UPLOAD_FOLDER)
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, final_filename)
        with open(file_path, "wb") as f:
            f.write(normalized_content)

        previous_url = getattr(guardian, "guardian_image", None)
        image_url = f"/files/{_UPLOAD_FOLDER}/{final_filename}"
        guardian.guardian_image = image_url
        guardian.flags.ignore_permissions = True
        guardian.save(ignore_permissions=True)
        frappe.db.commit()
        _remove_previous_guardian_image(previous_url)

        logs.append(f"Updated guardian image for {guardian.name}")
        return success_response(
            data={
                "guardian_image": image_url,
                "image_url": image_url,
                "compression_info": image_info,
            },
            message="Cập nhật ảnh phụ huynh thành công",
            logs=logs,
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Parent Portal Guardian Image Upload")
        return error_response(
            message=f"Lỗi khi cập nhật ảnh phụ huynh: {str(e)}",
            code="GUARDIAN_IMAGE_UPLOAD_ERROR",
            logs=logs,
        )
