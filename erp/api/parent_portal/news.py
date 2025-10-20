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


@frappe.whitelist(allow_guest=True)
def get_news_articles():
    """Get published news articles for parent portal with filtering"""
    try:
        data = frappe.local.form_dict
        
        # Debug: Log ALL incoming params
        frappe.logger().info(f"📰 [News API] Received form_dict: {data}")
        frappe.logger().info(f"📰 [News API] student_id from form_dict: {data.get('student_id')}")

        campus_id = data.get("campus_id")
            
        frappe.logger().info(f"Parent portal - Campus_id from params: {data.get('campus_id')}, user: {frappe.session.user}, final campus_id: {campus_id}")

        # Check if SIS News Article doctype exists
        if not frappe.db.exists("DocType", "SIS News Article"):
            frappe.logger().error("SIS News Article DocType does not exist")
            return error_response(
                message="News system not available",
                code="DOCTYPE_NOT_FOUND"
            )

        # Build filters - only published articles
        filters = {
            "status": "published"
        }
        
        # Add campus filter only if campus_id is provided
        if campus_id:
            filters["campus_id"] = campus_id
        
        # Log filters for debugging
        backend_log = f"Fetching news with filters={filters}"
        frappe.logger().info(f"Parent portal - {backend_log}")

        # Student ID for education stage filtering
        student_id = data.get("student_id")
        student_education_stage_id = None
        if student_id:
            try:
                # Get student's education stage through class -> grade -> stage
                # Path: Student -> Class -> Education Grade -> Education Stage
                student = frappe.get_doc("CRM Student", student_id)
                
                # Find active class enrollment
                class_students = frappe.get_all(
                    "SIS Class Student",
                    filters={"student_id": student_id},
                    fields=["class_id"],
                    order_by="creation desc",
                    limit=1
                )
                
                if class_students and class_students[0].class_id:
                    class_id = class_students[0].class_id
                    class_doc = frappe.get_doc("SIS Class", class_id)
                    
                    # Get education stage from education grade
                    if class_doc.education_grade:
                        grade_doc = frappe.get_doc("SIS Education Grade", class_doc.education_grade)
                        if grade_doc.education_stage_id:
                            student_education_stage_id = grade_doc.education_stage_id
                            frappe.logger().info(f"Parent portal - Student {student_id} education stage: {student_education_stage_id}")
            except Exception as e:
                frappe.logger().error(f"Parent portal - Error getting student education stage: {str(e)}")

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

        # Pagination params
        page = int(data.get("page", 1))
        limit = int(data.get("limit", 10))

        frappe.logger().info(f"Parent portal - Using filters: {filters}")

        # Get ALL published articles first (no pagination yet)
        # We need to filter by education stage before paginating
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
                "cover_image",
                "published_at",
                "published_by"
            ],
            filters=filters,
            order_by="featured desc, published_at desc"  # Featured articles first, then by date
        )

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
                    # Handle escaped JSON strings - some articles have double/triple escaped JSON
                    raw_stages = article.education_stage_ids or "[]"
                    
                    # Try to parse, if it's a string that looks like escaped JSON, unescape it
                    education_stage_ids = []
                    try:
                        # First attempt: direct parse
                        education_stage_ids = json.loads(raw_stages)
                    except:
                        # Second attempt: it might be double-escaped, try unescaping once
                        try:
                            unescaped = json.loads(raw_stages)
                            if isinstance(unescaped, str):
                                education_stage_ids = json.loads(unescaped)
                            else:
                                education_stage_ids = unescaped
                        except:
                            # Third attempt: triple-escaped?
                            try:
                                unescaped1 = json.loads(raw_stages)
                                if isinstance(unescaped1, str):
                                    unescaped2 = json.loads(unescaped1)
                                    if isinstance(unescaped2, str):
                                        education_stage_ids = json.loads(unescaped2)
                                    else:
                                        education_stage_ids = unescaped2
                            except:
                                education_stage_ids = []
                    
                    # If article has no education_stage_ids (empty array), show to all students
                    # If article has education_stage_ids, only show if student's stage matches
                    if education_stage_ids and len(education_stage_ids) > 0:
                        should_include = student_education_stage_id in education_stage_ids
                        frappe.logger().info(f"Parent portal - Article {article.name}: stages={education_stage_ids}, student_stage={student_education_stage_id}, include={should_include}")
                    else:
                        should_include = True  # Empty education_stage_ids means show to all
                        frappe.logger().info(f"Parent portal - Article {article.name}: No stages specified, showing to all")
                except Exception as e:
                    should_include = True  # If parsing fails completely, show the article (failsafe)
                    frappe.logger().error(f"Parent portal - Error parsing stages for {article.name}: {str(e)}, raw: {article.education_stage_ids}")
            else:
                frappe.logger().info(f"Parent portal - No student_education_stage_id provided, showing all articles")

            if should_include:
                # Get education stage names for display
                try:
                    # Reuse the already-parsed education_stage_ids from above
                    # But if we're showing all articles (no student filter), need to parse here
                    if not student_education_stage_id:
                        raw_stages = article.education_stage_ids or "[]"
                        try:
                            education_stage_ids = json.loads(raw_stages)
                        except:
                            try:
                                unescaped = json.loads(raw_stages)
                                education_stage_ids = json.loads(unescaped) if isinstance(unescaped, str) else unescaped
                            except:
                                education_stage_ids = []
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

        # Now apply pagination to filtered results
        total_count = len(filtered_articles)
        start_index = (page - 1) * limit
        end_index = start_index + limit
        paginated_articles = filtered_articles[start_index:end_index]

        success_log = f"Successfully retrieved {len(filtered_articles)} filtered news articles (campus={campus_id or 'all'}, total_before_filter={len(articles)}, student_id={student_id})"
        frappe.logger().info(f"Parent portal - {success_log}")

        return list_response(
            data=paginated_articles,
            message="News articles fetched successfully",
            meta={
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": len(filtered_articles),
                    "total_pages": (len(filtered_articles) + limit - 1) // limit
                },
                "backend_log": success_log,
                "filters_used": {
                    "campus_id": campus_id or None,
                    "status": "published",
                    "student_id": student_id
                },
                "debug_info": {
                    "user": frappe.session.user,
                    "is_guest": frappe.session.user == "Guest",
                    "campus_from_params": data.get("campus_id"),
                    "final_campus": campus_id
                },
                "code_version": "v2.2_params_only"  # Marker để verify code mới
            }
        )

    except Exception as e:
        frappe.logger().error(f"Parent portal - Error fetching news articles: {str(e)}")
        return error_response(
            message="Failed to fetch news articles",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=True)
