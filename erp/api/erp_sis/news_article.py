# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
    paginated_response
)
import os
import uuid
from PIL import Image, ImageOps
import io
import mimetypes
import base64


def handle_image_upload():
    """Handle image upload for news articles"""
    try:
        # Get file from request.files (proper way to handle file uploads)
        files = frappe.request.files
        if not files or 'cover_image' not in files:
            return None

        uploaded_file = files['cover_image']
        file_name = uploaded_file.filename

        if not file_name:
            frappe.logger().warning("Uploaded file has no filename")
            return None

        # Validate file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/bmp', 'image/webp']
        if uploaded_file.content_type not in allowed_types:
            frappe.logger().error(f"Invalid file type: {uploaded_file.content_type}")
            raise ValueError("Only image files (JPEG, PNG, GIF, BMP, WebP) are allowed")

        # Read file content as bytes
        try:
            file_content = uploaded_file.read()
            frappe.logger().info(f"Successfully read file content, size: {len(file_content)} bytes")
        except Exception as read_error:
            frappe.logger().error(f"Error reading file content: {str(read_error)}")
            raise ValueError("Failed to read uploaded file")

        # Validate file size (max 5MB)
        max_size = 5 * 1024 * 1024  # 5MB
        if len(file_content) > max_size:
            frappe.logger().error(f"File too large: {len(file_content)} bytes")
            raise ValueError("File size must be less than 5MB")

        # Save file directly to avoid encoding issues
        import os
        import uuid

        # Generate new filename with UUID to avoid conflicts
        original_extension = os.path.splitext(file_name)[1] if file_name else '.jpg'
        if not original_extension:
            # Fallback to determine extension from content type
            if uploaded_file and hasattr(uploaded_file, 'content_type'):
                if 'jpeg' in uploaded_file.content_type or 'jpg' in uploaded_file.content_type:
                    original_extension = '.jpg'
                elif 'png' in uploaded_file.content_type:
                    original_extension = '.png'
                elif 'gif' in uploaded_file.content_type:
                    original_extension = '.gif'
                elif 'bmp' in uploaded_file.content_type:
                    original_extension = '.bmp'
                elif 'webp' in uploaded_file.content_type:
                    original_extension = '.webp'
                else:
                    original_extension = '.jpg'

        # Create unique filename
        unique_id = str(uuid.uuid4())
        new_file_name = f"news_article_{unique_id}{original_extension}"

        frappe.logger().info(f"Original filename: {file_name}, New filename: {new_file_name}")

        # Create News_Articles directory if it doesn't exist
        upload_dir = frappe.get_site_path("public", "files", "News_Articles")
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir, exist_ok=True)

        # Save file directly to file system
        file_path = os.path.join(upload_dir, new_file_name)
        try:
            with open(file_path, 'wb') as f:
                f.write(file_content)
            frappe.logger().info(f"Successfully saved file to: {file_path}")
        except Exception as write_error:
            frappe.logger().error(f"Error writing file to disk: {str(write_error)}")
            raise ValueError("Error saving file to disk")

        # Create file URL
        file_url = f"/files/News_Articles/{new_file_name}"

        frappe.logger().info(f"File saved to: {file_path}, URL: {file_url}")

        return file_url

    except Exception as e:
        frappe.logger().error(f"Error handling image upload: {str(e)}")
        raise e


