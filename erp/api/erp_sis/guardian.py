import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
import unicodedata
from typing import Optional


def _normalize_text(text: str) -> str:
    try:
        text = unicodedata.normalize('NFD', text or '')
        text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
        text = text.replace('đ', 'd').replace('Đ', 'D')
        return text.lower()
    except Exception:
        return (text or '').lower()


def _resolve_guardian_docname(identifier: Optional[str] = None, guardian_code: Optional[str] = None, guardian_slug: Optional[str] = None) -> Optional[str]:
    """Resolve CRM Guardian docname from various identifiers: docname, guardian_id (code), or slug.
    Returns the docname or None.
    """
    # Prefer direct docname
    ident = (identifier or '').strip()
    code = (guardian_code or '').strip()
    slug = (guardian_slug or '').strip().lower()

    if ident and frappe.db.exists("CRM Guardian", ident):
        return ident

    # Exact guardian_id match
    if ident:
        hit = frappe.get_all("CRM Guardian", filters={"guardian_id": ident}, fields=["name"], limit=1)
        if hit:
            return hit[0].name
        # Case-insensitive guardian_id
        ci = frappe.db.sql(
            """
            SELECT name FROM `tabCRM Guardian` WHERE LOWER(guardian_id)=LOWER(%s) LIMIT 1
            """,
            (ident,),
            as_dict=True,
        )
        if ci:
            return ci[0].name
        # Fuzzy guardian_id LIKE
        like = frappe.db.sql(
            """
            SELECT name FROM `tabCRM Guardian` WHERE LOWER(guardian_id) LIKE LOWER(%s) LIMIT 1
            """,
            (f"%{ident}%",),
            as_dict=True,
        )
        if like:
            return like[0].name

    # guardian_code explicit
    if code:
        hit = frappe.get_all("CRM Guardian", filters={"guardian_id": code}, fields=["name"], limit=1)
        if hit:
            return hit[0].name

    # Slug by normalized guardian_name
    slug_candidate = slug or (ident if '-' in ident else '')
    if slug_candidate:
        search_words = slug_candidate.replace('-', ' ')
        candidates = frappe.db.sql(
            """
            SELECT name, guardian_name FROM `tabCRM Guardian`
            WHERE LOWER(guardian_name) LIKE %s LIMIT 100
            """,
            (f"%{search_words.lower()}%",),
            as_dict=True,
        )
        norm_slug = slug_candidate
        for row in candidates:
            name_slug = _normalize_text(row.get('guardian_name', '')).replace(' ', '-').replace('--', '-')
            if name_slug == norm_slug:
                return row['name']

    return None


