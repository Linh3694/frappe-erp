# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
import requests
import base64
from typing import Dict, List, Optional, Tuple
import json


class CompreFaceService:
    """Service to handle CompreFace API interactions for face recognition"""

    def __init__(self):
        self.base_url = "http://172.16.20.116:8080"
        self.api_key = "00000000-0000-0000-0000-000000000002"  # Default demo API key
        self.recognition_api = f"{self.base_url}/api/v1/recognition"

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for CompreFace API requests"""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }

    def _get_image_base64(self, image_url: str) -> Optional[str]:
        """Convert image URL to base64 string with validation"""
        try:
            import io
            from PIL import Image

            # Get image data
            if image_url.startswith('/files/') or image_url.startswith('files/'):
                file_path = frappe.get_site_path('public', image_url.lstrip('/'))
                with open(file_path, 'rb') as f:
                    image_data = f.read()
            else:
                # If it's a full URL, download the image
                response = requests.get(image_url, timeout=30)
                response.raise_for_status()
                image_data = response.content

            # Validate and resize image if needed
            try:
                img = Image.open(io.BytesIO(image_data))

                # Convert to RGB if necessary (remove alpha channel)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')

                # Resize if too large (max 1024x1024 for CompreFace)
                max_size = (1024, 1024)
                if img.width > max_size[0] or img.height > max_size[1]:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)

                # Convert back to JPEG bytes
                output_buffer = io.BytesIO()
                img.save(output_buffer, format='JPEG', quality=85)
                image_data = output_buffer.getvalue()

                frappe.logger().info(f"Image processed successfully: {img.size}, {len(image_data)} bytes")

            except Exception as img_error:
                frappe.logger().warning(f"Image processing failed, using original: {str(img_error)}")

            return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            frappe.log_error(f"Error converting image to base64: {str(e)}", "CompreFace Service")
            return None

    def create_subject(self, subject_id: str, subject_name: str = "") -> Dict:
        """
        Create a new subject in CompreFace

        Args:
            subject_id: Unique identifier for the subject (student_code)
            subject_name: Display name for the subject

        Returns:
            Dict with success status and data
        """
        try:
            url = f"{self.recognition_api}/subjects"
            payload = {
                "subject": subject_id,
                "name": subject_name or subject_id
            }

            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=30)
            response.raise_for_status()

            result = response.json()
            frappe.logger().info(f"CompreFace subject created: {subject_id}")

            return {
                "success": True,
                "data": result,
                "message": f"Subject {subject_id} created successfully"
            }

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:  # Subject already exists
                return {
                    "success": True,
                    "data": {"subject": subject_id},
                    "message": f"Subject {subject_id} already exists"
                }
            else:
                frappe.log_error(f"HTTP Error creating CompreFace subject: {str(e)}", "CompreFace Service")
                return {
                    "success": False,
                    "error": f"HTTP Error: {e.response.status_code}",
                    "message": "Failed to create subject in CompreFace"
                }

        except Exception as e:
            frappe.log_error(f"Error creating CompreFace subject: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to create subject in CompreFace"
            }

    def add_face_to_subject(self, subject_id: str, image_url: str) -> Dict:
        """
        Add a face image to an existing subject

        Args:
            subject_id: Subject identifier (student_code)
            image_url: URL or path to the face image

        Returns:
            Dict with success status and data
        """
        try:
            # Convert image to base64
            image_base64 = self._get_image_base64(image_url)
            if not image_base64:
                return {
                    "success": False,
                    "error": "Failed to process image",
                    "message": "Could not convert image to base64"
                }

            url = f"{self.recognition_api}/subjects/{subject_id}"
            payload = {
                "file": f"data:image/jpeg;base64,{image_base64}"
            }

            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=60)
            response.raise_for_status()

            result = response.json()
            frappe.logger().info(f"Face added to CompreFace subject: {subject_id}")

            return {
                "success": True,
                "data": result,
                "message": f"Face added to subject {subject_id} successfully"
            }

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error adding face: {e.response.status_code}"
            if e.response.status_code == 404:
                error_msg = f"Subject {subject_id} not found"
            elif e.response.status_code == 400:
                error_msg = "Invalid image or face not detected"

            # Log detailed response for debugging
            try:
                error_details = e.response.json() if e.response.content else {}
                frappe.logger().error(f"CompreFace add_face error for {subject_id}: {error_msg} - Details: {error_details}")
            except:
                frappe.logger().error(f"CompreFace add_face error for {subject_id}: {error_msg} - Raw response: {e.response.text}")

            frappe.log_error(f"{error_msg}: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": error_msg,
                "message": f"Failed to add face to subject {subject_id}"
            }

        except Exception as e:
            frappe.log_error(f"Error adding face to CompreFace subject: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to add face to subject {subject_id}"
            }

    def recognize_face(self, image_url: str, limit: int = 1) -> Dict:
        """
        Recognize faces in an image

        Args:
            image_url: URL or path to the image to recognize
            limit: Maximum number of results to return

        Returns:
            Dict with recognition results
        """
        try:
            # Convert image to base64
            image_base64 = self._get_image_base64(image_url)
            if not image_base64:
                return {
                    "success": False,
                    "error": "Failed to process image",
                    "message": "Could not convert image to base64"
                }

            url = f"{self.recognition_api}/recognize"
            payload = {
                "file": f"data:image/jpeg;base64,{image_base64}",
                "limit": limit
            }

            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=60)
            response.raise_for_status()

            result = response.json()
            return {
                "success": True,
                "data": result,
                "message": "Face recognition completed"
            }

        except Exception as e:
            frappe.log_error(f"Error recognizing face: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to recognize face"
            }

    def delete_subject(self, subject_id: str) -> Dict:
        """
        Delete a subject from CompreFace

        Args:
            subject_id: Subject identifier to delete

        Returns:
            Dict with success status
        """
        try:
            url = f"{self.recognition_api}/subjects/{subject_id}"

            response = requests.delete(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()

            frappe.logger().info(f"CompreFace subject deleted: {subject_id}")
            return {
                "success": True,
                "message": f"Subject {subject_id} deleted successfully"
            }

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # Subject doesn't exist, consider it a success
                return {
                    "success": True,
                    "message": f"Subject {subject_id} not found (already deleted)"
                }
            else:
                frappe.log_error(f"HTTP Error deleting CompreFace subject: {str(e)}", "CompreFace Service")
                return {
                    "success": False,
                    "error": f"HTTP Error: {e.response.status_code}",
                    "message": f"Failed to delete subject {subject_id}"
                }

        except Exception as e:
            frappe.log_error(f"Error deleting CompreFace subject: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to delete subject {subject_id}"
            }

    def get_subject_info(self, subject_id: str) -> Dict:
        """
        Get information about a subject

        Args:
            subject_id: Subject identifier

        Returns:
            Dict with subject information
        """
        try:
            url = f"{self.recognition_api}/subjects/{subject_id}"

            response = requests.get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()

            result = response.json()
            return {
                "success": True,
                "data": result,
                "message": f"Subject {subject_id} information retrieved"
            }

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return {
                    "success": False,
                    "error": "Subject not found",
                    "message": f"Subject {subject_id} does not exist"
                }
            else:
                frappe.log_error(f"HTTP Error getting subject info: {str(e)}", "CompreFace Service")
                return {
                    "success": False,
                    "error": f"HTTP Error: {e.response.status_code}",
                    "message": f"Failed to get subject {subject_id} info"
                }

        except Exception as e:
            frappe.log_error(f"Error getting CompreFace subject info: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to get subject {subject_id} info"
            }


# Singleton instance
compreFace_service = CompreFaceService()
