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
    forbidden_response
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
        data = frappe.local.form_dict
        article_id = data.get("article_id")

        if not article_id:
            return validation_error_response("Article ID is required", {"article_id": ["Article ID is required"]})

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
    try:
        # Get data from request - try both form_dict and JSON body
        data = frappe.local.form_dict
        frappe.logger().info(f"Initial form_dict data: {data}")
        frappe.logger().info(f"Request method: {frappe.request.method}")
        frappe.logger().info(f"Request content type: {frappe.request.content_type}")

        # Log all form data keys and values for debugging
        if data:
            for key, value in data.items():
                frappe.logger().info(f"Form data {key}: {value} (type: {type(value)})")

        if not data or not data.get('title_en'):
            # Try parsing JSON from request body
            try:
                if frappe.request.data:
                    import json
                    data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                    frappe.logger().info(f"Parsed JSON data: {data}")
            except Exception as e:
                frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        # Override campus_id to ensure user can't create for other campuses
        if isinstance(data, dict):
            data['campus_id'] = campus_id
        else:
            # If data is not a dict (like frappe form_dict), set attribute
            data.campus_id = campus_id

        frappe.logger().info(f"Final data before validation: title_en='{data.get('title_en') if isinstance(data, dict) else getattr(data, 'title_en', None)}', title_vn='{data.get('title_vn') if isinstance(data, dict) else getattr(data, 'title_vn', None)}'")

        # Validate required fields
        def get_field_value(field_name):
            if isinstance(data, dict):
                return data.get(field_name, "")
            else:
                return getattr(data, field_name, "")

        title_en = str(get_field_value("title_en")).strip()
        title_vn = str(get_field_value("title_vn")).strip()

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
            "summary_en": get_field_value("summary_en"),
            "summary_vn": get_field_value("summary_vn"),
            "content_en": get_field_value("content_en"),
            "content_vn": get_field_value("content_vn"),
            "education_stage_ids": get_field_value("education_stage_ids"),
            "featured": get_field_value("featured") or 0,
            "cover_image": cover_image_url or get_field_value("cover_image"),
            "status": get_field_value("status") or "draft"
        })

        # Handle tags
        tag_ids_str = get_field_value("tag_ids")
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
        # Get data from request - try both form_dict and JSON body
        data = frappe.local.form_dict
        frappe.logger().info(f"Initial form_dict data: {data}")
        frappe.logger().info(f"Request method: {frappe.request.method}")
        frappe.logger().info(f"Request content type: {frappe.request.content_type}")

        # Log all form data keys and values for debugging
        if data:
            for key, value in data.items():
                frappe.logger().info(f"Form data {key}: {value} (type: {type(value)})")

        if not data or not data.get('article_id'):
            # Try parsing JSON from request body
            try:
                if frappe.request.data:
                    import json
                    data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                    frappe.logger().info(f"Parsed JSON data: {data}")
            except Exception as e:
                frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")

        # Helper function to get field value from either dict or object
        def get_field_value(field_name):
            if isinstance(data, dict):
                return data.get(field_name, "")
            else:
                return getattr(data, field_name, "")

        article_id = get_field_value("article_id")

        if not article_id:
            return validation_error_response("Article ID is required", {"article_id": ["Article ID is required"]})

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and article.campus_id != campus_id:
            return forbidden_response("You don't have access to this article")

        # Validate required fields for update
        title_en = str(get_field_value("title_en")).strip()
        title_vn = str(get_field_value("title_vn")).strip()

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
            article.title_en = data.title_en
        if "title_vn" in data:
            article.title_vn = data.title_vn
        if "summary_en" in data:
            article.summary_en = data.summary_en
        if "summary_vn" in data:
            article.summary_vn = data.summary_vn
        if "content_en" in data:
            article.content_en = data.content_en
        if "content_vn" in data:
            article.content_vn = data.content_vn
        if "education_stage_ids" in data:
            article.education_stage_ids = data.education_stage_ids
        if "featured" in data:
            article.featured = data.featured
        if cover_image_url:
            article.cover_image = cover_image_url
        elif "cover_image" in data:
            article.cover_image = data.cover_image
        if "status" in data:
            article.status = data.status

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


@frappe.whitelist(allow_guest=False)
def delete_news_article():
    """Delete a news article"""
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

        # Delete the article
        article.delete()

        return success_response(
            message="News article deleted successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("News article not found")
    except Exception as e:
        frappe.logger().error(f"Error deleting news article: {str(e)}")
        return error_response(
            message=f"Failed to delete news article: {str(e)}",
            code="DELETE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
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


@frappe.whitelist(allow_guest=False)
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
