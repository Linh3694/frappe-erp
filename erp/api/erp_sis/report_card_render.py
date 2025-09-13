import frappe
import json
from typing import Any, Dict, Optional

from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import success_response, error_response, validation_error_response, not_found_response, forbidden_response, single_item_response


def _campus() -> str:
    return get_current_campus_from_context() or "campus-1"


def _payload() -> Dict[str, Any]:
    data = {}
    if getattr(frappe, "request", None) and getattr(frappe.request, "data", None):
        try:
            raw = frappe.request.data
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            parsed = json.loads(body or "{}")
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = frappe.local.form_dict or {}
    else:
        data = frappe.local.form_dict or {}
    return data


def _load_form(form_id: str):
    form = frappe.get_doc("SIS Report Card Form", form_id)
    if form.campus_id != _campus():
        frappe.throw("Access denied", frappe.PermissionError)
    return form


def _load_report(report_id: str):
    report = frappe.get_doc("SIS Student Report Card", report_id)
    if report.campus_id != _campus():
        frappe.throw("Access denied", frappe.PermissionError)
    return report


def _build_html(form, report_data: Dict[str, Any]) -> str:
    # Minimal SSR: render background pages with absolutely positioned containers; FE can evolve later
    pages_html = []
    base_styles = """
      <style>
        @page { size: A4; margin: 0; }
        .rc-root { display: flex; justify-content: center; }
        .rc-root .page { position: relative; width: 210mm; max-width: 100%; height: 297mm; page-break-after: always; margin: 0 auto; }
        .rc-root .bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
        .rc-root .overlay { position: absolute; left: 0; top: 0; right: 0; bottom: 0; }
        .rc-root .text { position: absolute; font-family: Arial, sans-serif; font-size: 12pt; color: #000; }
        .rc-root .text.bold { font-weight: 600; }
        .rc-root .text.center { text-align: center; }
        .rc-root .text.right { text-align: right; }
        .rc-root table { border-collapse: collapse; width: 100%; }
        .rc-root .hidden { display: none; }
      </style>
    """
    for idx, p in enumerate(getattr(form, "pages", None) or []):
        bg_url = p.background_image or ""
        if bg_url and not str(bg_url).lower().startswith(("http://", "https://")):
            try:
                bg_url = frappe.utils.get_url(bg_url)
            except Exception:
                # fallback: ensure single leading slash
                if not str(bg_url).startswith('/'):
                    bg_url = f"/{bg_url}"
        # Placeholders: allow user to upload later; keep an empty background if not set
        layout = {}
        try:
            layout = json.loads(p.layout_json or "{}") if isinstance(p.layout_json, (str, bytes)) else (p.layout_json or {})
        except Exception:
            layout = {}

        overlay_items = []
        for el in (layout.get("elements") or []):
            if el.get("type") == "text":
                x = el.get("x", 0)
                y = el.get("y", 0)
                w = el.get("w", None)
                fs = el.get("style", {}).get("fontSize", 12)
                fw = el.get("style", {}).get("fontWeight", 400)
                ta = el.get("style", {}).get("textAlign", None)
                content = report_data
                for key in (el.get("binding") or "").split('.'):
                    if not key:
                        continue
                    content = content.get(key, "") if isinstance(content, dict) else ""
                classes = ["text"]
                if fw and int(fw) >= 600:
                    classes.append("bold")
                if ta == "center":
                    classes.append("center")
                if ta == "right":
                    classes.append("right")
                overlay_items.append(
                    f'<div class="{" ".join(classes)}" style="left:{x}%;top:{y}%;width:{(str(w)+"%") if w else "auto"};font-size:{fs}pt;">{frappe.utils.escape_html(content or "")}</div>'
                )
            # More types (table, matrix) can be added later
        # If form has no positioned elements, provide sensible defaults for page 1
        if not overlay_items and idx == 0:
            student = report_data.get("student", {}) if isinstance(report_data, dict) else {}
            klass = report_data.get("class", {}) if isinstance(report_data, dict) else {}
            subject_eval = report_data.get("subject_eval", {}) if isinstance(report_data, dict) else {}
            # Subject title guess
            subject_id = subject_eval.get("subject_id") if isinstance(subject_eval, dict) else None
            default_subject_title = subject_id or ""
            def _text(left, top, width, content, align=None, bold=False):
                classes = ["text"]
                if bold:
                    classes.append("bold")
                if align in ("center", "right"):
                    classes.append(align)
                overlay_items.append(
                    f'<div class="{' '.join(classes)}" style="left:{left}%;top:{top}%;width:{width}%;">{frappe.utils.escape_html(content or "")}</div>'
                )
            _text(20, 20, 40, student.get("full_name", ""))
            _text(25, 15, 18, student.get("code", ""), align="right")
            _text(30, 15, 25, student.get("dob", ""))
            _text(62, 20, 16, klass.get("short_title", ""))
            _text(62, 26, 20, student.get("gender", ""))
            _text(30, 32, 40, default_subject_title, bold=True)

        # Build small fragments first to avoid nested f-strings with escapes
        bg_tag = f'<img class="bg" src="{bg_url}" />' if bg_url else ''
        overlay_html = ''.join(overlay_items)
        page_html = (
            '<div class="page">'
            f'{bg_tag}'
            f'<div class="overlay">{overlay_html}</div>'
            '</div>'
        )
        pages_html.append(page_html)
    html = f"<div class=\"rc-root\">{base_styles}{''.join(pages_html)}</div>"
    return html