@frappe.whitelist(allow_guest=False)
def get_all_guardians(page=1, limit=20):
    """Get all guardians with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        
        frappe.logger().info(f"get_all_guardians called with page: {page}, limit: {limit}")
        
        # Calculate offset for pagination
        offset = (page - 1) * limit
        
        # Temporarily disable campus filtering for guardians 
        filters = {}
        
        frappe.logger().info(f"Query filters: {filters}")
        frappe.logger().info(f"Query pagination: offset={offset}, limit={limit}")
        
        guardians = frappe.get_all(
            "CRM Guardian",
            fields=[
                "name",
                "guardian_id",
                "guardian_name",
                "phone_number",
                "email",
                "family_code",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="guardian_name asc",
            limit_start=offset,
            limit_page_length=limit
        )
        # Normalize nullable fields for FE
        for g in guardians:
            if g.get("email") is None:
                g["email"] = ""
        
        frappe.logger().info(f"Found {len(guardians)} guardians")
        
        # Get total count
        total_count = frappe.db.count("CRM Guardian", filters=filters)
        total_pages = (total_count + limit - 1) // limit
        
        frappe.logger().info(f"Total count: {total_count}, Total pages: {total_pages}")
        
        return {
            "success": True,
            "data": guardians,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
            "message": "Guardians fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardians: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching guardians: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)  
def get_guardian_data():
    """Get a specific guardian by ID, code or slug"""
    try:
        # Get parameters from form_dict
        form = frappe.local.form_dict or {}
        guardian_id = form.get("guardian_id") or form.get("id") or form.get("name")
        guardian_code = form.get("guardian_code")
        guardian_slug = form.get("guardian_slug")
        
        frappe.logger().info(f"get_guardian_data called - guardian_id: {guardian_id}, guardian_code: {guardian_code}, guardian_slug: {guardian_slug}")
        frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        
        # Also parse GET args and JSON body for robustness
        if not (guardian_id or guardian_code or guardian_slug):
            try:
                if hasattr(frappe.request, 'args') and frappe.request.args:
                    guardian_id = guardian_id or frappe.request.args.get('guardian_id')
                    guardian_code = guardian_code or frappe.request.args.get('guardian_code')
                    guardian_slug = guardian_slug or frappe.request.args.get('guardian_slug')
            except Exception:
                pass
            if not (guardian_id or guardian_code or guardian_slug) and frappe.request.data:
                try:
                    body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                    data = json.loads(body)
                    guardian_id = data.get('guardian_id') or data.get('id') or data.get('name')
                    guardian_code = guardian_code or data.get('guardian_code')
                    guardian_slug = guardian_slug or data.get('guardian_slug')
                except Exception:
                    pass

        if not guardian_id and not guardian_code and not guardian_slug:
            return {
                "success": False,
                "data": {},
                "message": "Guardian ID, code, or slug is required"
            }
        
        # Build filters based on what parameter we have
        if guardian_id:
            docname = _resolve_guardian_docname(identifier=guardian_id)
            if docname:
                guardian = frappe.get_doc("CRM Guardian", docname)
            else:
                guardian = None
        elif guardian_code:
            # Search by guardian_id (which acts as code)
            docname = _resolve_guardian_docname(guardian_code=guardian_code)
            if not docname:
                return {"success": False, "data": {}, "message": "Guardian not found"}
            guardian = frappe.get_doc("CRM Guardian", docname)
        elif guardian_slug:
            docname = _resolve_guardian_docname(guardian_slug=guardian_slug)
            if not docname:
                return {"success": False, "data": {}, "message": "Guardian not found"}
            guardian = frappe.get_doc("CRM Guardian", docname)
        
        if not guardian:
            return {
                "success": False,
                "data": {},
                "message": "Guardian not found"
            }
        
        return {
            "success": True,
            "data": {
                "name": guardian.name,
                "guardian_id": guardian.guardian_id,
                "guardian_name": guardian.guardian_name,
                "phone_number": guardian.phone_number,
                "email": guardian.email,
                "creation": guardian.creation.isoformat() if guardian.creation else None,
                "modified": guardian.modified.isoformat() if guardian.modified else None
            },
            "message": "Guardian fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardian data: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching guardian data: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_guardian():
    """Create a new guardian - ROBUST VERSION"""
    try:
        # Get data from request - handle both JSON and form data
        data = {}
        
        # Log all available data sources for debugging
        frappe.logger().info(f"Request method: {frappe.request.method}")
        frappe.logger().info(f"Request data: {frappe.request.data}")
        frappe.logger().info(f"Form dict: {frappe.local.form_dict}")
        
        # Try multiple data sources
        if frappe.request.data:
            try:
                # Handle bytes data
                if isinstance(frappe.request.data, bytes):
                    json_data = json.loads(frappe.request.data.decode('utf-8'))
                else:
                    json_data = json.loads(frappe.request.data)
                
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Successfully parsed JSON data: {data}")
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                frappe.logger().error(f"JSON parsing failed: {str(e)}")
                data = frappe.local.form_dict
        
        # Fallback to form_dict if no JSON data
        if not data:
            data = frappe.local.form_dict
            frappe.logger().info(f"Using form_dict data: {data}")
        
        # Extract values from data with multiple possible field names
        guardian_name = data.get("guardian_name") or data.get("guardianName") or data.get("name")
        guardian_id = data.get("guardian_id") or data.get("guardianId") or ""
        phone_number = data.get("phone_number") or data.get("phoneNumber") or ""
        email = data.get("email") or ""
        
        # Generate guardian_id if not provided
        if not guardian_id and guardian_name:
            import re
            # Create simple ID from name (remove spaces, Vietnamese chars, make lowercase)
            guardian_id = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', guardian_name.lower())
            guardian_id = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', guardian_id)
            guardian_id = re.sub(r'[ìíịỉĩ]', 'i', guardian_id)
            guardian_id = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', guardian_id)
            guardian_id = re.sub(r'[ùúụủũưừứựửữ]', 'u', guardian_id)
            guardian_id = re.sub(r'[ỳýỵỷỹ]', 'y', guardian_id)
            guardian_id = guardian_id.replace('đ', 'd')
            guardian_id = re.sub(r'[^a-z0-9]', '-', guardian_id)
            guardian_id = re.sub(r'-+', '-', guardian_id).strip('-') + '-' + str(nowdate().replace('-', ''))[-4:]
        
        # Format phone number for Vietnam if needed
        if phone_number and not phone_number.startswith('+'):
            # Add Vietnam country code if phone starts with 0
            if phone_number.startswith('0'):
                phone_number = '+84' + phone_number[1:]
            # Add + if it's just numbers
            elif phone_number.isdigit() and len(phone_number) >= 9:
                phone_number = '+84' + phone_number
        
        frappe.logger().info(f"Extracted values - Name: {guardian_name}, Phone: {phone_number}, Email: {email}")
        
        # Input validation with detailed debugging
        if not guardian_name:
            # Log all available data for debugging
            frappe.logger().error(f"Guardian name validation failed!")
            frappe.logger().error(f"Raw request data: {frappe.request.data}")
            frappe.logger().error(f"Form dict: {frappe.local.form_dict}")
            frappe.logger().error(f"Parsed data: {data}")
            frappe.logger().error(f"Guardian name extracted: '{guardian_name}'")
            
            # Also try to get data directly from form_dict with different keys
            alt_name = frappe.local.form_dict.get('guardian_name') or frappe.local.form_dict.get('guardianName')
            frappe.logger().error(f"Alternative name from form_dict: '{alt_name}'")
            
            frappe.throw(_("Guardian name is required"))
                
        # Check if guardian name already exists
        existing_name = frappe.db.exists("CRM Guardian", {"guardian_name": guardian_name})
        if existing_name:
            frappe.throw(_(f"Guardian with name '{guardian_name}' already exists"))
        
        frappe.logger().info(f"Creating guardian with Name: {guardian_name}")
        
        # Create new guardian with validation bypass
        guardian_doc = frappe.get_doc({
            "doctype": "CRM Guardian",
            "guardian_id": guardian_id,
            "guardian_name": guardian_name,
            "phone_number": phone_number or "",
            "email": email or ""
        })
        
        frappe.logger().info(f"Creating guardian with ID: {guardian_id}, Name: {guardian_name}")
        
        frappe.logger().info(f"Guardian doc created: {guardian_doc.as_dict()}")
        
        # Bypass validation temporarily due to doctype cache issue
        guardian_doc.flags.ignore_validate = True
        guardian_doc.flags.ignore_permissions = True
        guardian_doc.insert(ignore_permissions=True)
        
        # Force persist critical fields in case of server scripts altering values
        try:
            frappe.db.set_value("CRM Guardian", guardian_doc.name, {
                "phone_number": guardian_doc.phone_number or (phone_number or ""),
                "email": guardian_doc.email or (email or ""),
            })
        except Exception as e:
            frappe.logger().error(f"set_value after insert failed: {str(e)}")
        
        frappe.logger().info(f"Guardian inserted successfully with name: {guardian_doc.name}")
        frappe.db.commit()
        
        # Return consistent API response format
        return {
            "success": True,
            "data": {
                "name": guardian_doc.name,
                "guardian_id": guardian_doc.guardian_id,
                "guardian_name": guardian_doc.guardian_name,
                "phone_number": guardian_doc.phone_number,
                "email": guardian_doc.email if guardian_doc.email is not None else (email or "")
            },
            "message": "Guardian created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating guardian: {str(e)}", "Guardian Creation Error")
        frappe.logger().error(f"Full error details: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error creating guardian: {str(e)}"
        }


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def update_guardian(guardian_id=None, guardian_name=None, phone_number=None, email=None):
    """Update an existing guardian"""
    try:
        # Collect parameters from multiple sources and MERGE (do not depend on presence of guardian_id)
        form = frappe.local.form_dict or {}
        guardian_id = guardian_id or form.get("guardian_id") or form.get("id") or form.get("name")
        guardian_name = guardian_name if guardian_name is not None else form.get("guardian_name")
        phone_number = phone_number if phone_number is not None else form.get("phone_number")
        email = email if email is not None else form.get("email")

        # Merge JSON body (if present)
        if frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                json_data = json.loads(body)
                guardian_id = json_data.get("guardian_id") or json_data.get("id") or json_data.get("name") or guardian_id
                if json_data.get("guardian_name") is not None:
                    guardian_name = json_data.get("guardian_name")
                if json_data.get("phone_number") is not None:
                    phone_number = json_data.get("phone_number")
                if json_data.get("email") is not None:
                    email = json_data.get("email")
            except Exception:
                pass
        
        if not guardian_id:
            return {
                "success": False,
                "data": {},
                "message": "Guardian ID is required"
            }
        
        # Resolve real docname from name/code/slug, then get existing document
        resolved_docname = _resolve_guardian_docname(identifier=guardian_id)
        if not resolved_docname:
            return {"success": False, "data": {}, "message": "Guardian not found"}

        try:
            guardian_doc = frappe.get_doc("CRM Guardian", resolved_docname)
        except frappe.DoesNotExistError:
            return {"success": False, "data": {}, "message": "Guardian not found"}
        
        # Track if any changes were made
        changes_made = False
        
        # Helper function to normalize values for comparison
        def normalize_value(val):
            """Convert None/null/empty to empty string for comparison"""
            if val is None or val == "null" or val == "":
                return ""
            return str(val).strip()
        # Update fields (allow clearing with empty string) - assign unconditionally if key provided
        if guardian_name is not None:
            guardian_doc.guardian_name = guardian_name or ""
            changes_made = True
        
        if phone_number is not None:
            guardian_doc.phone_number = phone_number or ""
            changes_made = True

        if email is not None:
            guardian_doc.email = email or ""
            changes_made = True
        
        # Save the document with validation disabled
        try:
            guardian_doc.flags.ignore_validate = True
            guardian_doc.save(ignore_permissions=True)
            # Force-set using db API to avoid any override by hooks/server scripts
            frappe.db.set_value("CRM Guardian", guardian_doc.name, {
                "guardian_name": guardian_doc.guardian_name,
                "phone_number": guardian_doc.phone_number,
                "email": guardian_doc.email or "",
            })
            frappe.db.commit()
        except Exception as save_error:
            return {
                "success": False,
                "data": {},
                "message": f"Failed to save guardian: {str(save_error)}"
            }
        
        # Reload to get the final saved data from database
        guardian_doc.reload()
        
        return {
            "success": True,
            "data": {
                "name": guardian_doc.name,
                "guardian_id": guardian_doc.guardian_id,
                "guardian_name": guardian_doc.guardian_name,
                "phone_number": guardian_doc.phone_number,
                "email": guardian_doc.email if guardian_doc.email is not None else (email or "")
            },
            "message": "Guardian updated successfully"
        }
        
    except Exception as e:
        return {
            "success": False,
            "data": {},
            "message": f"Error updating guardian: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def delete_guardian():
    """Delete a guardian"""
    try:
        # Get guardian ID from multiple possible sources
        form = frappe.local.form_dict or {}
        guardian_id = form.get("guardian_id") or form.get("id") or form.get("name") or form.get("docname")
        # Fallback aliases
        if not guardian_id and hasattr(frappe, 'form_dict') and frappe.form_dict:
            guardian_id = frappe.form_dict.get('guardian_id') or frappe.form_dict.get('id') or frappe.form_dict.get('name')
        if not guardian_id and hasattr(frappe.request, 'form') and frappe.request.form:
            try:
                guardian_id = frappe.request.form.get('guardian_id') or frappe.request.form.get('id') or frappe.request.form.get('name')
            except Exception:
                pass
        if not guardian_id and hasattr(frappe.request, 'args') and frappe.request.args:
            guardian_id = frappe.request.args.get('guardian_id') or frappe.request.args.get('id') or frappe.request.args.get('name')
        if not guardian_id and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body)
                guardian_id = data.get('guardian_id') or data.get('id') or data.get('name')
            except Exception:
                pass
        guardian_id = (guardian_id or '').strip()
        
        frappe.logger().info(f"delete_guardian called - guardian_id: {guardian_id}")
        
        if not guardian_id:
            return {
                "success": False,
                "data": {},
                "message": "Guardian ID is required"
            }
        
        # Resolve real docname from name/code/slug
        docname = _resolve_guardian_docname(identifier=guardian_id)
        if not docname:
            return {"success": False, "data": {}, "message": "Guardian not found"}
        
        # Cleanup relationships before delete
        try:
            frappe.db.delete("CRM Family Relationship", {"guardian": docname})
        except Exception as e:
            frappe.logger().error(f"Failed to cleanup relationships for guardian {docname}: {str(e)}")

        # Delete the document
        try:
            frappe.delete_doc("CRM Guardian", docname, ignore_permissions=True, force=1)
        except Exception as e:
            # Fallback hard delete in case of cascading rules
            try:
                frappe.db.sql("DELETE FROM `tabCRM Guardian` WHERE name=%s", (docname,))
            except Exception:
                raise e
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Guardian deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting guardian: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting guardian: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def bulk_delete_guardians():
    """Bulk delete multiple guardians"""
    try:
        # Get guardian IDs from form_dict
        guardian_ids = frappe.local.form_dict.get("guardian_ids")
        
        frappe.logger().info(f"bulk_delete_guardians called - guardian_ids: {guardian_ids}")
        
        if not guardian_ids:
            return {
                "success": False,
                "data": None,
                "message": "Guardian IDs are required"
            }
        
        if not isinstance(guardian_ids, list):
            guardian_ids = [guardian_ids]
        
        deleted_count = 0
        errors = []
        
        for guardian_id in guardian_ids:
            try:
                # Check if guardian exists
                if frappe.db.exists("CRM Guardian", guardian_id):
                    frappe.delete_doc("CRM Guardian", guardian_id)
                    deleted_count += 1
                else:
                    errors.append(f"Guardian {guardian_id} not found")
            except Exception as e:
                errors.append(f"Error deleting guardian {guardian_id}: {str(e)}")
        
        frappe.db.commit()
        frappe.logger().info(f"Bulk delete completed. Deleted: {deleted_count}, Errors: {len(errors)}")
        
        return {
            "success": True,
            "data": {
                "deleted_count": deleted_count,
                "error_count": len(errors),
                "errors": errors
            },
            "message": f"Successfully deleted {deleted_count} guardians"
        }
        
    except Exception as e:
        frappe.log_error(f"Error in bulk delete guardians: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"Error in bulk delete guardians: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def search_guardians(search_term=None, page=1, limit=20):
    """Search guardians with pagination"""
    try:
        # Normalize parameters: prefer form_dict values if provided
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')
        # Coerce page/limit from form if present
        page = int(form.get('page', page))
        limit = int(form.get('limit', limit))

        frappe.logger().info(f"search_guardians called with search_term: '{search_term}', page: {page}, limit: {limit}")
        
        # Build search terms (use parameterized queries)
        where_clauses = []
        params = []
        if search_term and str(search_term).strip():
            like = f"%{str(search_term).strip()}%"
            where_clauses.append("(LOWER(guardian_name) LIKE LOWER(%s) OR LOWER(guardian_id) LIKE LOWER(%s) OR LOWER(phone_number) LIKE LOWER(%s) OR LOWER(email) LIKE LOWER(%s))")
            params.extend([like, like, like, like])
        
        conditions = " AND ".join(where_clauses) if where_clauses else "1=1"
        frappe.logger().info(f"FINAL WHERE: {conditions} | params: {params}")
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get guardians with search (parameterized)
        sql_query = (
            """
            SELECT 
                name,
                guardian_id,
                guardian_name,
                phone_number,
                email,
                creation,
                modified
            FROM `tabCRM Guardian`
            WHERE {where}
            ORDER BY guardian_name ASC
            LIMIT %s OFFSET %s
            """
        ).format(where=conditions)

        frappe.logger().info(f"EXECUTING SQL QUERY: {sql_query} | params={params + [limit, offset]}")

        guardians = frappe.db.sql(sql_query, params + [limit, offset], as_dict=True)

        frappe.logger().info(f"SQL QUERY RETURNED {len(guardians)} guardians")

        # Post-filter in Python for better VN diacritics handling and strict contains
        def normalize_text(text: str) -> str:
            try:
                import unicodedata
                if not text:
                    return ''
                text = unicodedata.normalize('NFD', text)
                text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
                # Handle Vietnamese specific characters
                text = text.replace('đ', 'd').replace('Đ', 'D')
                return text.lower()
            except Exception:
                return (text or '').lower()

        if search_term and str(search_term).strip():
            norm_q = normalize_text(str(search_term).strip())
            pre_count = len(guardians)
            guardians = [
                g for g in guardians
                if (
                    normalize_text(g.get('guardian_name', '')) .find(norm_q) != -1
                    or (g.get('guardian_id') or '').lower().find(norm_q.lower()) != -1
                    or (g.get('phone_number') or '').lower().find(norm_q.lower()) != -1
                    or (g.get('email') or '').lower().find(norm_q.lower()) != -1
                )
            ]
            frappe.logger().info(f"POST-FILTERED {pre_count} -> {len(guardians)} using normalized query='{norm_q}'")
        
        # Get total count (parameterized)
        count_query = (
            """
            SELECT COUNT(*) as count
            FROM `tabCRM Guardian`
            WHERE {where}
            """
        ).format(where=conditions)
        
        frappe.logger().info(f"EXECUTING COUNT QUERY: {count_query} | params={params}")
        
        total_count = frappe.db.sql(count_query, params, as_dict=True)[0]['count']
        
        frappe.logger().info(f"COUNT QUERY RETURNED: {total_count}")
        
        total_pages = (total_count + limit - 1) // limit
        
        return {
            "success": True,
            "data": guardians,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
            "message": "Guardian search completed successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error searching guardians: {str(e)}")
        return {
            "success": False,
            "data": [],
            "pagination": {
                "current_page": page,
                "total_pages": 0,
                "total_count": 0,
                "limit": limit,
                "offset": 0
            },
            "message": f"Error searching guardians: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_guardians_for_selection():
    """Get guardians for dropdown selection"""
    try:
        guardians = frappe.get_all(
            "CRM Guardian",
            fields=[
                "name",
                "guardian_id",
                "guardian_name",
                "phone_number",
                "email"
            ],
            order_by="guardian_name asc"
        )
        
        return {
            "success": True,
            "data": guardians,
            "message": "Guardians fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardians for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching guardians: {str(e)}"
        }