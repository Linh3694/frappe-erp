import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json


@frappe.whitelist(allow_guest=False)
def get_family_details(family_id=None, family_code=None):
    """Get a family with full relationships (students and guardians)."""
    try:
        if not family_id and not family_code:
            return {"success": False, "data": {}, "message": "Family ID or code is required"}

        if family_code and not family_id:
            # Resolve by code
            res = frappe.get_all("CRM Family", filters={"family_code": family_code}, fields=["name"], limit=1)
            if res:
                family_id = res[0].name

        # Fetch family basic info using db API to avoid permission issues
        fam_row = None
        if family_id:
            fam_row = frappe.db.get_value("CRM Family", family_id, ["name", "family_code"], as_dict=True)
        if not fam_row and family_code:
            fam_row = frappe.db.get_value("CRM Family", {"family_code": family_code}, ["name", "family_code"], as_dict=True)
        if not fam_row:
            return {"success": False, "data": {}, "message": "Family not found"}
        family_name = fam_row.get("name")

        rels = frappe.get_all(
            "CRM Family Relationship",
            filters={"parent": family_name},
            fields=["student", "guardian", "relationship_type", "key_person", "access"],
        )

        # Fetch student/guardian display
        student_names = {}
        guardian_names = {}
        if rels:
            student_ids = list({r["student"] for r in rels if r.get("student")})
            guardian_ids = list({r["guardian"] for r in rels if r.get("guardian")})
            if student_ids:
                for s in frappe.get_all("CRM Student", filters={"name": ["in", student_ids]}, fields=["name", "student_name", "student_code", "family_code"]):
                    student_names[s.name] = s
            if guardian_ids:
                for g in frappe.get_all("CRM Guardian", filters={"name": ["in", guardian_ids]}, fields=["name", "guardian_name", "guardian_id", "family_code", "phone_number", "email"]):
                    guardian_names[g.name] = g

        return {
            "success": True,
            "data": {
                "name": family_name,
                "family_code": fam_row.get("family_code"),
                "relationships": rels,
                "students": student_names,
                "guardians": guardian_names,
            },
            "message": "Family details fetched successfully",
        }
    except Exception as e:
        frappe.log_error(f"Error fetching family details: {str(e)}")
        return {"success": False, "data": {}, "message": f"Error fetching family details: {str(e)}"}


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_family_members(family_id=None, students=None, guardians=None, relationships=None):
    """Replace students/guardians and relationships of an existing family."""
    try:
        if not family_id:
            family_id = frappe.local.form_dict.get("family_id")
        # Parse JSON strings if sent as form
        def parse_json(value):
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return []
            return value or []

        if frappe.request.data and (students is None or guardians is None or relationships is None):
            try:
                body = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                students = body.get("students", students)
                guardians = body.get("guardians", guardians)
                relationships = body.get("relationships", relationships)
            except Exception:
                pass

        students = parse_json(students)
        guardians = parse_json(guardians)
        relationships = parse_json(relationships)

        if not family_id:
            return {"success": False, "data": {}, "message": "Family ID is required"}

        family_doc = frappe.get_doc("CRM Family", family_id)
        # Reset relationships
        family_doc.set("relationships", [])
        for rel in relationships:
            family_doc.append("relationships", {
                "student": rel.get("student"),
                "guardian": rel.get("guardian"),
                "relationship_type": rel.get("relationship_type", ""),
                "key_person": int(rel.get("key_person", False)),
                "access": int(rel.get("access", True)),
            })
        family_doc.flags.ignore_validate = True
        family_doc.save(ignore_permissions=True)

        # Update students and guardians docs similar to create_family
        family_code = getattr(family_doc, 'family_code', family_doc.name)

        for student_id in students:
            if frappe.db.exists("CRM Student", student_id):
                student_doc = frappe.get_doc("CRM Student", student_id)
                student_doc.family_code = family_code
                student_doc.set("family_relationships", [])
                for rel in relationships:
                    if rel.get("student") == student_id:
                        student_doc.append("family_relationships", {
                            "student": student_id,
                            "guardian": rel.get("guardian"),
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False)),
                        })
                student_doc.flags.ignore_validate = True
                student_doc.save(ignore_permissions=True)

        for guardian_id in guardians:
            if frappe.db.exists("CRM Guardian", guardian_id):
                guardian_doc = frappe.get_doc("CRM Guardian", guardian_id)
                guardian_doc.family_code = family_code
                guardian_doc.set("student_relationships", [])
                for rel in relationships:
                    if rel.get("guardian") == guardian_id:
                        guardian_doc.append("student_relationships", {
                            "student": rel.get("student"),
                            "guardian": guardian_id,
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False)),
                        })
                guardian_doc.flags.ignore_validate = True
                guardian_doc.save(ignore_permissions=True)

        frappe.db.commit()

        return {"success": True, "data": {"family_id": family_doc.name}, "message": "Family members updated successfully"}
    except Exception as e:
        frappe.log_error(f"Error updating family members: {str(e)}")
        return {"success": False, "data": {}, "message": f"Error updating family members: {str(e)}"}
