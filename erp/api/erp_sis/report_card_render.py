import frappe
import json
from typing import Any, Dict, Optional, List, Union

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


def _transform_data_for_bindings(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform report data to match frontend layout binding expectations.
    Converts subject_eval structure to subjects array for binding paths like subjects.0.*
    """
    if not isinstance(data, dict):
        return data
    
    transformed = data.copy()
    
    # Transform subject_eval to subjects array
    if "subject_eval" in data and isinstance(data["subject_eval"], dict):
        subject_eval = data["subject_eval"]
        frappe.logger().info(f"Found subject_eval: {json.dumps(subject_eval, indent=2, default=str)[:500]}...")
        
        # Create subjects array from subject_eval
        subjects = []
        
        # Method 1: If subject_eval has subject_id key
        subject_id = subject_eval.get("subject_id")
        if subject_id and subject_id in subject_eval:
            subject_data = subject_eval[subject_id]
            if isinstance(subject_data, dict):
                subjects.append({
                    "subject_id": subject_id,
                    "title_vn": subject_data.get("title_vn", subject_id),
                    "teacher_name": subject_data.get("teacher_name", ""),
                    "rubric": subject_data.get("rubric", {}),
                    "comments": subject_data.get("comments", []),
                    **subject_data
                })
        
        # Method 2: If subject_eval itself is the subject data
        elif subject_eval.get("title_vn") or subject_eval.get("rubric") or subject_eval.get("comments"):
            subjects.append({
                "subject_id": subject_id or "unknown",
                "title_vn": subject_eval.get("title_vn", subject_id or ""),
                "teacher_name": subject_eval.get("teacher_name", ""),
                "rubric": subject_eval.get("rubric", {}),
                "comments": subject_eval.get("comments", []),
                **subject_eval
            })
        
        # Method 3: Look for object keys that might be subject IDs
        else:
            for key, value in subject_eval.items():
                if key != "subject_id" and isinstance(value, dict):
                    if value.get("title_vn") or value.get("rubric") or value.get("comments"):
                        subjects.append({
                            "subject_id": key,
                            "title_vn": value.get("title_vn", key),
                            "teacher_name": value.get("teacher_name", ""),
                            "rubric": value.get("rubric", {}),
                            "comments": value.get("comments", []),
                            **value
                        })
        
        # If we found subjects, add to transformed data
        if subjects:
            transformed["subjects"] = subjects
            frappe.logger().info(f"Created subjects array with {len(subjects)} subjects")
            frappe.logger().info(f"First subject: {json.dumps(subjects[0], indent=2, default=str)[:500]}...")
        else:
            frappe.logger().warning("Could not create subjects array from subject_eval")
    
    return transformed


def _build_prim_vn_html(form, report_data: Dict[str, Any]) -> str:
    """
    Simplified PRIM_VN HTML builder for testing
    """
    try:
        frappe.logger().info("Building simplified PRIM_VN HTML")
        
        # Basic data extraction with safety checks
        student = report_data.get("student", {}) if isinstance(report_data, dict) else {}
        klass = report_data.get("class", {}) if isinstance(report_data, dict) else {} 
        report = report_data.get("report", {}) if isinstance(report_data, dict) else {}
        
        student_name = student.get("full_name", "") if isinstance(student, dict) else ""
        class_name = klass.get("short_title", "") if isinstance(klass, dict) else ""
        
        # Simple HTML output for testing
        base_styles = """
        <style>
            @page { size: A4; margin: 0; }
            .page { position: relative; width: 210mm; height: 297mm; background: white; }
            .header { text-align: center; font-weight: bold; margin: 20px 0; }
            .content { margin: 40px; }
        </style>
        """
        
        html_content = f"""
        <div>
            {base_styles}
            <div class="page">
                <div class="header">TRƯỜNG TIỂU HỌC WELLSPRING / WELLSPRING PRIMARY SCHOOL</div>
                <div class="content">
                    <p><strong>Học sinh/Student:</strong> {frappe.utils.escape_html(student_name)}</p>
                    <p><strong>Lớp/Class:</strong> {frappe.utils.escape_html(class_name)}</p>
                    <p><strong>Report Title:</strong> {frappe.utils.escape_html(str(report.get('title_vn', '')) if isinstance(report, dict) else '')}</p>
                    <p><strong>Debug:</strong> PRIM_VN renderer working - {len(str(report_data))} chars data</p>
                </div>
            </div>
        </div>
        """
        
        frappe.logger().info("PRIM_VN HTML built successfully with simplified version")
        return html_content
        
    except Exception as e:
        frappe.logger().error(f"Error in simplified PRIM_VN renderer: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        raise


# Commented out for simplified testing - can be restored later
"""
Temporarily commented out for simplified testing
"""

def _build_prim_vn_subject_page(bg_url: str, report: dict, student: dict, klass: dict, page_subjects: list, page_index: int) -> str:
    """Build a subject page for PRIM_VN (same as PrimaryVN.tsx A4Page for subjects)"""
    
    # Header (same as PrimaryVN.tsx lines 147-148)
    header_html = f"""
        <div class="positioned-text bold center" style="left:0%;top:10%;width:100%;">TRƯỜNG TIỂU HỌC WELLSPRING / WELLSPRING PRIMARY SCHOOL</div>
        <div class="positioned-text bold center" style="left:0%;top:12%;width:100%;">{report.get('title_vn', '') or report.get('title_en', '')}</div>
    """
    
    # Student info (same as PrimaryVN.tsx lines 151-162)
    student_info_html = f"""
        <div class="positioned-text" style="left:2%;top:15%;width:25%;">Học sinh/Student:</div>
        <div class="positioned-text bold" style="left:19%;top:15%;width:25%;">{student.get('full_name', '')}</div>
        <div class="positioned-text" style="left:2%;top:18%;width:25%;">Ngày sinh/DOB:</div>
        <div class="positioned-text bold" style="left:19%;top:18%;width:25%;">{student.get('dob', '')}</div>
        
        <div class="positioned-text" style="left:40%;top:15%;width:25%;">Lớp/Class:</div>
        <div class="positioned-text bold" style="left:50%;top:15%;width:25%;">{klass.get('short_title', '')}</div>
        <div class="positioned-text" style="left:40%;top:18%;width:25%;">Giới tính/Gender:</div>
        <div class="positioned-text bold" style="left:56%;top:18%;width:25%;">{student.get('gender', '')}</div>
        
        <div class="positioned-text" style="left:70%;top:15%;width:25%;">Mã học sinh/ID:</div>
        <div class="positioned-text bold" style="left:85%;top:15%;width:25%;">{student.get('code', '')}</div>
    """
    
    # Subject blocks content area (same as PrimaryVN.tsx lines 165-169)
    subjects_html = ""
    for i, subject in enumerate(page_subjects):
        subject_html = _build_prim_vn_subject_block(subject, i)
        subjects_html += subject_html
    
    # Background image
    bg_tag = f'<img class="page-bg" src="{bg_url}" />' if bg_url else ''
    
    page_html = f"""
        <div class="page">
            {bg_tag}
            {header_html}
            {student_info_html}
            <div style="position:absolute;left:12%;right:12%;top:24%;bottom:8%;display:flex;flex-direction:column;gap:16px;">
                {subjects_html}
            </div>
        </div>
    """
    
    return page_html


def _build_prim_vn_subject_block(subject: dict, index: int) -> str:
    """Build subject block HTML (same as PrimaryVN.tsx SubjectBlock component lines 97-129)"""
    
    # Subject header (same as PrimaryVN.tsx lines 112-115)
    subject_title = subject.get("title_vn", "")
    teacher_name = subject.get("teacher_name", "")
    
    # Test points (same as PrimaryVN.tsx lines 98-103)  
    test_titles = subject.get("test_point_titles", [])
    test_values = subject.get("test_point_inputs", [])
    
    test_pairs = []
    for i, title in enumerate(test_titles):
        value = test_values[i] if i < len(test_values) else ""
        if value:
            test_pairs.append(f"{title}: {value}")
        else:
            test_pairs.append(title)
    
    test_display = " / ".join(test_pairs) if test_pairs else (" / ".join(test_values) if test_values else "")
    
    # Matrix grid (same as PrimaryVN.tsx line 119)
    matrix_html = ""
    rubric = subject.get("rubric", {})
    if rubric:
        criteria = rubric.get("criteria_options", [])
        scales = rubric.get("scale_options", []) 
        selections = rubric.get("selections", [])
        matrix_html = _build_matrix_html(criteria, scales, selections)
    
    # Comments (same as PrimaryVN.tsx lines 121-127)
    comments_html = ""
    comments = subject.get("comments", [])[:2]  # Limit 2 comments
    for comment in comments:
        if isinstance(comment, dict):
            title = comment.get("title", "")
            value = comment.get("value", "")
            comments_html += f"""
                <div class="comment-block">
                    <div class="comment-title">{frappe.utils.escape_html(title)}</div>
                    <div class="comment-value">{frappe.utils.escape_html(value)}</div>
                </div>
            """
    
    # Test scores section
    test_html = ""
    if test_display:
        test_html = f'<div style="margin-bottom:6px;font-size:12pt;">Điểm bài kiểm tra/ Test score(s)/Level: {frappe.utils.escape_html(test_display)}</div>'
    
    subject_block_html = f"""
        <div class="subject-block">
            <div style="display:flex;justify-content:space-between;align-items:end;margin-bottom:6px;">
                <div style="font-weight:600;font-size:12pt;">Môn học/Subject: {frappe.utils.escape_html(subject_title)}</div>
                <div style="font-size:12pt;">Giáo viên/Teacher: {frappe.utils.escape_html(teacher_name)}</div>
            </div>
            {test_html}
            {matrix_html}
            <div style="margin-top:8px;">
                {comments_html}
            </div>
        </div>
    """
    
    return subject_block_html


def _build_prim_vn_homeroom_page(bg_url: str, report: dict, student: dict, klass: dict, teachers: str, homeroom_items: list, page_index: int) -> str:
    """Build homeroom page for PRIM_VN (same as PrimaryVN.tsx homeroom pages lines 173-209)"""
    
    # Same header and student info as subject pages
    header_html = f"""
        <div class="positioned-text bold center" style="left:0%;top:10%;width:100%;">TRƯỜNG TIỂU HỌC WELLSPRING / WELLSPRING PRIMARY SCHOOL</div>
        <div class="positioned-text bold center" style="left:0%;top:12%;width:100%;">{report.get('title_vn', '') or report.get('title_en', '')}</div>
    """
    
    student_info_html = f"""
        <div class="positioned-text" style="left:2%;top:15%;width:25%;">Học sinh/Student:</div>
        <div class="positioned-text bold" style="left:19%;top:15%;width:25%;">{student.get('full_name', '')}</div>
        <div class="positioned-text" style="left:2%;top:18%;width:25%;">Ngày sinh/DOB:</div>
        <div class="positioned-text bold" style="left:19%;top:18%;width:25%;">{student.get('dob', '')}</div>
        
        <div class="positioned-text" style="left:40%;top:15%;width:25%;">Lớp/Class:</div>
        <div class="positioned-text bold" style="left:50%;top:15%;width:25%;">{klass.get('short_title', '')}</div>
        <div class="positioned-text" style="left:40%;top:18%;width:25%;">Giới tính/Gender:</div>
        <div class="positioned-text bold" style="left:56%;top:18%;width:25%;">{student.get('gender', '')}</div>
        
        <div class="positioned-text" style="left:70%;top:15%;width:25%;">Mã học sinh/ID:</div>
        <div class="positioned-text bold" style="left:85%;top:15%;width:25%;">{student.get('code', '')}</div>
    """
    
    # Homeroom section titles (same as PrimaryVN.tsx lines 194-199)
    homeroom_header_html = f"""
        <div class="positioned-text bold" style="left:2%;top:22%;width:96%;">Giáo viên/Teachers: {frappe.utils.escape_html(teachers)}</div>
        <div class="positioned-text bold" style="left:2%;top:25%;width:96%;">Nhận xét của giáo viên chủ nhiệm/Homeroom Teacher's Comments</div>
    """
    
    # Homeroom comments (same as PrimaryVN.tsx lines 202-207)
    homeroom_html = ""
    for item in homeroom_items:
        if isinstance(item, dict):
            title = item.get("title", "")
            value = item.get("value", "")
            homeroom_html += f"""
                <div class="comment-block">
                    <div class="comment-title">{frappe.utils.escape_html(title)}</div>
                    <div class="comment-value">{frappe.utils.escape_html(value)}</div>
                </div>
            """
    
    # Background image
    bg_tag = f'<img class="page-bg" src="{bg_url}" />' if bg_url else ''
    
    page_html = f"""
        <div class="page">
            {bg_tag}
            {header_html}
            {student_info_html}
            {homeroom_header_html}
            <div style="position:absolute;left:12%;right:12%;top:30%;bottom:8%;display:flex;flex-direction:column;gap:16px;">
                {homeroom_html}
            </div>
        </div>
    """
    
    return page_html


def _build_matrix_html(criteria: list, scales: list, selections: list) -> str:
    """Build matrix grid HTML (same as PrimaryVN.tsx MatrixGrid component)"""
    if not criteria or not scales:
        return ""
    
    # Check if criteria/scale combination is selected
    def has_selection(c: str, s: str) -> bool:
        if not selections:
            return False
        for sel in selections:
            if isinstance(sel, dict) and sel.get("criteria") == c and sel.get("scale") == s:
                return True
        return False
    
    # Table header
    header_cells = '<th style="border:1px solid #999;padding:4px;width:28%;">Nội dung/Contents</th>'
    for scale in scales:
        header_cells += f'<th style="border:1px solid #999;padding:4px;">{frappe.utils.escape_html(str(scale))}</th>'
    
    # Table rows
    rows_html = ""
    for i, criterion in enumerate(criteria):
        cells = f'<td style="border:1px solid #999;padding:4px;">{i+1}. {frappe.utils.escape_html(str(criterion))}</td>'
        for scale in scales:
            mark = "x" if has_selection(criterion, scale) else ""
            cells += f'<td style="border:1px solid #999;padding:4px;text-align:center;">{mark}</td>'
        rows_html += f'<tr>{cells}</tr>'
    
    matrix_html = f"""
        <table class="matrix-grid">
            <thead>
                <tr style="background:#f6f6f6;">
                    <th style="border:1px solid #999;padding:4px;">STT/No</th>
                    {header_cells}
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    """
    
    return matrix_html


def _build_html(form, report_data: Dict[str, Any]) -> str:
    def _resolve_path(data: Any, path: Optional[str]) -> Any:
        if not path:
            return None
        cur: Any = data
        # Support dot path with numeric indexes, e.g. subjects.0.title_vn
        for raw_key in str(path).split('.'):
            key = raw_key.strip()
            if key == '':
                continue
            try:
                if isinstance(cur, list):
                    # numeric index into list
                    if key.isdigit():
                        idx = int(key)
                        cur = cur[idx] if 0 <= idx < len(cur) else None
                    else:
                        # cannot key into list with non-numeric key
                        cur = None
                elif isinstance(cur, dict):
                    cur = cur.get(key)
                else:
                    return None
            except Exception:
                return None
            if cur is None:
                return None
        return cur

    def _pct(v: Optional[Union[int, float]]) -> str:
        try:
            return f"{float(v)}%"
        except Exception:
            return "auto"

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
            # Debug logging
            frappe.logger().info(f"Page {idx} layout parsed: {layout}")
            frappe.logger().info(f"Elements count: {len(layout.get('elements', []))}")
        except Exception as e:
            frappe.logger().error(f"Error parsing layout_json: {e}")
            frappe.logger().info(f"Raw layout_json: {p.layout_json}")
            layout = {}

        overlay_items: List[str] = []
        for el in (layout.get("elements") or []):
            etype = el.get("type")
            frappe.logger().info(f"Processing element: type={etype}, data={el}")
            if etype == "text":
                x = el.get("x", 0)
                y = el.get("y", 0)
                w = el.get("w", None)
                style = el.get("style", {}) or {}
                fs = style.get("fontSize", 12)
                fw = style.get("fontWeight", 400)
                ta = style.get("textAlign", None)
                # Prefer explicit text, fallback to binding
                content_val = el.get("text")
                binding_path = el.get("binding")
                if binding_path:
                    bound = _resolve_path(report_data, binding_path)
                    frappe.logger().info(f"Binding {binding_path} resolved to: {bound}")
                    if bound is not None and not isinstance(bound, (dict, list)):
                        content_val = bound
                else:
                    frappe.logger().info(f"No binding for element, using text: {content_val}")
                classes = ["text"]
                try:
                    if fw and int(fw) >= 600:
                        classes.append("bold")
                except Exception:
                    pass
                if ta == "center":
                    classes.append("center")
                if ta == "right":
                    classes.append("right")
                safe_text = frappe.utils.escape_html(str(content_val or ""))
                width_str = f"{w}%" if w is not None else "auto"
                overlay_items.append(
                    f'<div class="{" ".join(classes)}" style="left:{x}%;top:{y}%;width:{width_str};font-size:{fs}pt;">{safe_text}</div>'
                )
            elif etype == "matrix":
                # Position container by left/right/top in percent (like FE preview)
                left = el.get("left", None)
                right = el.get("right", None)
                top = el.get("top", None)
                criteria = el.get("criteria") or _resolve_path(report_data, el.get("criteriaPath")) or []
                scales = el.get("scales") or _resolve_path(report_data, el.get("scalePath")) or []
                selections = el.get("selections") or _resolve_path(report_data, el.get("selectionsPath")) or []
                # Normalize
                criteria_list = criteria if isinstance(criteria, list) else []
                scales_list = scales if isinstance(scales, list) else []
                sel_list = selections if isinstance(selections, list) else []
                def _has(c: str, s: str) -> bool:
                    try:
                        return any(x.get('criteria') == c and x.get('scale') == s for x in sel_list if isinstance(x, dict))
                    except Exception:
                        return False
                style_parts = ["position:absolute"]
                if left is not None:
                    style_parts.append(f"left:{_pct(left)}")
                if right is not None:
                    style_parts.append(f"right:{_pct(right)}")
                if top is not None:
                    style_parts.append(f"top:{_pct(top)}")
                tbl_head = '<tr><th style="border:1px solid #999;padding:4px;width:28%">Nội dung</th>' + ''.join([f'<th style="border:1px solid #999;padding:4px">{frappe.utils.escape_html(str(sc))}</th>' for sc in scales_list]) + '</tr>'
                rows = []
                for cr in criteria_list:
                    safe_cr = frappe.utils.escape_html(str(cr))
                    cells = ''.join([f'<td style="border:1px solid #999;padding:4px;text-align:center">{"x" if _has(cr, sc) else ""}</td>' for sc in scales_list])
                    rows.append(f'<tr><td style="border:1px solid #999;padding:4px">{safe_cr}</td>{cells}</tr>')
                table_html = (
                    '<table style="border-collapse:collapse;width:100%;font-size:11pt;border:1px solid #ccc">'
                    f'<thead>{tbl_head}</thead>'
                    f'<tbody>{"".join(rows)}</tbody>'
                    '</table>'
                )
                overlay_items.append(f'<div style="{";".join(style_parts)}">{table_html}</div>')
            elif etype == "comments":
                left = el.get("left", None)
                right = el.get("right", None)
                top = el.get("top", None)
                items = el.get("items") or _resolve_path(report_data, el.get("listPath")) or []
                limit = el.get("limit", None)
                items_list = items if isinstance(items, list) else []
                if isinstance(limit, int) and limit >= 0:
                    items_list = items_list[:limit]
                style_parts = ["position:absolute"]
                if left is not None:
                    style_parts.append(f"left:{_pct(left)}")
                if right is not None:
                    style_parts.append(f"right:{_pct(right)}")
                if top is not None:
                    style_parts.append(f"top:{_pct(top)}")
                blocks: List[str] = []
                for it in items_list:
                    if not isinstance(it, dict):
                        continue
                    title = frappe.utils.escape_html(str(it.get('title') or ''))
                    value = frappe.utils.escape_html(str(it.get('value') or ''))
                    block_html = (
                        '<div style="margin-bottom:8px">'
                        f'<div style="font-weight:600;font-size:12pt">{title}</div>'
                        f'<div style="min-height:64px;padding:8px;border:1px solid #ccc;border-radius:4px;font-size:12pt;white-space:pre-wrap">{value}</div>'
                        '</div>'
                    )
                    blocks.append(block_html)
                overlay_items.append(f'<div style="{";".join(style_parts)}">{"".join(blocks)}</div>')
            # else: unsupported type -> ignore
        # If form has no positioned elements, provide sensible defaults for page 1
        if not overlay_items and idx == 0:
            frappe.logger().warning(f"No overlay items found for page {idx}, using fallback defaults")
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
                class_str = " ".join(classes)
                safe_content = frappe.utils.escape_html(content or "")
                overlay_items.append(
                    f'<div class="{class_str}" style="left:{left}%;top:{top}%;width:{width}%;">{safe_content}</div>'
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
        frappe.logger().info(f"Report data structure: {json.dumps(data, indent=2, default=str)[:1000]}...")
        
        # Transform data to match frontend layout binding expectations
        transformed_data = _transform_data_for_bindings(data)
        frappe.logger().info(f"Transformed data structure: {json.dumps(transformed_data, indent=2, default=str)[:1000]}...")
        
        # Special handling for PRIM_VN - use dedicated renderer instead of layout_json
        if form.code == 'PRIM_VN':
            frappe.logger().info("Using dedicated PRIM_VN renderer")
            try:
                html = _build_prim_vn_html(form, transformed_data)
                frappe.logger().info("PRIM_VN HTML built successfully")
            except Exception as prim_error:
                frappe.logger().error(f"Error in PRIM_VN renderer: {str(prim_error)}")
                frappe.log_error(f"PRIM_VN renderer error: {str(prim_error)}")
                # Fallback to regular renderer
                frappe.logger().info("Falling back to regular HTML renderer")
                html = _build_html(form, transformed_data)
        else:
            html = _build_html(form, transformed_data)
        return single_item_response({"html": html}, "HTML built")
    except frappe.DoesNotExistError:
        return not_found_response("Report not found")
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        frappe.log_error(f"Error get_report_html: {str(e)}")
        frappe.logger().error(f"Full error details: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        return error_response(f"Error building html: {str(e)}")


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


@frappe.whitelist(allow_guest=False)
def get_report_data(report_id: Optional[str] = None):
    """New API: Get structured report data for frontend React rendering"""
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
        
        frappe.logger().info(f"Report data structure: {json.dumps(data, indent=2, default=str)[:1000]}...")
        
        # Transform data to match frontend layout binding expectations
        transformed_data = _transform_data_for_bindings(data)
        frappe.logger().info(f"Transformed data structure: {json.dumps(transformed_data, indent=2, default=str)[:1000]}...")
        
        # Return structured data for frontend React rendering
        response_data = {
            "form_code": form.code or "PRIM_VN",
            "data": transformed_data,
            "student": transformed_data.get("student", {}),
            "class": transformed_data.get("class", {}),
            "report": transformed_data.get("report", {}),
            "subjects": transformed_data.get("subjects", []),
            "homeroom": transformed_data.get("homeroom", []),
        }
        
        frappe.logger().info("Returning structured data for frontend rendering")
        return single_item_response(response_data, "Report data retrieved for frontend rendering")
        
    except frappe.DoesNotExistError:
        return not_found_response("Report not found")
    except frappe.PermissionError:
        return forbidden_response("Access denied")
    except Exception as e:
        frappe.log_error(f"Error get_report_data: {str(e)}")
        frappe.logger().error(f"Full error details: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        return error_response(f"Error getting report data: {str(e)}")


