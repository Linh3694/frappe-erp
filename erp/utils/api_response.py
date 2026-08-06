import frappe
from typing import Dict, Any, List, Optional, Union


def success_response(
    data: Any = None,
    message: str = "Success",
    meta: Optional[Dict[str, Any]] = None,
    debug_info: Optional[Dict[str, Any]] = None,
    logs: Optional[List[str]] = None
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

    # Add logs at top-level for frontend network access
    if logs:
        response["logs"] = logs

    if debug_info:
        response["debug_info"] = debug_info

    return response


def error_response(
    message: str,
    errors: Optional[Dict[str, List[str]]] = None,
    code: Optional[str] = None,
    debug_info: Optional[Dict[str, Any]] = None,
    logs: Optional[List[str]] = None,
    data: Any = None
) -> Dict[str, Any]:
    """Chuẩn hoá error response theo format cố định.

    `data` cho các lỗi vẫn cần trả payload kèm theo (vd bulk import: đếm số
    thành công/thất bại, link file lỗi). Bỏ trống thì key `data` không xuất
    hiện, giữ nguyên shape của các error response còn lại.
    """
    response = {
        "success": False,
        "message": message
    }

    if errors:
        response["errors"] = errors

    if data is not None:
        response["data"] = data

    if code:
        response["code"] = code

    # Add logs at top-level for frontend network access
    if logs:
        response["logs"] = logs

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
    message: str = "Success",
    logs: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Response cho single item (get by ID, create, update)"""
    response = {
        "success": True,
        "message": message,
        "data": data
    }
    
    # Add logs at top-level for frontend network access
    if logs:
        response["logs"] = logs
    
    return response


def list_response(
    data: List[Any],
    message: str = "Success",
    meta: Optional[Dict[str, Any]] = None,
    logs: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Response cho list data không phân trang"""
    response = {
        "success": True,
        "message": message,
        "data": data
    }

    if meta:
        response["meta"] = meta
    
    # Add logs at top-level for frontend network access
    if logs:
        response["logs"] = logs

    return response


def validation_error_response(
    message: str,
    errors: Optional[Dict[str, List[str]]] = None,
    code: str = "VALIDATION_ERROR",
    debug_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Response cho validation errors.

    `errors` là chi tiết lỗi theo từng field. Để trống khi chỉ cần một câu
    thông báo chung — phần lớn API trong repo gọi hàm này với mỗi `message`.
    """
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
    code: str = "NOT_FOUND",
    logs: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Response cho resource not found"""
    return error_response(
        message=message,
        code=code,
        logs=logs
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