def get_all_families(page=1, limit=20):
    """Get all families with basic information and pagination - NEW STRUCTURE"""
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
        
        # Get families with relationships and student/guardian details
        families = frappe.db.sql("""
            SELECT 
                f.name,
                f.family_code,
                f.creation,
                f.modified,
                COUNT(DISTINCT fr.student) as student_count,
                COUNT(DISTINCT fr.guardian) as guardian_count,
                GROUP_CONCAT(DISTINCT s.student_name ORDER BY s.student_name SEPARATOR ', ') as student_names,
                GROUP_CONCAT(DISTINCT g.guardian_name ORDER BY g.guardian_name SEPARATOR ', ') as guardian_names
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
            GROUP BY f.name, f.family_code, f.creation, f.modified
            ORDER BY f.family_code ASC
            LIMIT %s OFFSET %s
        """, (limit, offset), as_dict=True)
        
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
                "family_code": getattr(family, "family_code", None),
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
    """Create a new family with multiple students and guardians - NEW STRUCTURE"""
    try:
        # Get data from request
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                # Support both bytes and string payloads
                if isinstance(frappe.request.data, bytes):
                    json_data = json.loads(frappe.request.data.decode('utf-8'))
                else:
                    json_data = json.loads(frappe.request.data)

                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_family: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_family (empty JSON body): {data}")
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                # If JSON parsing fails, use form_dict
                frappe.logger().error(f"JSON parsing failed in create_family: {str(e)}")
                data = frappe.local.form_dict
                frappe.logger().info(f"Using form data for create_family after JSON failure: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_family: {data}")
        
        # Extract values from data - handle both JSON and form data
        # Try to get from main data first, then from form_dict
        students = data.get("students") or frappe.local.form_dict.get("students", [])
        guardians = data.get("guardians") or frappe.local.form_dict.get("guardians", [])
        relationships = data.get("relationships") or frappe.local.form_dict.get("relationships", [])
        
        frappe.logger().info(f"Raw students: {students} (type: {type(students)})")
        frappe.logger().info(f"Raw guardians: {guardians} (type: {type(guardians)})")
        frappe.logger().info(f"Raw relationships: {relationships} (type: {type(relationships)})")
        
        # Parse JSON strings if they come from form data
        if isinstance(students, str):
            try:
                students = json.loads(students)
                frappe.logger().info(f"Parsed students from JSON: {students}")
            except json.JSONDecodeError as e:
                frappe.logger().error(f"Failed to parse students JSON: {e}")
                students = []
                
        if isinstance(guardians, str):
            try:
                guardians = json.loads(guardians)
                frappe.logger().info(f"Parsed guardians from JSON: {guardians}")
            except json.JSONDecodeError as e:
                frappe.logger().error(f"Failed to parse guardians JSON: {e}")
                guardians = []
                
        if isinstance(relationships, str):
            try:
                relationships = json.loads(relationships)
                frappe.logger().info(f"Parsed relationships from JSON: {relationships}")
            except json.JSONDecodeError as e:
                frappe.logger().error(f"Failed to parse relationships JSON: {e}")
                relationships = []
        
        frappe.logger().info(f"Received data: {data}")
        frappe.logger().info(f"Students: {students}")
        frappe.logger().info(f"Guardians: {guardians}")
        frappe.logger().info(f"Relationships: {relationships}")
        
        # Input validation
        if not students or not guardians or not relationships:
            frappe.logger().error(f"Validation failed - students: {len(students) if students else 0}, guardians: {len(guardians) if guardians else 0}, relationships: {len(relationships) if relationships else 0}")
            frappe.throw(_("Students, Guardians, and Relationships are required"))
        
        if len(students) == 0 or len(guardians) == 0:
            frappe.throw(_("At least one student and one guardian are required"))
        
        # Create family first to get auto-generated FAM-xxx code
        family_doc = frappe.get_doc({
            "doctype": "CRM Family",
            "relationships": []
        })
        
        # Insert to get auto-generated name (FAM-1, FAM-2, etc.)
        family_doc.flags.ignore_validate = True
        # Bypass mandatory since family_code is required but will be set to name after insert
        family_doc.insert(ignore_permissions=True, ignore_mandatory=True)
        
        # Use the auto-generated name as family_code
        family_code = family_doc.name  # This will be FAM-1, FAM-2, etc.
        
        # Now update the family_code field to match the name (required field)
        family_doc.family_code = family_code
        family_doc.flags.ignore_validate = True
        family_doc.save(ignore_permissions=True)
        
        # Verify all students exist
        for student_id in students:
            if not frappe.db.exists("CRM Student", student_id):
                frappe.throw(_(f"Student '{student_id}' not found"))
        
        # Verify all guardians exist
        for guardian_id in guardians:
            if not frappe.db.exists("CRM Guardian", guardian_id):
                frappe.throw(_(f"Guardian '{guardian_id}' not found"))
        
        # Add relationships to the existing family_doc
        for rel in relationships:
            family_doc.append("relationships", {
                "student": rel.get("student"),
                "guardian": rel.get("guardian"),
                "relationship_type": rel.get("relationship_type", ""),
                "key_person": int(rel.get("key_person", False)),
                "access": int(rel.get("access", True))
            })
        
        # Save the family with relationships
        family_doc.save(ignore_permissions=True)
        
        # Update students with family_code and family_relationships
        for student_id in students:
            try:
                frappe.logger().info(f"Updating student {student_id} with family_code {family_code}")
                student_doc = frappe.get_doc("CRM Student", student_id)
                frappe.logger().info(f"Student doc before update: family_code = {student_doc.family_code}")
                student_doc.family_code = family_code
                frappe.logger().info(f"Student doc after setting: family_code = {student_doc.family_code}")

                # Reset and append family relationships for this student (use child table API)
                student_doc.set("family_relationships", [])
                for rel in relationships:
                    if rel.get("student") == student_id:
                        student_doc.append("family_relationships", {
                            "student": student_id,
                            "guardian": rel.get("guardian"),
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False))
                        })

                student_doc.flags.ignore_validate = True
                student_doc.save(ignore_permissions=True)
                frappe.logger().info(f"Successfully updated student {student_id}")
            except Exception as e:
                frappe.logger().error(f"Error updating student {student_id}: {str(e)}")
                raise
        
        # Update guardians with family_code and student_relationships
        for guardian_id in guardians:
            try:
                frappe.logger().info(f"Updating guardian {guardian_id} with family_code {family_code}")
                guardian_doc = frappe.get_doc("CRM Guardian", guardian_id)
                frappe.logger().info(f"Guardian doc before update: family_code = {guardian_doc.family_code}")
                guardian_doc.family_code = family_code
                frappe.logger().info(f"Guardian doc after setting: family_code = {guardian_doc.family_code}")

                # Reset and append student relationships for this guardian (use child table API)
                guardian_doc.set("student_relationships", [])
                for rel in relationships:
                    if rel.get("guardian") == guardian_id:
                        guardian_doc.append("student_relationships", {
                            "student": rel.get("student"),
                            "guardian": guardian_id,
                            "relationship_type": rel.get("relationship_type", ""),
                            "key_person": int(rel.get("key_person", False)),
                            "access": int(rel.get("access", False))
                        })

                guardian_doc.flags.ignore_validate = True
                guardian_doc.save(ignore_permissions=True)
                frappe.logger().info(f"Successfully updated guardian {guardian_id}")
            except Exception as e:
                frappe.logger().error(f"Error updating guardian {guardian_id}: {str(e)}")
                raise
        
        frappe.db.commit()
        
        # Return consistent API response format
        return {
            "success": True,
            "data": {
                "family_code": family_code,
                "students": students,
                "guardians": guardians,
                "relationships": relationships
            },
            "message": "Family created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating family: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error creating family: {str(e)}"
        }


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
            where_clauses.append("(LOWER(f.family_code) LIKE LOWER(%s) OR LOWER(s.student_name) LIKE LOWER(%s) OR LOWER(g.guardian_name) LIKE LOWER(%s))")
            params.extend([like, like, like])
        
        conditions = " AND ".join(where_clauses)
        frappe.logger().info(f"FINAL WHERE: {conditions} | params: {params}")
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get families with search (parameterized) - join with student and guardian names
        sql_query = (
            """
            SELECT 
                f.name,
                f.family_code,
                f.creation,
                f.modified,
                COUNT(DISTINCT fr.student) as student_count,
                COUNT(DISTINCT fr.guardian) as guardian_count,
                GROUP_CONCAT(DISTINCT s.student_name SEPARATOR ', ') as student_names,
                GROUP_CONCAT(DISTINCT g.guardian_name SEPARATOR ', ') as guardian_names
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
            WHERE {where}
            GROUP BY f.name, f.family_code, f.creation, f.modified
            ORDER BY f.family_code ASC
            LIMIT %s OFFSET %s
            """
        ).format(where=conditions)

        frappe.logger().info(f"EXECUTING SQL QUERY: {sql_query} | params={params + [limit, offset]}")

        families = frappe.db.sql(sql_query, params + [limit, offset], as_dict=True)

        frappe.logger().info(f"SQL QUERY RETURNED {len(families)} families")
        
        # Get total count (parameterized)
        count_query = (
            """
            SELECT COUNT(DISTINCT f.name) as count
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
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
    """Get families for dropdown selection - NEW STRUCTURE"""
    try:
        families = frappe.db.sql("""
            SELECT 
                f.name,
                f.family_code,
                COUNT(DISTINCT fr.student) as student_count,
                COUNT(DISTINCT fr.guardian) as guardian_count,
                GROUP_CONCAT(DISTINCT s.student_name SEPARATOR ', ') as student_names,
                GROUP_CONCAT(DISTINCT g.guardian_name SEPARATOR ', ') as guardian_names
            FROM `tabCRM Family` f
            LEFT JOIN `tabCRM Family Relationship` fr ON f.name = fr.parent
            LEFT JOIN `tabCRM Student` s ON fr.student = s.name
            LEFT JOIN `tabCRM Guardian` g ON fr.guardian = g.name
            GROUP BY f.name, f.family_code
            ORDER BY f.family_code ASC
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