def get_news_article(article_id=None):
    """Get a single published news article by ID for parent portal"""
    try:
        # Extensive debug logging
        frappe.logger().info(f"===== get_news_article called =====")
        frappe.logger().info(f"article_id parameter: {article_id}")
        frappe.logger().info(f"frappe.form_dict: {frappe.form_dict}")
        frappe.logger().info(f"frappe.local.form_dict: {frappe.local.form_dict}")
        
        # Log request details
        if hasattr(frappe, 'request'):
            frappe.logger().info(f"Request method: {frappe.request.method}")
            frappe.logger().info(f"Request URL: {frappe.request.url}")
            frappe.logger().info(f"Request args (query params): {frappe.request.args}")
            frappe.logger().info(f"Request form: {frappe.request.form}")
            frappe.logger().info(f"Request data (raw): {frappe.request.data}")
            frappe.logger().info(f"Request Content-Type: {frappe.request.content_type}")
            frappe.logger().info(f"Request headers: {dict(frappe.request.headers)}")
            try:
                if frappe.request.is_json:
                    frappe.logger().info(f"Request json: {frappe.request.get_json(force=True, silent=True)}")
                else:
                    frappe.logger().info(f"Request is not JSON")
            except Exception as json_err:
                frappe.logger().info(f"Could not parse JSON: {str(json_err)}")
        
        # For GET requests, Frappe automatically maps query params to function params
        # For POST requests, we need to get from form_dict
        if not article_id:
            # Try form_dict for POST requests
            article_id = frappe.form_dict.get("article_id") or frappe.local.form_dict.get("article_id")
            frappe.logger().info(f"Got from form_dict: {article_id}")
            
            # Try request.args for GET requests
            if not article_id and hasattr(frappe, 'request'):
                article_id = frappe.request.args.get("article_id")
                frappe.logger().info(f"Got from request.args: {article_id}")

        if not article_id:
            error_msg = f"Article ID is still None after all attempts"
            frappe.logger().error(error_msg)
            # Include debug info in response
            debug_data = {
                "form_dict": str(frappe.form_dict),
                "method": frappe.request.method if hasattr(frappe, 'request') else 'N/A',
                "url": frappe.request.url if hasattr(frappe, 'request') else 'N/A',
                "request_args": str(frappe.request.args) if hasattr(frappe, 'request') else 'N/A'
            }
            frappe.logger().error(f"Debug info: {debug_data}")
            return validation_error_response(
                "Article ID is required", 
                {"article_id": ["Article ID is required"]},
                debug_info=debug_data
            )

        # Get the article
        article = frappe.get_doc("SIS News Article", article_id)

        # Check if article is published
        if article.status != "published":
            return not_found_response("Article not found")

        # No campus check for parent portal - allow viewing all published articles

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
            "featured": article.featured,
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
        frappe.logger().error("Parent portal - Article does not exist")
        return not_found_response("Article not found")
    except Exception as e:
        frappe.logger().error(f"Parent portal - Error fetching news article: {str(e)}")
        frappe.logger().error(f"Exception type: {type(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        return error_response(
            message="Failed to fetch news article",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_news_tags():
    """Get active news tags for current campus (parent portal)"""
    try:
        data = frappe.local.form_dict
        
        # Get campus_id from request params only (optional filter)
        # If not provided, will return tags from all campuses
        campus_id = data.get("campus_id")
            
        frappe.logger().info(f"Parent portal - Campus_id from params: {data.get('campus_id')}, user: {frappe.session.user}, final campus_id: {campus_id}")

        # Check if SIS News Tag doctype exists
        if not frappe.db.exists("DocType", "SIS News Tag"):
            frappe.logger().error("SIS News Tag DocType does not exist")
            return error_response(
                message="News system not available",
                code="DOCTYPE_NOT_FOUND"
            )

        # Build filters - is_active tags only
        filters = {"is_active": 1}
        
        # Add campus filter only if campus_id is provided
        if campus_id:
            filters["campus_id"] = campus_id
            
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
