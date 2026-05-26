"""Library API package — facade re-export giữ tương thích erp.api.erp_sis.library.<func>."""

from ._constants import *  # noqa: F401,F403
from ._common import (  # noqa: F401
    _require_library_role,
    _validate_student,
    _get_json_payload,
    _parse_date,
    _import_excel_to_rows,
    _log_library_activity,
)
from .settings import get_library_settings, update_library_settings, _get_library_settings  # noqa: F401
from .summary import get_library_summary  # noqa: F401
from .lookups import (  # noqa: F401
    list_lookups,
    create_lookup,
    update_lookup,
    delete_lookup,
    import_lookups_excel,
)
from .titles import (  # noqa: F401
    list_titles,
    create_title,
    update_title,
    delete_title,
    import_titles_excel,
    upload_title_cover,
    bulk_upload_covers,
)
from .copies import (  # noqa: F401
    list_book_copies,
    create_book_copy,
    update_book_copy,
    delete_book_copy,
    import_copies_excel,
    borrow_multiple,
    return_copy,
    _get_copy_by_identifier,
    _sync_copy_after_return,
)
from .activities import list_activities  # noqa: F401
from .events import (  # noqa: F401
    list_events,
    get_event,
    create_event,
    update_event,
    delete_event,
    delete_event_day,
    toggle_day_published,
    upload_day_images,
    delete_day_image,
)
from .book_intros import (  # noqa: F401
    list_book_introductions,
    get_book_introduction,
    create_book_introduction,
    update_book_introduction,
    delete_book_introduction,
    toggle_introduction_published,
    upload_file_for_intro,
)
from .transactions import (  # noqa: F401
    create_transaction,
    list_transactions,
    get_transaction,
    return_transaction_items,
    sync_overdue_status,
    _get_user_employee_code,
    _create_transaction_internal,
    _return_items_internal,
    _find_active_transaction_for_copy,
)
from .fines import (  # noqa: F401
    list_fines,
    create_fine,
    update_fine,
    _create_fine_if_needed,
    _get_book_copy_cover_price,
    _resolve_return_fine_amount,
)
from .reports import (  # noqa: F401
    get_library_borrow_report,
    get_library_top_books,
    get_library_top_borrowers,
)
