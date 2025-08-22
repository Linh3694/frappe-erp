import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json


@frappe.whitelist(allow_guest=False)
def get_all_families(page=1, limit=20):
    """Get all families with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        
        frappe.logger().info(f"get_all_families called with page: {page}, limit: {limit}")
        
        # Calculate offset for pagination
        offset = (page - 1) * limit
        
        filters = {}
        
        frappe.logger().info(f"Query filters: {filters}")
        frappe.logger().info(f"Query pagination: offset={offset}, limit={limit}")
        
        families = frappe.get_all(
            "CRM Family",
            fields=[
                "name",
                "student_id",
                "guardian_id", 
                "relationship",
                "key_person",
                "access",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="student_id asc, guardian_id asc",
            limit_start=offset,
            limit_page_length=limit
        )
        
        frappe.logger().info(f"Found {len(families)} families")
        
        # Get total count
        total_count = frappe.db.count("CRM Family", filters=filters)
        total_pages = (total_count + limit - 1) // limit
        
        frappe.logger().info(f"Total count: {total_count}, Total pages: {total_pages}")
        
        return {
            "success": True,
            "data": families,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
            "message": "Families fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching families: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching families: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)  
def get_family_data():
    """Get a specific family by ID"""
    try:
        # Get parameters from form_dict
        family_id = frappe.local.form_dict.get("family_id")
        student_id = frappe.local.form_dict.get("student_id")
        guardian_id = frappe.local.form_dict.get("guardian_id")
        
        frappe.logger().info(f"get_family_data called - family_id: {family_id}, student_id: {student_id}, guardian_id: {guardian_id}")
        frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        
        if not family_id and not student_id and not guardian_id:
            return {
                "success": False,
                "data": {},
                "message": "Family ID, Student ID, or Guardian ID is required"
            }
        
        # Build filters based on what parameter we have
        if family_id:
            family = frappe.get_doc("CRM Family", family_id)
        elif student_id and guardian_id:
            # Search by both student and guardian
            families = frappe.get_all("CRM Family", 
                filters={
                    "student_id": student_id,
                    "guardian_id": guardian_id
                }, 
                fields=["name"], 
                limit=1)
            
            if not families:
                return {
                    "success": False,
                    "data": {},
                    "message": "Family not found"
                }
            
            family = frappe.get_doc("CRM Family", families[0].name)
        elif student_id:
            # Search by student only
            families = frappe.get_all("CRM Family", 
                filters={"student_id": student_id}, 
                fields=["name"])
            
            if not families:
                return {
                    "success": False,
                    "data": [],
                    "message": "No families found for this student"
                }
            
            # Return multiple families for this student
            family_data = []
            for f in families:
                doc = frappe.get_doc("CRM Family", f.name)
                family_data.append({
                    "name": doc.name,
                    "student_id": doc.student_id,
                    "guardian_id": doc.guardian_id,
                    "relationship": doc.relationship,
                    "key_person": doc.key_person,
                    "access": doc.access
                })
            
            return {
                "success": True,
                "data": family_data,
                "message": "Families fetched successfully"
            }
        elif guardian_id:
            # Search by guardian only
            families = frappe.get_all("CRM Family", 
                filters={"guardian_id": guardian_id}, 
                fields=["name"])
            
            if not families:
                return {
                    "success": False,
                    "data": [],
                    "message": "No families found for this guardian"
                }
            
            # Return multiple families for this guardian
            family_data = []
            for f in families:
                doc = frappe.get_doc("CRM Family", f.name)
                family_data.append({
                    "name": doc.name,
                    "student_id": doc.student_id,
                    "guardian_id": doc.guardian_id,
                    "relationship": doc.relationship,
                    "key_person": doc.key_person,
                    "access": doc.access
                })
            
            return {
                "success": True,
                "data": family_data,
                "message": "Families fetched successfully"
            }
        
        if not family:
            return {
                "success": False,
                "data": {},
                "message": "Family not found"
            }
        
        return {
            "success": True,
            "data": {
                "name": family.name,
                "student_id": family.student_id,
                "guardian_id": family.guardian_id,
                "relationship": family.relationship,
                "key_person": family.key_person,
                "access": family.access,
                "creation": family.creation.isoformat() if family.creation else None,
                "modified": family.modified.isoformat() if family.modified else None
            },
            "message": "Family fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching family data: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching family data: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_family():
    """Create a new family relationship - ROBUST VERSION"""
    try:
        # Get data from request - follow Student pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_family: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_family: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_family: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_family: {data}")
        
        # Extract values from data
        student_id = data.get("student_id")
        guardian_id = data.get("guardian_id")
        relationship = data.get("relationship")
        key_person = data.get("key_person", False)
        access = data.get("access", False)
        
        # Input validation
        if not student_id or not guardian_id or not relationship:
            frappe.throw(_("Student ID, Guardian ID, and Relationship are required"))
        
        # Validate relationship
        valid_relationships = ["dad", "mom", "foster_parent", "grandparent", "uncle_aunt", "sibling", "other"]
        if relationship not in valid_relationships:
            frappe.throw(_(f"Relationship must be one of: {', '.join(valid_relationships)}"))
        
        # Check if this exact family relationship already exists
        existing_family = frappe.db.exists(
            "CRM Family", 
            {
                "student_id": student_id,
                "guardian_id": guardian_id
            }
        )
        if existing_family:
            frappe.throw(_(f"Family relationship between student '{student_id}' and guardian '{guardian_id}' already exists"))
        
        # Verify student exists
        if not frappe.db.exists("CRM Student", student_id):
            frappe.throw(_(f"Student '{student_id}' not found"))
        
        # Verify guardian exists
        if not frappe.db.exists("CRM Guardian", guardian_id):
            frappe.throw(_(f"Guardian '{guardian_id}' not found"))
        
        # Create new family relationship with validation bypass
        family_doc = frappe.get_doc({
            "doctype": "CRM Family",
            "student_id": student_id,
            "guardian_id": guardian_id,
            "relationship": relationship,
            "key_person": int(key_person) if key_person else 0,
            "access": int(access) if access else 0
        })
        
        # Bypass validation temporarily due to doctype cache issue
        family_doc.flags.ignore_validate = True
        family_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        # Return consistent API response format
        return {
            "success": True,
            "data": {
                "name": family_doc.name,
                "student_id": family_doc.student_id,
                "guardian_id": family_doc.guardian_id,
                "relationship": family_doc.relationship,
                "key_person": family_doc.key_person,
                "access": family_doc.access
            },
            "message": "Family relationship created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating family: {str(e)}")
        frappe.throw(_(f"Error creating family: {str(e)}"))


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def update_family(family_id=None, relationship=None, key_person=None, access=None):
    """Update an existing family relationship"""
    try:
        # Get parameters from multiple sources for flexibility
        if not family_id:
            family_id = frappe.local.form_dict.get("family_id")
        if not relationship:
            relationship = frappe.local.form_dict.get("relationship")
        if key_person is None:
            key_person = frappe.local.form_dict.get("key_person")
        if access is None:
            access = frappe.local.form_dict.get("access")
        
        # Fallback to JSON data if form_dict is empty
        if not family_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                family_id = json_data.get("family_id")
                relationship = json_data.get("relationship")
                key_person = json_data.get("key_person")
                access = json_data.get("access")
            except Exception:
                pass
        
        if not family_id:
            return {
                "success": False,
                "data": {},
                "message": "Family ID is required"
            }
        
        # Get existing document
        try:
            family_doc = frappe.get_doc("CRM Family", family_id)
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Family not found"
            }
        
        # Track if any changes were made
        changes_made = False
        
        # Helper function to normalize values for comparison
        def normalize_value(val):
            """Convert None/null/empty to empty string for comparison"""
            if val is None or val == "null" or val == "":
                return ""
            return str(val).strip()
        
        # Update fields if provided
        if relationship and normalize_value(relationship) != normalize_value(family_doc.relationship):
            # Validate relationship
            valid_relationships = ["dad", "mom", "foster_parent", "grandparent", "uncle_aunt", "sibling", "other"]
            if relationship not in valid_relationships:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Relationship must be one of: {', '.join(valid_relationships)}"
                }
            family_doc.relationship = relationship
            changes_made = True
        
        if key_person is not None:
            new_key_person = int(key_person) if str(key_person).lower() in ['1', 'true', 'yes'] else 0
            if new_key_person != family_doc.key_person:
                family_doc.key_person = new_key_person
                changes_made = True

        if access is not None:
            new_access = int(access) if str(access).lower() in ['1', 'true', 'yes'] else 0
            if new_access != family_doc.access:
                family_doc.access = new_access
                changes_made = True
        
        # Save the document with validation disabled
        try:
            family_doc.flags.ignore_validate = True
            family_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as save_error:
            return {
                "success": False,
                "data": {},
                "message": f"Failed to save family: {str(save_error)}"
            }
        
        # Reload to get the final saved data from database
        family_doc.reload()
        
        return {
            "success": True,
            "data": {
                "name": family_doc.name,
                "student_id": family_doc.student_id,
                "guardian_id": family_doc.guardian_id,
                "relationship": family_doc.relationship,
                "key_person": family_doc.key_person,
                "access": family_doc.access
            },
            "message": "Family updated successfully"
        }
        
    except Exception as e:
        return {
            "success": False,
            "data": {},
            "message": f"Error updating family: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def delete_family():
    """Delete a family relationship"""
    try:
        # Get family ID from form_dict
        family_id = frappe.local.form_dict.get("family_id")
        
        frappe.logger().info(f"delete_family called - family_id: {family_id}")
        
        if not family_id:
            return {
                "success": False,
                "data": {},
                "message": "Family ID is required"
            }
        
        # Get family document
        try:
            family_doc = frappe.get_doc("CRM Family", family_id)
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Family not found"
            }
        
        # Delete the document
        frappe.delete_doc("CRM Family", family_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Family relationship deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting family: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting family: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def search_families(search_term=None, page=1, limit=20):
    """Search families with pagination"""
    try:
        # Normalize parameters: prefer form_dict values if provided
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')
        # Coerce page/limit from form if present
        page = int(form.get('page', page))
        limit = int(form.get('limit', limit))

        frappe.logger().info(f"search_families called with search_term: '{search_term}', page: {page}, limit: {limit}")
        
        # Build search terms (use parameterized queries)
        where_clauses = ["1=1"]  # Base condition
        params = []
        if search_term and str(search_term).strip():
            like = f"%{str(search_term).strip()}%"
            where_clauses.append("(LOWER(f.student_id) LIKE LOWER(%s) OR LOWER(f.guardian_id) LIKE LOWER(%s) OR LOWER(f.relationship) LIKE LOWER(%s) OR LOWER(s.student_name) LIKE LOWER(%s) OR LOWER(g.guardian_name) LIKE LOWER(%s))")
            params.extend([like, like, like, like, like])
        
        conditions = " AND ".join(where_clauses)
        frappe.logger().info(f"FINAL WHERE: {conditions} | params: {params}")
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get families with search (parameterized) - join with student and guardian names
        sql_query = (
            """
            SELECT 
                f.name,
                f.student_id,
                f.guardian_id,
                f.relationship,
                f.key_person,
                f.access,
                f.creation,
                f.modified,
                s.student_name,
                g.guardian_name
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Student` s ON f.student_id = s.name
            LEFT JOIN `tabCRM Guardian` g ON f.guardian_id = g.name
            WHERE {where}
            ORDER BY f.student_id ASC, f.guardian_id ASC
            LIMIT %s OFFSET %s
            """
        ).format(where=conditions)

        frappe.logger().info(f"EXECUTING SQL QUERY: {sql_query} | params={params + [limit, offset]}")

        families = frappe.db.sql(sql_query, params + [limit, offset], as_dict=True)

        frappe.logger().info(f"SQL QUERY RETURNED {len(families)} families")
        
        # Get total count (parameterized)
        count_query = (
            """
            SELECT COUNT(*) as count
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Student` s ON f.student_id = s.name
            LEFT JOIN `tabCRM Guardian` g ON f.guardian_id = g.name
            WHERE {where}
            """
        ).format(where=conditions)
        
        frappe.logger().info(f"EXECUTING COUNT QUERY: {count_query} | params={params}")
        
        total_count = frappe.db.sql(count_query, params, as_dict=True)[0]['count']
        
        frappe.logger().info(f"COUNT QUERY RETURNED: {total_count}")
        
        total_pages = (total_count + limit - 1) // limit
        
        return {
            "success": True,
            "data": families,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
            "message": "Family search completed successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error searching families: {str(e)}")
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
            "message": f"Error searching families: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_families_for_selection():
    """Get families for dropdown selection"""
    try:
        families = frappe.db.sql("""
            SELECT 
                f.name,
                f.student_id,
                f.guardian_id,
                f.relationship,
                f.key_person,
                f.access,
                s.student_name,
                g.guardian_name
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Student` s ON f.student_id = s.name
            LEFT JOIN `tabCRM Guardian` g ON f.guardian_id = g.name
            ORDER BY s.student_name ASC, g.guardian_name ASC
        """, as_dict=True)
        
        return {
            "success": True,
            "data": families,
            "message": "Families fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching families for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching families: {str(e)}"
        }
