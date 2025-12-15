"""
Public API endpoints cho Library - Không yêu cầu authentication
Dành cho trang public library website
"""

import json
from typing import List, Dict, Any
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import getdate
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    validation_error_response,
)

# DocType constants
TITLE_DTYPE = "SIS Library Title"
EVENT_DTYPE = "SIS Library Event"
EVENT_DAY_DTYPE = "SIS Library Event Day"


def _create_slug(title: str) -> str:
    """Tạo slug từ tiêu đề để match với frontend."""
    import re
    # Convert Vietnamese characters
    replacements = {
        'á': 'a', 'à': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ắ': 'a', 'ằ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ấ': 'a', 'ầ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'é': 'e', 'è': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ế': 'e', 'ề': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'í': 'i', 'ì': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ó': 'o', 'ò': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ố': 'o', 'ồ': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ớ': 'o', 'ờ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ú': 'u', 'ù': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ứ': 'u', 'ừ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ý': 'y', 'ỳ': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
        'đ': 'd',
    }
    
    slug = title.lower()
    for vn, en in replacements.items():
        slug = slug.replace(vn, en)
    
    # Remove special characters, keep only alphanumeric and spaces
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    # Replace spaces with hyphens
    slug = re.sub(r'\s+', '-', slug)
    # Replace multiple hyphens with single hyphen
    slug = re.sub(r'-+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    
    return slug


def _transform_title_to_public(doc) -> Dict[str, Any]:
    """Transform title document sang format cho public API."""
    # Parse authors từ JSON string
    authors = []
    if doc.authors:
        try:
            authors = json.loads(doc.authors) if isinstance(doc.authors, str) else doc.authors
        except:
            authors = []
    
    # Parse description, introduction, audio_book
    description = {}
    if doc.description:
        try:
            description = json.loads(doc.description) if isinstance(doc.description, str) else doc.description
        except:
            description = {}
    
    introduction = {}
    if doc.introduction:
        try:
            introduction = json.loads(doc.introduction) if isinstance(doc.introduction, str) else doc.introduction
        except:
            introduction = {}
    
    audio_book = {}
    if hasattr(doc, 'audio_book') and doc.audio_book:
        try:
            audio_book = json.loads(doc.audio_book) if isinstance(doc.audio_book, str) else doc.audio_book
        except:
            audio_book = {}
    
    return {
        "_id": doc.name,
        "libraryId": doc.name,
        "libraryCode": doc.library_code or "",
        "title": doc.title,
        "libraryTitle": doc.title,
        "authors": authors,
        "category": doc.category or "",
        "coverImage": doc.cover_image or "",
        "documentType": doc.document_type or "",
        "seriesName": doc.series_name or "",
        "language": doc.language or "Tiếng Việt",
        "isNewBook": bool(doc.is_new_book),
        "isFeaturedBook": bool(doc.is_featured_book),
        "isAudioBook": bool(doc.is_audio_book),
        "description": description,
        "introduction": introduction,
        "audioBook": audio_book,
        "publishYear": getattr(doc, 'publish_year', None),
        "createdAt": str(doc.creation) if hasattr(doc, 'creation') else None,
        "modifiedAt": str(doc.modified) if hasattr(doc, 'modified') else None,
        "borrowCount": 0,  # TODO: Count from copies if needed
        "rating": 4,  # Default rating
    }


@frappe.whitelist(allow_guest=True)
def list_public_titles(limit: int = 20, page: int = 1):
    """
    Lấy danh sách tất cả đầu sách (public).
    URL: /api/method/erp.api.erp_sis.library_view.list_public_titles
    """
    try:
        limit = int(limit)
        page = int(page)
        
        titles = frappe.get_all(
            TITLE_DTYPE,
            fields=[
                "name",
                "title",
                "library_code",
                "authors",
                "category",
                "document_type",
                "series_name",
                "language",
                "is_new_book",
                "is_featured_book",
                "is_audio_book",
                "cover_image",
                "description",
                "introduction",
            ],
            limit_start=(page - 1) * limit,
            limit=limit,
            order_by="modified desc",
        )
        
        # Transform data
        result = []
        for title_dict in titles:
            # Get full doc để có đủ fields
            try:
                doc = frappe.get_cached_doc(TITLE_DTYPE, title_dict.name)
                result.append(_transform_title_to_public(doc))
            except:
                # Fallback nếu không get được doc
                result.append({
                    "_id": title_dict.name,
                    "libraryId": title_dict.name,
                    "libraryCode": title_dict.library_code or "",
                    "title": title_dict.title,
                    "authors": json.loads(title_dict.authors) if title_dict.authors else [],
                    "category": title_dict.category or "",
                    "coverImage": title_dict.cover_image or "",
                    "documentType": title_dict.document_type or "",
                    "seriesName": title_dict.series_name or "",
                    "language": title_dict.language or "Tiếng Việt",
                    "isNewBook": bool(title_dict.is_new_book),
                    "isFeaturedBook": bool(title_dict.is_featured_book),
                    "isAudioBook": bool(title_dict.is_audio_book),
                    "borrowCount": 0,
                    "rating": 4,
                })
        
        return success_response(data=result, message="Fetched public titles")
    except Exception as ex:
        frappe.log_error(f"list_public_titles failed: {ex}")
        return error_response(message="Không lấy được danh sách sách", code="PUBLIC_TITLES_ERROR")


@frappe.whitelist(allow_guest=True)
def get_public_title_by_slug(slug: str):
    """
    Lấy chi tiết sách theo slug.
    URL: /api/method/erp.api.erp_sis.library_view.get_public_title_by_slug
    """
    if not slug:
        return validation_error_response(message="Thiếu slug", errors={"slug": ["required"]})
    
    try:
        # Lấy tất cả titles và tìm theo slug
        titles = frappe.get_all(
            TITLE_DTYPE,
            fields=["name", "title"],
        )
        
        # Tìm title có slug khớp
        matched_title = None
        for title_dict in titles:
            if _create_slug(title_dict.title) == slug:
                matched_title = title_dict.name
                break
        
        if not matched_title:
            return error_response(message="Không tìm thấy sách", code="TITLE_NOT_FOUND")
        
        # Lấy full document
        doc = frappe.get_doc(TITLE_DTYPE, matched_title)
        result = _transform_title_to_public(doc)
        
        return success_response(data=result, message="Fetched title detail")
    except Exception as ex:
        frappe.log_error(f"get_public_title_by_slug failed: {ex}")
        return error_response(message="Không lấy được chi tiết sách", code="TITLE_DETAIL_ERROR")


@frappe.whitelist(allow_guest=True)
def list_featured_titles(limit: int = 4):
    """
    Lấy danh sách sách nổi bật.
    URL: /api/method/erp.api.erp_sis.library_view.list_featured_titles
    """
    try:
        limit = int(limit)
        
        titles = frappe.get_all(
            TITLE_DTYPE,
            filters={"is_featured_book": 1},
            fields=[
                "name",
                "title",
                "library_code",
                "authors",
                "category",
                "document_type",
                "series_name",
                "language",
                "is_new_book",
                "is_featured_book",
                "is_audio_book",
                "cover_image",
            ],
            limit=limit,
            order_by="modified desc",
        )
        
        # Transform data
        result = []
        for title_dict in titles:
            try:
                doc = frappe.get_cached_doc(TITLE_DTYPE, title_dict.name)
                result.append(_transform_title_to_public(doc))
            except:
                # Fallback
                result.append({
                    "_id": title_dict.name,
                    "libraryId": title_dict.name,
                    "libraryCode": title_dict.library_code or "",
                    "title": title_dict.title,
                    "authors": json.loads(title_dict.authors) if title_dict.authors else [],
                    "category": title_dict.category or "",
                    "coverImage": title_dict.cover_image or "",
                    "isNewBook": bool(title_dict.is_new_book),
                    "isFeaturedBook": True,
                    "isAudioBook": bool(title_dict.is_audio_book),
                    "borrowCount": 0,
                    "rating": 4,
                })
        
        return success_response(data=result, message="Fetched featured titles")
    except Exception as ex:
        frappe.log_error(f"list_featured_titles failed: {ex}")
        return error_response(message="Không lấy được sách nổi bật", code="FEATURED_TITLES_ERROR")


@frappe.whitelist(allow_guest=True)
def list_new_titles(limit: int = 4):
    """
    Lấy danh sách sách mới.
    URL: /api/method/erp.api.erp_sis.library_view.list_new_titles
    """
    try:
        limit = int(limit)
        
        titles = frappe.get_all(
            TITLE_DTYPE,
            filters={"is_new_book": 1},
            fields=[
                "name",
                "title",
                "library_code",
                "authors",
                "category",
                "document_type",
                "series_name",
                "language",
                "is_new_book",
                "is_featured_book",
                "is_audio_book",
                "cover_image",
            ],
            limit=limit,
            order_by="modified desc",
        )
        
        # Transform data
        result = []
        for title_dict in titles:
            try:
                doc = frappe.get_cached_doc(TITLE_DTYPE, title_dict.name)
                result.append(_transform_title_to_public(doc))
            except:
                result.append({
                    "_id": title_dict.name,
                    "libraryId": title_dict.name,
                    "libraryCode": title_dict.library_code or "",
                    "title": title_dict.title,
                    "authors": json.loads(title_dict.authors) if title_dict.authors else [],
                    "category": title_dict.category or "",
                    "coverImage": title_dict.cover_image or "",
                    "isNewBook": True,
                    "isFeaturedBook": bool(title_dict.is_featured_book),
                    "isAudioBook": bool(title_dict.is_audio_book),
                    "borrowCount": 0,
                    "rating": 4,
                })
        
        return success_response(data=result, message="Fetched new titles")
    except Exception as ex:
        frappe.log_error(f"list_new_titles failed: {ex}")
        return error_response(message="Không lấy được sách mới", code="NEW_TITLES_ERROR")


@frappe.whitelist(allow_guest=True)
def list_audio_titles(limit: int = 4):
    """
    Lấy danh sách sách nói.
    URL: /api/method/erp.api.erp_sis.library_view.list_audio_titles
    """
    try:
        limit = int(limit)
        
        titles = frappe.get_all(
            TITLE_DTYPE,
            filters={"is_audio_book": 1},
            fields=[
                "name",
                "title",
                "library_code",
                "authors",
                "category",
                "document_type",
                "series_name",
                "language",
                "is_new_book",
                "is_featured_book",
                "is_audio_book",
                "cover_image",
            ],
            limit=limit,
            order_by="modified desc",
        )
        
        # Transform data
        result = []
        for title_dict in titles:
            try:
                doc = frappe.get_cached_doc(TITLE_DTYPE, title_dict.name)
                result.append(_transform_title_to_public(doc))
            except:
                result.append({
                    "_id": title_dict.name,
                    "libraryId": title_dict.name,
                    "libraryCode": title_dict.library_code or "",
                    "title": title_dict.title,
                    "authors": json.loads(title_dict.authors) if title_dict.authors else [],
                    "category": title_dict.category or "",
                    "coverImage": title_dict.cover_image or "",
                    "isNewBook": bool(title_dict.is_new_book),
                    "isFeaturedBook": bool(title_dict.is_featured_book),
                    "isAudioBook": True,
                    "borrowCount": 0,
                    "rating": 4,
                })
        
        return success_response(data=result, message="Fetched audio titles")
    except Exception as ex:
        frappe.log_error(f"list_audio_titles failed: {ex}")
        return error_response(message="Không lấy được sách nói", code="AUDIO_TITLES_ERROR")


@frappe.whitelist(allow_guest=True)
def list_related_titles(category: str = "", limit: int = 10):
    """
    Lấy danh sách sách liên quan theo category.
    URL: /api/method/erp.api.erp_sis.library_view.list_related_titles
    """
    try:
        limit = int(limit)
        
        filters = {}
        if category:
            filters["category"] = ["like", f"%{category}%"]
        
        titles = frappe.get_all(
            TITLE_DTYPE,
            filters=filters,
            fields=[
                "name",
                "title",
                "library_code",
                "authors",
                "category",
                "document_type",
                "series_name",
                "language",
                "is_new_book",
                "is_featured_book",
                "is_audio_book",
                "cover_image",
            ],
            limit=limit,
            order_by="modified desc",
        )
        
        # Transform data
        result = []
        for title_dict in titles:
            try:
                doc = frappe.get_cached_doc(TITLE_DTYPE, title_dict.name)
                result.append(_transform_title_to_public(doc))
            except:
                result.append({
                    "_id": title_dict.name,
                    "libraryId": title_dict.name,
                    "libraryCode": title_dict.library_code or "",
                    "title": title_dict.title,
                    "authors": json.loads(title_dict.authors) if title_dict.authors else [],
                    "category": title_dict.category or "",
                    "coverImage": title_dict.cover_image or "",
                    "isNewBook": bool(title_dict.is_new_book),
                    "isFeaturedBook": bool(title_dict.is_featured_book),
                    "isAudioBook": bool(title_dict.is_audio_book),
                    "borrowCount": 0,
                    "rating": 4,
                })
        
        return success_response(data=result, message="Fetched related titles")
    except Exception as ex:
        frappe.log_error(f"list_related_titles failed: {ex}")
        return error_response(message="Không lấy được sách liên quan", code="RELATED_TITLES_ERROR")


@frappe.whitelist(allow_guest=True)
def list_public_events(page: int = 1, limit: int = 20):
    """
    Lấy danh sách sự kiện thư viện (public).
    Chỉ lấy events có days published.
    URL: /api/method/erp.api.erp_sis.library_view.list_public_events
    """
    try:
        page = int(page)
        limit = int(limit)
        
        events = frappe.get_all(
            EVENT_DTYPE,
            fields=[
                "name",
                "title",
                "description",
                "start_date",
                "creation",
                "modified",
            ],
            limit_start=(page - 1) * limit,
            limit=limit,
            order_by="start_date desc",
        )
        
        result = []
        for event_dict in events:
            # Get days cho event
            days = frappe.get_all(
                EVENT_DAY_DTYPE,
                filters={
                    "parent": event_dict.name,
                    "is_published": 1,
                },
                fields=[
                    "name",
                    "day_number",
                    "date",
                    "title",
                    "description",
                    "is_published",
                    "images",
                ],
                order_by="day_number asc",
            )
            
            # Parse images cho mỗi day
            for day in days:
                if day.get("images"):
                    try:
                        day["images"] = json.loads(day["images"])
                    except:
                        day["images"] = []
                else:
                    day["images"] = []
            
            # Only include events có ít nhất 1 day published và có images
            has_images = False
            for day in days:
                if day.get("images") and len(day["images"]) > 0:
                    has_images = True
                    break
            
            if days and has_images:
                result.append({
                    "_id": event_dict.name,
                    "title": event_dict.title,
                    "description": event_dict.description or "",
                    "date": event_dict.start_date,
                    "days": days,
                    "images": [],  # Placeholder - frontend sẽ gom từ days
                    "isPublished": True,
                    "createdAt": str(event_dict.creation),
                    "updatedAt": str(event_dict.modified),
                })
        
        total = len(result)
        
        return success_response(
            data={
                "activities": result,
                "totalPages": (total // limit) + (1 if total % limit > 0 else 0),
                "currentPage": page,
                "total": total,
            },
            message="Fetched public events"
        )
    except Exception as ex:
        frappe.log_error(f"list_public_events failed: {ex}")
        return error_response(message="Không lấy được hoạt động", code="PUBLIC_EVENTS_ERROR")
