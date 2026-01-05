# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

"""
API endpoints cho Invitation flow (invite, accept, decline, leave, remove member)
"""

import frappe
from frappe import _
import json
from frappe.utils import add_days, now_datetime
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    not_found_response,
    forbidden_response,
    validation_error_response
)
from .project import get_user_project_role, check_project_access, log_project_change


def get_request_param(param_name):
    """Helper function để lấy parameter từ request - hỗ trợ cả JSON body và query params"""
    # 1. Try JSON payload (POST body)
    if frappe.request.data:
        try:
            json_data = json.loads(frappe.request.data)
            if json_data and param_name in json_data:
                return json_data[param_name]
        except (json.JSONDecodeError, TypeError):
            pass
    
    # 2. Try form_dict
    value = frappe.local.form_dict.get(param_name)
    if value:
        return value
    
    # 3. Try query params
    if hasattr(frappe.local, 'request') and hasattr(frappe.local.request, 'args'):
        value = frappe.local.request.args.get(param_name)
        if value:
            return value
    
    return None


@frappe.whitelist(allow_guest=False, methods=["POST"])
def invite_member():
    """
    Mời user vào project
    
    Payload (JSON body):
        project_id: ID của project (required)
        invitee_email: Email của người được mời (required)
        role: Vai trò được mời (manager/member/viewer), default: member
        message: Lời nhắn từ người mời
    
    Returns:
        Invitation vừa tạo
    """
    try:
        user = frappe.session.user
        
        # Đọc data từ JSON body
        data = json.loads(frappe.request.data) if frappe.request.data else {}
        project_id = data.get("project_id")
        invitee_email = data.get("invitee_email")
        role = data.get("role", "member")
        message = data.get("message")
        
        # Validate required fields
        if not project_id or not invitee_email:
            return error_response("project_id và invitee_email là bắt buộc", code="MISSING_PARAMETER")
        
        # Validate role
        valid_roles = ["manager", "member", "viewer"]
        if role not in valid_roles:
            return validation_error_response(
                "Role không hợp lệ",
                {"role": [f"Role phải là một trong: {', '.join(valid_roles)}"]}
            )
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra quyền invite (owner hoặc manager)
        inviter_role = get_user_project_role(project_id, user)
        if inviter_role not in ["owner", "manager"]:
            return forbidden_response("Bạn không có quyền mời thành viên")
        
        # Manager không thể mời với role manager
        if inviter_role == "manager" and role == "manager":
            return forbidden_response("Manager không thể mời thêm manager")
        
        # Kiểm tra user được mời tồn tại
        invitee = frappe.db.get_value("User", {"email": invitee_email}, "name")
        if not invitee:
            return not_found_response(f"Không tìm thấy user với email {invitee_email}")
        
        # Kiểm tra không tự mời chính mình
        if invitee == user:
            return validation_error_response(
                "Không thể tự mời chính mình",
                {"invitee_email": ["Bạn không thể mời chính mình"]}
            )
        
        # Kiểm tra đã là member chưa
        existing_member = frappe.db.exists("PM Project Member", {
            "project_id": project_id,
            "user_id": invitee
        })
        if existing_member:
            return validation_error_response(
                "User đã là thành viên",
                {"invitee_email": ["User này đã là thành viên của dự án"]}
            )
        
        # Kiểm tra đã có pending invitation chưa
        existing_invitation = frappe.db.exists("PM Project Invitation", {
            "project_id": project_id,
            "invitee_id": invitee,
            "status": "pending"
        })
        if existing_invitation:
            return validation_error_response(
                "Đã có lời mời đang chờ",
                {"invitee_email": ["Đã có lời mời đang chờ xử lý cho user này"]}
            )
        
        # Tạo invitation
        invitation = frappe.get_doc({
            "doctype": "PM Project Invitation",
            "project_id": project_id,
            "inviter_id": user,
            "invitee_id": invitee,
            "role": role,
            "status": "pending",
            "expires_at": add_days(now_datetime(), 7),
            "message": message
        })
        invitation.insert()
        frappe.db.commit()
        
        # Log change
        log_project_change(project_id, "member_invited", None, {
            "invitee_id": invitee,
            "role": role
        })
        
        # Enrich invitation data
        invitation_data = invitation.as_dict()
        invitation_data["invitee_full_name"] = frappe.db.get_value("User", invitee, "full_name")
        invitation_data["project_title"] = frappe.db.get_value("PM Project", project_id, "title")
        
        return single_item_response(invitation_data, "Đã gửi lời mời thành công")
        
    except Exception as e:
        frappe.log_error(f"Error inviting member: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_my_invitations(status: str = "pending"):
    """
    Lấy danh sách lời mời của user hiện tại
    
    Args:
        status: Filter theo status (pending/accepted/declined/expired)
    
    Returns:
        List các invitations
    """
    try:
        user = frappe.session.user
        
        filters = {"invitee_id": user}
        if status:
            filters["status"] = status
        
        invitations = frappe.get_all(
            "PM Project Invitation",
            filters=filters,
            fields=["name", "project_id", "inviter_id", "role", "status", 
                   "expires_at", "message", "creation"],
            order_by="creation desc"
        )
        
        # Enrich data
        for inv in invitations:
            inv["project_title"] = frappe.db.get_value("PM Project", inv["project_id"], "title")
            inviter_info = frappe.db.get_value(
                "User", inv["inviter_id"], 
                ["full_name", "user_image"], 
                as_dict=True
            )
            if inviter_info:
                inv["inviter_full_name"] = inviter_info.get("full_name")
                inv["inviter_image"] = inviter_info.get("user_image")
        
        return success_response(
            data=invitations,
            message=f"Tìm thấy {len(invitations)} lời mời"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting invitations: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_project_invitations():
    """
    Lấy danh sách lời mời của project (cho owner/manager)
    
    Args:
        project_id: ID của project (from query params)
        status: Filter theo status (from query params)
    
    Returns:
        List các invitations
    """
    try:
        user = frappe.session.user
        
        # Lấy params từ GET query params
        project_id = frappe.request.args.get("project_id") or frappe.form_dict.get("project_id")
        status = frappe.request.args.get("status") or frappe.form_dict.get("status")
        
        # Validate project_id
        if not project_id:
            return error_response("project_id is required", code="MISSING_PARAMETER")
        
        # Kiểm tra quyền
        role = get_user_project_role(project_id, user)
        if role not in ["owner", "manager"]:
            return forbidden_response("Bạn không có quyền xem lời mời")
        
        filters = {"project_id": project_id}
        if status:
            filters["status"] = status
        
        invitations = frappe.get_all(
            "PM Project Invitation",
            filters=filters,
            fields=["name", "inviter_id", "invitee_id", "role", "status",
                   "expires_at", "message", "creation"],
            order_by="creation desc"
        )
        
        # Enrich data
        for inv in invitations:
            inviter_info = frappe.db.get_value(
                "User", inv["inviter_id"],
                ["full_name", "user_image"],
                as_dict=True
            )
            invitee_info = frappe.db.get_value(
                "User", inv["invitee_id"],
                ["full_name", "email", "user_image"],
                as_dict=True
            )
            if inviter_info:
                inv["inviter_full_name"] = inviter_info.get("full_name")
                inv["inviter_image"] = inviter_info.get("user_image")
            if invitee_info:
                inv["invitee_full_name"] = invitee_info.get("full_name")
                inv["invitee_email"] = invitee_info.get("email")
                inv["invitee_image"] = invitee_info.get("user_image")
        
        return success_response(
            data=invitations,
            message=f"Tìm thấy {len(invitations)} lời mời"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting project invitations: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def accept_invitation():
    """
    Chấp nhận lời mời vào project
    
    Query params:
        invitation_id: ID của invitation
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Lấy invitation_id từ request
        invitation_id = get_request_param("invitation_id")
        if not invitation_id:
            return error_response("invitation_id là bắt buộc", code="MISSING_PARAMETER")
        
        # Kiểm tra invitation tồn tại
        if not frappe.db.exists("PM Project Invitation", invitation_id):
            return not_found_response(f"Invitation {invitation_id} không tồn tại")
        
        invitation = frappe.get_doc("PM Project Invitation", invitation_id)
        
        # Kiểm tra quyền (chỉ invitee mới được accept)
        if invitation.invitee_id != user:
            return forbidden_response("Bạn không có quyền thực hiện hành động này")
        
        # Kiểm tra status
        if invitation.status != "pending":
            return validation_error_response(
                "Lời mời không hợp lệ",
                {"status": [f"Lời mời đang ở trạng thái '{invitation.status}'"]}
            )
        
        # Kiểm tra hết hạn
        if invitation.expires_at and invitation.expires_at < now_datetime():
            invitation.status = "expired"
            invitation.save()
            frappe.db.commit()
            return validation_error_response(
                "Lời mời đã hết hạn",
                {"expires_at": ["Lời mời này đã hết hạn"]}
            )
        
        # Kiểm tra user đã là member chưa (có thể đã được thêm bằng cách khác)
        existing_member = frappe.db.exists("PM Project Member", {
            "project_id": invitation.project_id,
            "user_id": user
        })
        
        if existing_member:
            # User đã là member rồi, chỉ cập nhật status invitation
            invitation.status = "accepted"
            invitation.save()
            frappe.db.commit()
            return success_response(message="Bạn đã là thành viên của dự án này")
        
        # Tạo member record
        member = frappe.get_doc({
            "doctype": "PM Project Member",
            "project_id": invitation.project_id,
            "user_id": user,
            "role": invitation.role,
            "joined_at": now_datetime()
        })
        member.insert()
        
        # Cập nhật invitation status
        invitation.status = "accepted"
        invitation.save()
        frappe.db.commit()
        
        # Log change
        log_project_change(invitation.project_id, "member_joined", None, {
            "user_id": user,
            "role": invitation.role
        })
        
        return success_response(message="Đã tham gia dự án thành công")
        
    except Exception as e:
        frappe.log_error(f"Error accepting invitation: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def decline_invitation():
    """
    Từ chối lời mời vào project
    
    Query params:
        invitation_id: ID của invitation
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Lấy invitation_id từ request
        invitation_id = get_request_param("invitation_id")
        if not invitation_id:
            return error_response("invitation_id là bắt buộc", code="MISSING_PARAMETER")
        
        # Kiểm tra invitation tồn tại
        if not frappe.db.exists("PM Project Invitation", invitation_id):
            return not_found_response(f"Invitation {invitation_id} không tồn tại")
        
        invitation = frappe.get_doc("PM Project Invitation", invitation_id)
        
        # Kiểm tra quyền
        if invitation.invitee_id != user:
            return forbidden_response("Bạn không có quyền thực hiện hành động này")
        
        # Kiểm tra status
        if invitation.status != "pending":
            return validation_error_response(
                "Lời mời không hợp lệ",
                {"status": [f"Lời mời đang ở trạng thái '{invitation.status}'"]}
            )
        
        # Cập nhật status
        invitation.status = "declined"
        invitation.save()
        frappe.db.commit()
        
        return success_response(message="Đã từ chối lời mời")
        
    except Exception as e:
        frappe.log_error(f"Error declining invitation: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def cancel_invitation():
    """
    Hủy lời mời (dành cho inviter hoặc owner/manager)
    
    Query params:
        invitation_id: ID của invitation
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Lấy invitation_id từ request
        invitation_id = get_request_param("invitation_id")
        if not invitation_id:
            return error_response("invitation_id là bắt buộc", code="MISSING_PARAMETER")
        
        # Kiểm tra invitation tồn tại
        if not frappe.db.exists("PM Project Invitation", invitation_id):
            return not_found_response(f"Invitation {invitation_id} không tồn tại")
        
        invitation = frappe.get_doc("PM Project Invitation", invitation_id)
        
        # Kiểm tra quyền (inviter hoặc owner/manager)
        user_role = get_user_project_role(invitation.project_id, user)
        if invitation.inviter_id != user and user_role not in ["owner", "manager"]:
            return forbidden_response("Bạn không có quyền hủy lời mời này")
        
        # Kiểm tra status
        if invitation.status != "pending":
            return validation_error_response(
                "Không thể hủy",
                {"status": [f"Lời mời đang ở trạng thái '{invitation.status}'"]}
            )
        
        # Xóa invitation
        frappe.delete_doc("PM Project Invitation", invitation_id, force=True)
        frappe.db.commit()
        
        return success_response(message="Đã hủy lời mời")
        
    except Exception as e:
        frappe.log_error(f"Error canceling invitation: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def leave_project():
    """
    Rời khỏi project
    
    Query params:
        project_id: ID của project
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Lấy project_id từ request
        project_id = get_request_param("project_id")
        if not project_id:
            return error_response("project_id là bắt buộc", code="MISSING_PARAMETER")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Kiểm tra user là member
        role = get_user_project_role(project_id, user)
        if not role:
            return validation_error_response(
                "Không phải thành viên",
                {"project_id": ["Bạn không phải là thành viên của dự án này"]}
            )
        
        # Owner không thể rời (phải chuyển quyền hoặc xóa project)
        if role == "owner":
            return forbidden_response(
                "Chủ dự án không thể rời. Vui lòng chuyển quyền sở hữu hoặc xóa dự án."
            )
        
        # Xóa member record
        member = frappe.get_doc("PM Project Member", {
            "project_id": project_id,
            "user_id": user
        })
        member_name = member.name
        frappe.delete_doc("PM Project Member", member_name, force=True)
        frappe.db.commit()
        
        # Log change
        log_project_change(project_id, "member_left", 
                          {"user_id": user, "role": role}, None)
        
        return success_response(message="Đã rời khỏi dự án")
        
    except Exception as e:
        frappe.log_error(f"Error leaving project: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def remove_member():
    """
    Xóa thành viên khỏi project (chỉ owner có quyền)
    
    Query params:
        project_id: ID của project
        member_user_id: User ID của member cần xóa
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Lấy params từ request
        project_id = get_request_param("project_id")
        member_user_id = get_request_param("member_user_id")
        
        if not project_id or not member_user_id:
            return error_response("project_id và member_user_id là bắt buộc", code="MISSING_PARAMETER")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Chỉ owner mới có quyền remove
        role = get_user_project_role(project_id, user)
        if role != "owner":
            return forbidden_response("Chỉ chủ dự án mới có quyền xóa thành viên")
        
        # Không thể xóa chính mình (owner)
        if member_user_id == user:
            return forbidden_response("Không thể tự xóa chính mình")
        
        # Kiểm tra member tồn tại
        member_role = get_user_project_role(project_id, member_user_id)
        if not member_role:
            return not_found_response(f"User {member_user_id} không phải là thành viên")
        
        # Xóa member
        member = frappe.get_doc("PM Project Member", {
            "project_id": project_id,
            "user_id": member_user_id
        })
        member_name = member.name
        frappe.delete_doc("PM Project Member", member_name, force=True)
        frappe.db.commit()
        
        # Log change
        log_project_change(project_id, "member_removed",
                          {"user_id": member_user_id, "role": member_role}, None)
        
        return success_response(message="Đã xóa thành viên khỏi dự án")
        
    except Exception as e:
        frappe.log_error(f"Error removing member: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["POST"])
def transfer_ownership():
    """
    Chuyển quyền sở hữu project cho member khác
    
    Query params:
        project_id: ID của project
        new_owner_id: User ID của owner mới
    
    Returns:
        Success message
    """
    try:
        user = frappe.session.user
        
        # Lấy params từ request
        project_id = get_request_param("project_id")
        new_owner_id = get_request_param("new_owner_id")
        
        if not project_id or not new_owner_id:
            return error_response("project_id và new_owner_id là bắt buộc", code="MISSING_PARAMETER")
        
        # Kiểm tra project tồn tại
        if not frappe.db.exists("PM Project", project_id):
            return not_found_response(f"Project {project_id} không tồn tại")
        
        # Chỉ owner hiện tại mới có quyền chuyển
        role = get_user_project_role(project_id, user)
        if role != "owner":
            return forbidden_response("Chỉ chủ dự án mới có quyền chuyển quyền sở hữu")
        
        # Kiểm tra new owner là member
        new_owner_role = get_user_project_role(project_id, new_owner_id)
        if not new_owner_role:
            return not_found_response(f"User {new_owner_id} không phải là thành viên")
        
        # Cập nhật project owner_id
        project = frappe.get_doc("PM Project", project_id)
        project.owner_id = new_owner_id
        project.save()
        
        # Cập nhật role của owner cũ thành manager
        old_owner_member = frappe.get_doc("PM Project Member", {
            "project_id": project_id,
            "user_id": user
        })
        old_owner_member.role = "manager"
        old_owner_member.save()
        
        # Cập nhật role của owner mới
        new_owner_member = frappe.get_doc("PM Project Member", {
            "project_id": project_id,
            "user_id": new_owner_id
        })
        new_owner_member.role = "owner"
        new_owner_member.save()
        
        frappe.db.commit()
        
        # Log change
        log_project_change(project_id, "ownership_transferred",
                          {"owner_id": user},
                          {"owner_id": new_owner_id})
        
        return success_response(message="Đã chuyển quyền sở hữu thành công")
        
    except Exception as e:
        frappe.log_error(f"Error transferring ownership: {str(e)}")
        return error_response(str(e))

