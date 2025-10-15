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
            return validation_error_response("Article ID is required")

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
        data = frappe.local.form_dict

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        # Override campus_id to ensure user can't create for other campuses
        data.campus_id = campus_id

        # Validate required fields
        if not data.get("title_en") or not data.get("title_vn"):
            return validation_error_response("Both English and Vietnamese titles are required")

        # Create the article
        article = frappe.get_doc({
            "doctype": "SIS News Article",
            "campus_id": campus_id,
            "title_en": data.get("title_en"),
            "title_vn": data.get("title_vn"),
            "summary_en": data.get("summary_en"),
            "summary_vn": data.get("summary_vn"),
            "content_en": data.get("content_en"),
            "content_vn": data.get("content_vn"),
            "education_stage_ids": data.get("education_stage_ids"),
            "featured": data.get("featured", 0),
            "cover_image": data.get("cover_image"),
            "status": data.get("status", "draft")
        })

        # Handle tags
        tag_ids = data.get("tag_ids")
        if tag_ids:
            if isinstance(tag_ids, str):
                tag_ids = json.loads(tag_ids)

            if tag_ids:
                for tag_id in tag_ids:
                    # Validate tag exists and belongs to same campus
                    tag_doc = frappe.get_doc("SIS News Tag", tag_id)
                    if tag_doc.campus_id != campus_id:
                        return validation_error_response(f"Tag '{tag_doc.name_en}' belongs to different campus")

                    article.append("tags", {
                        "news_tag_id": tag_id
                    })

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
        return validation_error_response("An article with this title already exists")
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
        data = frappe.local.form_dict
        article_id = data.get("article_id")

        if not article_id:
            return validation_error_response("Article ID is required")

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and article.campus_id != campus_id:
            return forbidden_response("You don't have access to this article")

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
        if "cover_image" in data:
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
                        return validation_error_response(f"Tag '{tag_doc.name_en}' belongs to different campus")

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
        return validation_error_response("An article with this title already exists")
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
            return validation_error_response("Article ID is required")

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
            return validation_error_response("Article ID is required")

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
            return validation_error_response("Article ID is required")

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
