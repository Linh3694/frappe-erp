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
    not_found_response
)


@frappe.whitelist(allow_guest=False)
def get_news_articles():
    """Get published news articles for parent portal with filtering"""
    try:
        data = frappe.local.form_dict

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        frappe.logger().info(f"Parent portal - Current campus_id: {campus_id}")

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Check if SIS News Article doctype exists
        if not frappe.db.exists("DocType", "SIS News Article"):
            frappe.logger().error("SIS News Article DocType does not exist")
            return error_response(
                message="News system not available",
                code="DOCTYPE_NOT_FOUND"
            )

        # Build filters - only published articles
        filters = {
            "campus_id": campus_id,
            "status": "published"
        }

        # Student ID for education stage filtering
        student_id = data.get("student_id")
        student_education_stage_id = None
        if student_id:
            # Get student's education stage
            student = frappe.get_doc("SIS Student", student_id)
            if student.enrollment_status == "enrolled" and student.class_id:
                class_doc = frappe.get_doc("SIS Class", student.class_id)
                if class_doc.education_stage_id:
                    student_education_stage_id = class_doc.education_stage_id

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
        limit = int(data.get("limit", 10))
        offset = (page - 1) * limit

        frappe.logger().info(f"Parent portal - Using filters: {filters}")

        # Get published articles with pagination
        articles = frappe.get_all(
            "SIS News Article",
            fields=[
                "name",
                "title_en",
                "title_vn",
                "summary_en",
                "summary_vn",
                "education_stage_ids",
                "cover_image",
                "published_at",
                "published_by"
            ],
            filters=filters,
            order_by="published_at desc",
            limit_page_length=limit,
            limit_start=offset
        )

        # Get total count for pagination
        total_count = frappe.db.count("SIS News Article", filters=filters)

        # Enrich articles with tag information and filter by education stage
        filtered_articles = []
        for article in articles:
            article_tags = frappe.get_all(
                "SIS News Article Tag",
                filters={"parent": article.name},
                fields=["news_tag_id", "tag_name_en", "tag_name_vn", "tag_color"]
            )
            article["tags"] = article_tags

            # Filter by student's education stage if provided
            should_include = True
            if student_education_stage_id:
                try:
                    education_stage_ids = json.loads(article.education_stage_ids or "[]")
                    should_include = student_education_stage_id in education_stage_ids
                except:
                    should_include = False  # If parsing fails, exclude the article

            if should_include:
                # Get education stage names for display
                try:
                    education_stage_ids = json.loads(article.education_stage_ids or "[]")
                    if education_stage_ids:
                        stages_info = []
                        for stage_id in education_stage_ids[:2]:  # Show max 2 stages
                            try:
                                stage = frappe.get_doc("SIS Education Stage", stage_id)
                                stages_info.append(f"{stage.title_en}")
                            except:
                                pass
                        if stages_info:
                            article["education_stage_name_en"] = ", ".join(stages_info)
                        if len(education_stage_ids) > 2:
                            article["education_stage_name_en"] += f" +{len(education_stage_ids) - 2}"
                except:
                    pass

                filtered_articles.append(article)

        # Apply pagination to filtered results
        start_index = (page - 1) * limit
        end_index = start_index + limit
        paginated_articles = filtered_articles[start_index:end_index]

        frappe.logger().info(f"Parent portal - Successfully retrieved {len(filtered_articles)} filtered news articles")

        return list_response(
            data=paginated_articles,
            message="News articles fetched successfully",
            pagination={
                "page": page,
                "limit": limit,
                "total": len(filtered_articles),
                "total_pages": (len(filtered_articles) + limit - 1) // limit
            }
        )

    except Exception as e:
        frappe.logger().error(f"Parent portal - Error fetching news articles: {str(e)}")
        return error_response(
            message="Failed to fetch news articles",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_news_article():
    """Get a single published news article by ID for parent portal"""
    try:
        data = frappe.local.form_dict
        article_id = data.get("article_id")

        if not article_id:
            return validation_error_response("Article ID is required")

        # Get current user's campus information
        campus_id = get_current_campus_from_context()

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if article is published and user has access to this campus
        if article.status != "published":
            return not_found_response("Article not found")

        if campus_id and article.campus_id != campus_id:
            return not_found_response("Article not found")

        # Get tags
        article_tags = frappe.get_all(
            "SIS News Article Tag",
            filters={"parent": article.name},
            fields=["news_tag_id", "tag_name_en", "tag_name_vn", "tag_color"]
        )

        # Get education stage names
        education_stage_name_en = None
        education_stage_name_vn = None
        if article.education_stage_ids:
            try:
                education_stage_ids = json.loads(article.education_stage_ids or "[]")
                if education_stage_ids:
                    stages_info_en = []
                    stages_info_vn = []
                    for stage_id in education_stage_ids:
                        try:
                            stage = frappe.get_doc("SIS Education Stage", stage_id)
                            stages_info_en.append(stage.title_en)
                            stages_info_vn.append(stage.title_vn)
                        except:
                            pass
                    if stages_info_en:
                        education_stage_name_en = ", ".join(stages_info_en)
                    if stages_info_vn:
                        education_stage_name_vn = ", ".join(stages_info_vn)
            except:
                pass

        article_data = {
            "name": article.name,
            "title_en": article.title_en,
            "title_vn": article.title_vn,
            "summary_en": article.summary_en,
            "summary_vn": article.summary_vn,
            "content_en": article.content_en,
            "content_vn": article.content_vn,
            "education_stage_ids": json.loads(article.education_stage_ids or "[]"),
            "education_stage_name_en": education_stage_name_en,
            "education_stage_name_vn": education_stage_name_vn,
            "cover_image": article.cover_image,
            "published_at": article.published_at,
            "published_by": article.published_by,
            "tags": article_tags
        }

        return single_item_response(
            data=article_data,
            message="News article fetched successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("Article not found")
    except Exception as e:
        frappe.logger().error(f"Parent portal - Error fetching news article: {str(e)}")
        return error_response(
            message="Failed to fetch news article",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_news_tags():
    """Get active news tags for current campus (parent portal)"""
    try:
        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        frappe.logger().info(f"Parent portal - Current campus_id: {campus_id}")

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Check if SIS News Tag doctype exists
        if not frappe.db.exists("DocType", "SIS News Tag"):
            frappe.logger().error("SIS News Tag DocType does not exist")
            return error_response(
                message="News system not available",
                code="DOCTYPE_NOT_FOUND"
            )

        filters = {"campus_id": campus_id, "is_active": 1}
        frappe.logger().info(f"Parent portal - Using filters: {filters}")

        # Get active news tags
        tags = frappe.get_all(
            "SIS News Tag",
            fields=[
                "name",
                "name_en",
                "name_vn",
                "color"
            ],
            filters=filters,
            order_by="name_en asc"
        )

        frappe.logger().info(f"Parent portal - Successfully retrieved {len(tags)} active news tags")

        return list_response(
            data=tags,
            message="News tags fetched successfully"
        )

    except Exception as e:
        frappe.logger().error(f"Parent portal - Error fetching news tags: {str(e)}")
        return error_response(
            message="Failed to fetch news tags",
            code="FETCH_ERROR"
        )