@frappe.whitelist(allow_guest=False)
def get_news_articles():
    """Get news articles with filtering"""
    try:
        data = frappe.local.form_dict

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        frappe.logger().info(f"Current campus_id: {campus_id}")

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Check if SIS News Article doctype exists
        if not frappe.db.exists("DocType", "SIS News Article"):
            frappe.logger().error("SIS News Article DocType does not exist")
            return error_response(
                message="SIS News Article DocType not found",
                code="DOCTYPE_NOT_FOUND"
            )

        # Build filters
        filters = {"campus_id": campus_id}

        # Status filter
        status = data.get("status")
        if status:
            filters["status"] = status

        # Education stage filter
        education_stage_id = data.get("education_stage_id")
        if education_stage_id:
            filters["education_stage_id"] = education_stage_id

        # Tag filter
        tag_ids = data.get("tag_ids")
        if tag_ids:
            if isinstance(tag_ids, str):
                tag_ids = json.loads(tag_ids)
            if tag_ids:
                # Get articles that have any of the specified tags
                articles_with_tags = frappe.db.sql("""
                    SELECT DISTINCT parent
                    FROM `tabSIS News Article Tag`
                    WHERE news_tag_id IN ({})
                """.format(','.join(['%s'] * len(tag_ids))), tag_ids, as_dict=True)

                if articles_with_tags:
                    article_names = [a.parent for a in articles_with_tags]
                    filters["name"] = ["in", article_names]
                else:
                    # No articles found with these tags
                    return list_response(data=[], message="No articles found with specified tags")

        # Pagination
        page = int(data.get("page", 1))
        limit = int(data.get("limit", 20))
        offset = (page - 1) * limit

        frappe.logger().info(f"Using filters: {filters}")

        # Get articles with pagination
        articles = frappe.get_all(
            "SIS News Article",
            fields=[
                "name",
                "title_en",
                "title_vn",
                "summary_en",
                "summary_vn",
                "education_stage_ids",
                "featured",
                "status",
                "cover_image",
                "published_at",
                "published_by",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="published_at desc, modified desc" if status == "published" else "modified desc",
            limit_page_length=limit,
            limit_start=offset
        )

        # Get total count for pagination
        total_count = frappe.db.count("SIS News Article", filters=filters)

        # Enrich articles with tag information
        for article in articles:
            article_tags = frappe.get_all(
                "SIS News Article Tag",
                filters={"parent": article.name},
                fields=["news_tag_id", "tag_name_en", "tag_name_vn", "tag_color"]
            )
            article["tags"] = article_tags

        frappe.logger().info(f"Successfully retrieved {len(articles)} news articles")

        # Return paginated response if there are more pages, otherwise return list response
        if total_count > limit:
            return paginated_response(
                data=articles,
                current_page=page,
                total_count=total_count,
                per_page=limit,
                message="News articles fetched successfully"
            )
        else:
            return list_response(
                data=articles,
                message="News articles fetched successfully"
            )

    except Exception as e:
        frappe.logger().error(f"Error fetching news articles: {str(e)}")
        return error_response(
            message=f"Failed to fetch news articles: {str(e)}",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_news_article():
    """Get a single news article by ID"""
    try:
        # Try multiple sources for article_id
        data = frappe.local.form_dict
        
        # Try from request.form (for POST form-urlencoded)
        article_id = data.get("article_id") or frappe.request.form.get("article_id")
        
        # Try from request.args (for GET query params)
        if not article_id:
            article_id = frappe.request.args.get("article_id")
        
        # Try from JSON body
        if not article_id:
            try:
                json_data = frappe.request.get_json(silent=True)
                if json_data:
                    article_id = json_data.get("article_id")
            except:
                pass
        
        # Return debug info in error response
        if not article_id:
            debug_info = {
                "form_dict": {k: str(v)[:100] for k, v in data.items()},
                "request_form": dict(frappe.request.form) if frappe.request.form else None,
                "request_args": dict(frappe.request.args) if frappe.request.args else None,
                "request_data": str(frappe.request.data[:200]) if frappe.request.data else None,
                "content_type": frappe.request.content_type
            }
            return validation_error_response(
                f"Article ID is required. Debug: {debug_info}", 
                {"article_id": ["Article ID is required"]}
            )

        # Get current user's campus information
        campus_id = get_current_campus_from_context()

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if user has access to this campus
        if campus_id and article.campus_id != campus_id:
            return forbidden_response("You don't have access to this article")

        # Get tags
        article_tags = frappe.get_all(
            "SIS News Article Tag",
            filters={"parent": article.name},
            fields=["news_tag_id", "tag_name_en", "tag_name_vn", "tag_color"]
        )

        article_data = {
            "name": article.name,
            "title_en": article.title_en,
            "title_vn": article.title_vn,
            "summary_en": article.summary_en,
            "summary_vn": article.summary_vn,
            "content_en": article.content_en,
            "content_vn": article.content_vn,
            "education_stage_ids": article.education_stage_ids,
            "featured": article.featured,
            "status": article.status,
            "cover_image": article.cover_image,
            "published_at": article.published_at,
            "published_by": article.published_by,
            "campus_id": article.campus_id,
            "tags": article_tags,
            "created_at": article.created_at,
            "created_by": article.created_by,
            "updated_at": article.updated_at,
            "updated_by": article.updated_by
        }

        return single_item_response(
            data=article_data,
            message="News article fetched successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("News article not found")
    except Exception as e:
        frappe.logger().error(f"Error fetching news article: {str(e)}")
        return error_response(
            message=f"Failed to fetch news article: {str(e)}",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_news_article():
    """Create a new news article"""
    logs = []  # Collect logs to return in response
    
    try:
        # IMPORTANT: Check for files first to detect multipart form data
        files = frappe.request.files
        has_files = files and 'cover_image' in files
        
        logs.append(f"Request method: {frappe.request.method}")
        logs.append(f"Request content type: {frappe.request.content_type}")
        logs.append(f"Has files: {has_files}")
        logs.append(f"Request files keys: {list(files.keys()) if files else 'None'}")

        # Get data from request - handle multipart form data properly
        data = {}
        
        # Check if request is multipart (either has files OR content-type is multipart)
        is_multipart = (frappe.request.content_type and 'multipart/form-data' in frappe.request.content_type)
        
        logs.append(f"Is multipart: {is_multipart}")
        
        # Try multiple methods to get form data when request is multipart
        if is_multipart:
            # Method 1: Try frappe.request.form (Werkzeug's ImmutableMultiDict)
            if hasattr(frappe.request, 'form') and frappe.request.form:
                frappe.logger().info(f"Using frappe.request.form, keys: {list(frappe.request.form.keys())}")
                for key in frappe.request.form.keys():
                    data[key] = frappe.request.form.get(key)
                    frappe.logger().info(f"request.form[{key}] = {data[key]}")
            
            # Method 2: If request.form is empty, try form_dict
            if not data:
                frappe.logger().info("request.form is empty, trying form_dict")
                data = dict(frappe.local.form_dict)
                frappe.logger().info(f"form_dict keys: {list(data.keys())}")
            
            # Method 3: Last resort - try werkzeug parser on fresh stream
            if not data or not data.get('title_en'):
                frappe.logger().info("form_dict is empty, trying werkzeug parser")
                try:
                    from werkzeug.formparser import parse_form_data
                    stream, form, files_parsed = parse_form_data(frappe.request.environ, silent=False)
                    
                    # Convert form data to dict
                    for key in form.keys():
                        data[key] = form.get(key)
                        frappe.logger().info(f"werkzeug form[{key}] = {data[key]}")
                        
                    frappe.logger().info(f"Parsed multipart form data using werkzeug: {list(data.keys())}")
                    
                except Exception as e:
                    frappe.logger().error(f"Failed to parse multipart form data: {str(e)}")
                    import traceback
                    frappe.logger().error(traceback.format_exc())
        else:
            # No files, use standard parsing
            data = dict(frappe.local.form_dict)
            frappe.logger().info(f"Using standard form_dict: {list(data.keys())}")
            
            # If form_dict is empty, try JSON body
            if not data or not data.get('title_en'):
                try:
                    if frappe.request.data:
                        data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                        frappe.logger().info(f"Parsed JSON data: {list(data.keys())}")
                except Exception as e:
                    frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")
        
        # Log final parsed data for debugging
        frappe.logger().info(f"Final parsed data keys: {list(data.keys())}")
        for key, value in data.items():
            if key != 'cmd':  # Skip cmd to reduce noise
                frappe.logger().info(f"Form data {key}: {value[:100] if isinstance(value, str) and len(value) > 100 else value} (type: {type(value).__name__})")

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        # Override campus_id to ensure user can't create for other campuses
        data['campus_id'] = campus_id

        # Validate required fields
        title_en = str(data.get("title_en", "")).strip()
        title_vn = str(data.get("title_vn", "")).strip()
        
        frappe.logger().info(f"Final data before validation: title_en='{title_en}', title_vn='{title_vn}'")

        if not title_en or not title_vn:
            frappe.logger().error(f"Validation failed: title_en='{title_en}', title_vn='{title_vn}'")
            return validation_error_response("Both English and Vietnamese titles are required", {"title": ["Both English and Vietnamese titles are required"]})

        # Handle image upload
        cover_image_url = None
        try:
            cover_image_url = handle_image_upload()
            if cover_image_url:
                frappe.logger().info(f"Image uploaded successfully: {cover_image_url}")
        except ValueError as e:
            frappe.logger().error(f"Image upload validation error: {str(e)}")
            return validation_error_response(str(e), {"cover_image": [str(e)]})
        except Exception as e:
            frappe.logger().error(f"Unexpected error during image upload: {str(e)}")
            return validation_error_response("Failed to upload image", {"cover_image": ["Failed to upload image"]})

        # Create the article
        article = frappe.get_doc({
            "doctype": "SIS News Article",
            "campus_id": campus_id,
            "title_en": title_en,
            "title_vn": title_vn,
            "summary_en": data.get("summary_en", ""),
            "summary_vn": data.get("summary_vn", ""),
            "content_en": data.get("content_en", ""),
            "content_vn": data.get("content_vn", ""),
            "education_stage_ids": data.get("education_stage_ids", ""),
            "featured": data.get("featured") or 0,
            "cover_image": cover_image_url or data.get("cover_image", ""),
            "status": data.get("status", "draft")
        })

        # Handle tags
        tag_ids_str = data.get("tag_ids")
        if tag_ids_str:
            try:
                if isinstance(tag_ids_str, str):
                    tag_ids = json.loads(tag_ids_str)
                else:
                    tag_ids = tag_ids_str

                if tag_ids:
                    for tag_id in tag_ids:
                        # Validate tag exists and belongs to same campus
                        tag_doc = frappe.get_doc("SIS News Tag", tag_id)
                        if tag_doc.campus_id != campus_id:
                            return validation_error_response(f"Tag '{tag_doc.name_en}' belongs to different campus", {"tags": [f"Tag '{tag_doc.name_en}' belongs to different campus"]})

                        article.append("tags", {
                            "news_tag_id": tag_id
                        })
            except json.JSONDecodeError as e:
                frappe.logger().error(f"Failed to parse tag_ids JSON: {tag_ids_str}, error: {str(e)}")
                return validation_error_response("Invalid tag_ids format", {"tag_ids": ["Invalid JSON format"]})

        article.insert()

        # Get the created article data
        created_article = frappe.get_doc("SIS News Article", article.name)

        # Get tags
        article_tags = frappe.get_all(
            "SIS News Article Tag",
            filters={"parent": created_article.name},
            fields=["news_tag_id", "tag_name_en", "tag_name_vn", "tag_color"]
        )

        article_data = {
            "name": created_article.name,
            "title_en": created_article.title_en,
            "title_vn": created_article.title_vn,
            "summary_en": created_article.summary_en,
            "summary_vn": created_article.summary_vn,
            "content_en": created_article.content_en,
            "content_vn": created_article.content_vn,
            "education_stage_ids": created_article.education_stage_ids,
            "featured": created_article.featured,
            "status": created_article.status,
            "cover_image": created_article.cover_image,
            "published_at": created_article.published_at,
            "published_by": created_article.published_by,
            "campus_id": created_article.campus_id,
            "tags": article_tags,
            "created_at": created_article.created_at,
            "created_by": created_article.created_by,
            "updated_at": created_article.updated_at,
            "updated_by": created_article.updated_by
        }

        return single_item_response(
            data=article_data,
            message="News article created successfully"
        )

    except frappe.DuplicateEntryError:
        return validation_error_response("An article with this title already exists", {"title": ["An article with this title already exists"]})
    except Exception as e:
        frappe.logger().error(f"Error creating news article: {str(e)}")
        return error_response(
            message=f"Failed to create news article: {str(e)}",
            code="CREATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_news_article():
    """Update an existing news article"""
    try:
        # IMPORTANT: Check for files first to detect multipart form data
        files = frappe.request.files
        has_files = files and 'cover_image' in files

        # Get data from request - handle multipart form data properly
        data = {}
        
        # Check if request is multipart (either has files OR content-type is multipart)
        is_multipart = (frappe.request.content_type and 'multipart/form-data' in frappe.request.content_type)
        
        frappe.logger().info(f"Is multipart: {is_multipart}, Has files: {has_files}")
        
        # Try multiple methods to get form data when request is multipart
        if is_multipart:
            # Method 1: Try frappe.request.form (Werkzeug's ImmutableMultiDict)
            if hasattr(frappe.request, 'form') and frappe.request.form:
                frappe.logger().info(f"Using frappe.request.form, keys: {list(frappe.request.form.keys())}")
                for key in frappe.request.form.keys():
                    data[key] = frappe.request.form.get(key)
                    frappe.logger().info(f"request.form[{key}] = {data[key]}")
            
            # Method 2: If request.form is empty, try form_dict
            if not data:
                frappe.logger().info("request.form is empty, trying form_dict")
                data = dict(frappe.local.form_dict)
                frappe.logger().info(f"form_dict keys: {list(data.keys())}")
            
            # Method 3: Last resort - try werkzeug parser on fresh stream
            if not data or not data.get('title_en'):
                frappe.logger().info("form_dict is empty, trying werkzeug parser")
                try:
                    from werkzeug.formparser import parse_form_data
                    stream, form, files_parsed = parse_form_data(frappe.request.environ, silent=False)
                    
                    # Convert form data to dict
                    for key in form.keys():
                        data[key] = form.get(key)
                        frappe.logger().info(f"werkzeug form[{key}] = {data[key]}")
                        
                    frappe.logger().info(f"Parsed multipart form data using werkzeug: {list(data.keys())}")
                    
                except Exception as e:
                    frappe.logger().error(f"Failed to parse multipart form data: {str(e)}")
                    import traceback
                    frappe.logger().error(traceback.format_exc())
        else:
            # No files, use standard parsing
            data = dict(frappe.local.form_dict)
            frappe.logger().info(f"Using standard form_dict: {list(data.keys())}")
            
            # If form_dict is empty, try JSON body
            if not data or not data.get('article_id'):
                try:
                    if frappe.request.data:
                        data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                        frappe.logger().info(f"Parsed JSON data: {list(data.keys())}")
                except Exception as e:
                    frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")
        
        # Log final parsed data for debugging
        frappe.logger().info(f"Final parsed data keys: {list(data.keys())}")
        for key, value in data.items():
            if key != 'cmd':  # Skip cmd to reduce noise
                frappe.logger().info(f"Form data {key}: {value[:100] if isinstance(value, str) and len(value) > 100 else value} (type: {type(value).__name__})")

        article_id = data.get("article_id")

        if not article_id:
            return validation_error_response("Article ID is required", {"article_id": ["Article ID is required"]})

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and article.campus_id != campus_id:
            return forbidden_response("You don't have access to this article")

        # Validate required fields for update
        title_en = str(data.get("title_en", "")).strip()
        title_vn = str(data.get("title_vn", "")).strip()
        
        frappe.logger().info(f"Validating update: title_en='{title_en}', title_vn='{title_vn}'")

        if not title_en or not title_vn:
            frappe.logger().error(f"Validation failed: title_en='{title_en}', title_vn='{title_vn}'")
            return validation_error_response("Both English and Vietnamese titles are required", {"title": ["Both English and Vietnamese titles are required"]})

        # Handle image upload
        cover_image_url = None
        try:
            cover_image_url = handle_image_upload()
            if cover_image_url:
                frappe.logger().info(f"Image uploaded successfully: {cover_image_url}")
        except ValueError as e:
            frappe.logger().error(f"Image upload validation error: {str(e)}")
            return validation_error_response(str(e), {"cover_image": [str(e)]})
        except Exception as e:
            frappe.logger().error(f"Unexpected error during image upload: {str(e)}")
            return validation_error_response("Failed to upload image", {"cover_image": ["Failed to upload image"]})

        # Update fields
        if "title_en" in data:
            article.title_en = data["title_en"]
        if "title_vn" in data:
            article.title_vn = data["title_vn"]
        if "summary_en" in data:
            article.summary_en = data["summary_en"]
        if "summary_vn" in data:
            article.summary_vn = data["summary_vn"]
        if "content_en" in data:
            article.content_en = data["content_en"]
        if "content_vn" in data:
            article.content_vn = data["content_vn"]
        if "education_stage_ids" in data:
            article.education_stage_ids = data["education_stage_ids"]
        if "featured" in data:
            article.featured = data["featured"]
        if cover_image_url:
            article.cover_image = cover_image_url
        elif "cover_image" in data:
            article.cover_image = data["cover_image"]
        if "status" in data:
            article.status = data["status"]

        # Handle tags update
        tag_ids = data.get("tag_ids")
        if tag_ids is not None:  # Allow empty array to clear tags
            if isinstance(tag_ids, str):
                tag_ids = json.loads(tag_ids)

            # Clear existing tags
            article.set("tags", [])

            # Add new tags
            if tag_ids:
                for tag_id in tag_ids:
                    # Validate tag exists and belongs to same campus
                    tag_doc = frappe.get_doc("SIS News Tag", tag_id)
                    if tag_doc.campus_id != article.campus_id:
                        return validation_error_response(f"Tag '{tag_doc.name_en}' belongs to different campus", {"tags": [f"Tag '{tag_doc.name_en}' belongs to different campus"]})

                    article.append("tags", {
                        "news_tag_id": tag_id
                    })

        article.save()

        # Get updated article data
        updated_article = frappe.get_doc("SIS News Article", article.name)

        # Get tags
        article_tags = frappe.get_all(
            "SIS News Article Tag",
            filters={"parent": updated_article.name},
            fields=["news_tag_id", "tag_name_en", "tag_name_vn", "tag_color"]
        )

        article_data = {
            "name": updated_article.name,
            "title_en": updated_article.title_en,
            "title_vn": updated_article.title_vn,
            "summary_en": updated_article.summary_en,
            "summary_vn": updated_article.summary_vn,
            "content_en": updated_article.content_en,
            "content_vn": updated_article.content_vn,
            "education_stage_ids": updated_article.education_stage_ids,
            "featured": updated_article.featured,
            "status": updated_article.status,
            "cover_image": updated_article.cover_image,
            "published_at": updated_article.published_at,
            "published_by": updated_article.published_by,
            "campus_id": updated_article.campus_id,
            "tags": article_tags,
            "created_at": updated_article.created_at,
            "created_by": updated_article.created_by,
            "updated_at": updated_article.updated_at,
            "updated_by": updated_article.updated_by
        }

        return single_item_response(
            data=article_data,
            message="News article updated successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("News article not found")
    except frappe.DuplicateEntryError:
        return validation_error_response("An article with this title already exists", {"title": ["An article with this title already exists"]})
    except Exception as e:
        frappe.logger().error(f"Error updating news article: {str(e)}")
        return error_response(
            message=f"Failed to update news article: {str(e)}",
            code="UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def delete_news_article():
    """Delete a news article"""
    logs = []

    try:
        logs.append(f"DELETE API CALLED - User: {frappe.session.user}")
        logs.append(f"Request method: {frappe.request.method}")

        data = frappe.local.form_dict
        logs.append(f"form_dict keys: {list(data.keys())}")

        article_id = data.get("article_id")
        logs.append(f"article_id from form_dict: '{article_id}'")

        # Try from request.args (for GET query params)
        if not article_id:
            article_id = frappe.request.args.get("article_id")
            logs.append(f"article_id from query args: '{article_id}'")

        if not article_id:
            logs.append("ERROR: Article ID is required")
            return validation_error_response("Article ID is required", {"article_id": ["Article ID is required"]})

        logs.append(f"FINAL article_id: '{article_id}'")

        # Verify article exists BEFORE deletion
        try:
            article_check = frappe.get_doc("SIS News Article", article_id)
            logs.append(f"Article exists: {article_check.name}, campus: {article_check.campus_id}")
        except frappe.DoesNotExistError:
            logs.append(f"ERROR: Article {article_id} does not exist before deletion")
            return error_response(
                message="News article not found",
                code="NOT_FOUND",
                logs=logs
            )

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        logs.append(f"User campus: '{campus_id}', Article campus: '{article_check.campus_id}'")

        if campus_id and article_check.campus_id != campus_id:
            logs.append("ERROR: Campus access denied")
            return error_response(
                message="You don't have access to this article",
                code="FORBIDDEN",
                logs=logs
            )

        logs.append("Access granted - proceeding with deletion")

        # Get fresh article instance for deletion
        article = frappe.get_doc("SIS News Article", article_id)
        cover_image = article.cover_image
        logs.append(f"Article cover_image: '{cover_image}'")

        # Delete using frappe.delete_doc
        try:
            logs.append("Calling frappe.delete_doc...")
            frappe.delete_doc("SIS News Article", article_id, ignore_permissions=True, force=True)
            logs.append("frappe.delete_doc completed successfully")

            # IMMEDIATE VERIFICATION - check if still exists
            try:
                still_exists = frappe.db.exists("SIS News Article", article_id)
                logs.append(f"Immediate verification - exists in DB: {still_exists}")

                if still_exists:
                    logs.append("ERROR: Article still exists in database after delete!")
                    return error_response(
                        message="Article deletion failed - still exists in database",
                        code="DELETE_ERROR",
                        logs=logs
                    )
                else:
                    logs.append("SUCCESS: Article confirmed deleted from database")

            except Exception as verify_error:
                logs.append(f"Verification check error: {str(verify_error)}")

            # Try to cleanup cover image file if it exists
            if cover_image and cover_image.startswith("/files/News_Articles/"):
                try:
                    import os
                    file_path = frappe.get_site_path("public") + cover_image
                    logs.append(f"Attempting to delete file: {file_path}")
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logs.append("Cover image file deleted successfully")
                    else:
                        logs.append("Cover image file not found")
                except Exception as file_error:
                    logs.append(f"Failed to delete cover image file: {str(file_error)}")

            logs.append("DELETION COMPLETED SUCCESSFULLY")
            return success_response(
                message="News article deleted successfully",
                logs=logs
            )

        except Exception as delete_error:
            logs.append(f"DELETE OPERATION FAILED: {str(delete_error)}")
            frappe.logger().error(f"Delete operation failed: {str(delete_error)}")
            import traceback
            logs.append(f"Delete traceback: {traceback.format_exc()}")
            return error_response(
                message=f"Failed to delete article: {str(delete_error)}",
                code="DELETE_ERROR",
                logs=logs
            )

    except frappe.DoesNotExistError:
        logs.append("Article not found during initial fetch")
        return error_response(
            message="News article not found",
            code="NOT_FOUND",
            logs=logs
        )
    except Exception as e:
        logs.append(f"Unexpected error: {str(e)}")
        frappe.logger().error(f"Error deleting news article: {str(e)}")
        import traceback
        logs.append(f"Full traceback: {traceback.format_exc()}")
        return error_response(
            message=f"Failed to delete news article: {str(e)}",
            code="DELETE_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def publish_news_article():
    """Publish a draft article"""
    try:
        data = frappe.local.form_dict
        article_id = data.get("article_id")

        if not article_id:
            return validation_error_response("Article ID is required", {"article_id": ["Article ID is required"]})

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and article.campus_id != campus_id:
            return forbidden_response("You don't have access to this article")

        # Update status to published
        article.status = "published"
        article.save()

        return success_response(
            message="News article published successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("News article not found")
    except Exception as e:
        frappe.logger().error(f"Error publishing news article: {str(e)}")
        return error_response(
            message=f"Failed to publish news article: {str(e)}",
            code="PUBLISH_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def unpublish_news_article():
    """Unpublish an article (change back to draft)"""
    try:
        data = frappe.local.form_dict
        article_id = data.get("article_id")

        if not article_id:
            return validation_error_response("Article ID is required", {"article_id": ["Article ID is required"]})

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and article.campus_id != campus_id:
            return forbidden_response("You don't have access to this article")

        # Update status to draft
        article.status = "draft"
        article.save()

        return success_response(
            message="News article unpublished successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("News article not found")
    except Exception as e:
        frappe.logger().error(f"Error unpublishing news article: {str(e)}")
        return error_response(
            message=f"Failed to unpublish news article: {str(e)}",
            code="UNPUBLISH_ERROR"
        )

@frappe.whitelist(allow_guest=False, methods=['POST'])
def upload_content_image():
    """
    Upload image for article content (markdown content images)
    - Converts to WebP for optimization
    - Resizes if too large (max width 1920px)
    - Saves to /files/News_Articles/content/
    """
    logs = []
    
    try:
        # Validate user authentication
        if frappe.session.user == "Guest":
            logs.append("Guest user attempted to upload content image")
            return forbidden_response(
                message="Vui lòng đăng nhập để tải ảnh lên",
                code="GUEST_NOT_ALLOWED"
            )
        
        logs.append(f"Upload content image called by user: {frappe.session.user}")
        
        # Get uploaded file from request
        files = frappe.request.files
        if not files or 'image' not in files:
            logs.append("No image file found in request")
            return validation_error_response(
                message="Không tìm thấy file ảnh",
                errors={"image": ["File ảnh là bắt buộc"]},
                code="MISSING_IMAGE_FILE"
            )
        
        image_file = files['image']
        logs.append(f"Received file: {image_file.filename}")
        
        # Validate file type
        allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
        file_extension = image_file.filename.rsplit('.', 1)[1].lower() if '.' in image_file.filename else ''
        
        if file_extension not in allowed_extensions:
            error_msg = f"Loại file không hợp lệ. Chỉ chấp nhận: {', '.join(allowed_extensions)}"
            logs.append(f"Invalid file type: {file_extension}")
            return validation_error_response(
                message=error_msg,
                errors={"image": [error_msg]},
                code="INVALID_FILE_TYPE"
            )
        
        logs.append(f"File extension validated: {file_extension}")
        
        # Read file content
        file_content = image_file.read()
        
        # Validate file size (max 10MB for content images)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            error_msg = "Kích thước file quá lớn. Tối đa cho phép: 10MB"
            logs.append(f"File too large: {len(file_content)} bytes")
            return validation_error_response(
                message=error_msg,
                errors={"image": [error_msg]},
                code="FILE_TOO_LARGE"
            )
        
        logs.append(f"Original file size: {len(file_content)} bytes ({len(file_content) / 1024 / 1024:.2f} MB)")
        
        # Process and convert image to WebP
        image_url, compression_info = process_content_image(file_content, image_file.filename, logs)
        
        logs.append(f"Image uploaded successfully: {image_url}")
        logs.append(f"Compression info: {compression_info}")
        
        # Return success response with image URL
        return success_response(
            data={
                "image_url": image_url,
                "compression_info": compression_info
            },
            message="Tải ảnh lên thành công",
            logs=logs
        )
    
    except Exception as e:
        logs.append(f"Upload content image error: {str(e)}")
        frappe.log_error(f"Upload content image error: {str(e)}", "News Article Content Image Upload")
        return error_response(
            message=f"Lỗi khi tải ảnh lên: {str(e)}",
            code="UPLOAD_ERROR",
            logs=logs
        )


def process_content_image(file_content, original_filename, logs=None):
    """
    Process and convert content image to WebP with optimization
    - Auto-orient using EXIF data
    - Resize if width > 1920px
    - Convert to WebP format with quality 90
    """
    if logs is None:
        logs = []
    
    try:
        original_size = len(file_content)
        
        # Open image with PIL
        image = Image.open(io.BytesIO(file_content))
        logs.append(f"Image opened - Size: {image.size}, Mode: {image.mode}, Format: {image.format}")
        
        # Normalize orientation using EXIF data
        try:
            image = ImageOps.exif_transpose(image)
            logs.append("EXIF orientation normalized")
        except Exception as exif_error:
            logs.append(f"EXIF transpose skipped: {str(exif_error)}")
        
        # Convert to RGB if necessary (WebP supports RGB and RGBA)
        if image.mode not in ['RGB', 'RGBA']:
            original_mode = image.mode
            image = image.convert('RGB')
            logs.append(f"Converted image mode from {original_mode} to RGB")
        
        # Resize if width exceeds maximum (1920px for content images)
        max_width = 1920
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            original_size_str = f"{image.width}x{image.height}"
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
            logs.append(f"Resized image from {original_size_str} to {image.width}x{image.height}")
        
        # Generate unique filename with UUID
        file_id = str(uuid.uuid4())
        name_no_ext = os.path.splitext(original_filename)[0] if '.' in original_filename else original_filename
        # Sanitize filename - remove special characters
        name_no_ext = "".join(c for c in name_no_ext if c.isalnum() or c in ('-', '_'))
        final_filename = f"content_{name_no_ext}_{file_id}.webp"
        
        logs.append(f"Generated filename: {final_filename}")
        
        # Convert to WebP format
        output = io.BytesIO()
        # quality=90: Balance between quality and file size
        # method=6: Maximum compression effort
        # lossless=False: Allow lossy compression for better size reduction
        image.save(output, format='WEBP', quality=90, method=6, lossless=False)
        
        processed_content = output.getvalue()
        compressed_size = len(processed_content)
        
        # Calculate compression ratio
        compression_ratio = (1 - compressed_size / original_size) * 100
        
        compression_info = {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "compression_ratio": round(compression_ratio, 1),
            "original_format": os.path.splitext(original_filename)[1].upper() if '.' in original_filename else 'UNKNOWN',
            "final_format": "WEBP",
            "dimensions": f"{image.width}x{image.height}"
        }
        
        logs.append(f"WebP conversion complete: {original_size} bytes -> {compressed_size} bytes ({compression_ratio:.1f}% reduction)")
        
        # Create upload directory if it doesn't exist
        upload_dir = frappe.get_site_path("public", "files", "News_Articles", "content")
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir, exist_ok=True)
            logs.append(f"Created upload directory: {upload_dir}")
        
        # Save file to disk
        file_path = os.path.join(upload_dir, final_filename)
        with open(file_path, 'wb') as f:
            f.write(processed_content)
        
        logs.append(f"File saved to: {file_path}")
        
        # Create public URL
        image_url = f"/files/News_Articles/content/{final_filename}"
        
        frappe.logger().info(f"Content image processed successfully: {original_filename} -> {final_filename}")
        
        return image_url, compression_info
    
    except Exception as e:
        logs.append(f"Content image processing error: {str(e)}")
        frappe.log_error(f"Content image processing error: {str(e)}", "News Article Content Image Processing")
        raise e
