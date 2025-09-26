import frappe
from typing import Dict, Any, List, Optional, Union


def success_response(
    data: Any = None,
    message: str = "Success",
    meta: Optional[Dict[str, Any]] = None,
    debug_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Chuẩn hoá success response theo format cố định"""
    response = {
        "success": True,
        "message": message
    }

    if data is not None:
        response["data"] = data

    if meta:
        response["meta"] = meta

    if debug_info:
        response["debug_info"] = debug_info

    return response


def error_response(
    message: str,
    errors: Optional[Dict[str, List[str]]] = None,
    code: Optional[str] = None,
    debug_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Chuẩn hoá error response theo format cố định"""
    response = {
        "success": False,
        "message": message
    }

    if errors:
        response["errors"] = errors

    if code:
        response["code"] = code

    if debug_info:
        if 'errors' not in response:
            response['errors'] = {}
        response['errors']['debug_info'] = debug_info

    return response


def paginated_response(
    data: List[Any],
    current_page: int,
    total_count: int,
    per_page: int,
    message: str = "Success"
) -> Dict[str, Any]:
    """Chuẩn hoá paginated response theo format cố định"""
    total_pages = (total_count + per_page - 1) // per_page

    return {
        "success": True,
        "message": message,
        "data": data,
        "pagination": {
            "current_page": current_page,
            "per_page": per_page,
            "total": total_count,
            "total_pages": total_pages
        }
    }


def single_item_response(
    data: Any,
    message: str = "Success"
) -> Dict[str, Any]:
    """Response cho single item (get by ID, create, update)"""
    return {
        "success": True,
        "message": message,
        "data": data
    }


def list_response(
    data: List[Any],
    message: str = "Success",
    meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Response cho list data không phân trang"""
    response = {
        "success": True,
        "message": message,
        "data": data
    }

    if meta:
        response["meta"] = meta

    return response


def validation_error_response(
    message: str,
    errors: Dict[str, List[str]],
    code: str = "VALIDATION_ERROR",
    debug_info: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Response cho validation errors"""
    response = error_response(
        message=message,
        errors=errors,
        code=code
    )
    if debug_info:
        if 'errors' not in response:
            response['errors'] = {}
        response['errors']['debug_info'] = debug_info
    return response


def not_found_response(
    message: str = "Resource not found",
    code: str = "NOT_FOUND"
) -> Dict[str, Any]:
    """Response cho resource not found"""
    return error_response(
        message=message,
        code=code
    )


def forbidden_response(
    message: str = "Access denied",
    code: str = "FORBIDDEN"
) -> Dict[str, Any]:
    """Response cho access denied"""
    return error_response(
        message=message,
        code=code
    )