@frappe.whitelist(allow_guest=False)
def get_report_html(report_id: Optional[str] = None):
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id")
        if not report_id:
            return validation_error_response(message="report_id is required")
        report = _load_report(report_id)
        form = _load_form(report.form_id)
        data = json.loads(report.data_json or "{}")
        # Enrich data with student & class info for bindings
        try:
            crm = frappe.get_doc("CRM Student", report.student_id)
            data.setdefault("student", {})
            data["student"].update({
                "full_name": getattr(crm, "student_name", None) or getattr(crm, "full_name", None) or getattr(crm, "name", ""),
                "code": getattr(crm, "student_code", ""),
                "dob": getattr(crm, "dob", ""),
                "gender": getattr(crm, "gender", ""),
            })
        except Exception:
            pass
        try:
            klass = frappe.get_doc("SIS Class", report.class_id)
            data.setdefault("class", {})
            data["class"].update({
                "short_title": getattr(klass, "short_title", None) or getattr(klass, "title", None) or report.class_id,
            })
        except Exception:
            pass
        html = _build_html(form, data)
        return single_item_response({"html": html}, "HTML built")
    except frappe.DoesNotExistError:
        return not_found_response("Report not found")
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        frappe.log_error(f"Error get_report_html: {str(e)}")
        return error_response("Error building html")


@frappe.whitelist(allow_guest=False)
def get_report_pdf(report_id: Optional[str] = None, filename: Optional[str] = None):
    """Server-side render to PDF using Frappe's PDF engine."""
    try:
        report_id = report_id or (frappe.local.form_dict or {}).get("report_id") or ((frappe.request.args.get("report_id") if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) else None))
        if not report_id:
            payload = _payload()
            report_id = payload.get("report_id")
        if not report_id:
            return validation_error_response(message="report_id is required")
        report = _load_report(report_id)
        form = _load_form(report.form_id)
        data = json.loads(report.data_json or "{}")
        html = _build_html(form, data)

        from frappe.utils.pdf import get_pdf
        pdf_content = get_pdf(html)

        if not filename:
            filename = f"report-card-{report.student_id}-{report.semester_part}.pdf"

        frappe.local.response.filename = filename
        frappe.local.response.filecontent = pdf_content
        frappe.local.response.type = "download"
        return
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        frappe.log_error(f"Error get_report_pdf: {str(e)}")
        return error_response("Error rendering pdf")


