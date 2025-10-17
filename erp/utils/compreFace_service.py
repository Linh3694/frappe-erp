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

    def _get_image_data(self, image_url: str) -> Optional[bytes]:
        """Convert image URL to binary data with validation"""
        try:
            import io
            from PIL import Image
            import base64

            # Get image data
            if image_url.startswith('/files/') or image_url.startswith('files/'):
                file_path = frappe.get_site_path('public', image_url.lstrip('/'))
                with open(file_path, 'rb') as f:
                    image_data = f.read()
            elif image_url.startswith('data:image/'):
                # Handle data URL (base64 encoded image)
                try:
                    # Extract base64 data from data URL
                    header, base64_data = image_url.split(',', 1)
                    image_data = base64.b64decode(base64_data)
                except (ValueError, base64.binascii.Error) as e:
                    frappe.logger().error(f"Invalid data URL format: {str(e)}")
                    return None
            else:
                # If it's a full URL, download the image
                response = requests.get(image_url, timeout=30)
                response.raise_for_status()
                image_data = response.content

            # Validate and resize image if needed
            processed_image_data = image_data
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
                processed_image_data = output_buffer.getvalue()

            except Exception as img_error:
                frappe.logger().warning(f"Image processing failed, using original: {str(img_error)}")

            return processed_image_data
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
                frappe.logger().info(f"Subject {subject_id} already exists (409), treating as success")
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
            # Convert image to binary data
            image_data = self._get_image_data(image_url)
            if not image_data:
                return {
                    "success": False,
                    "error": "Failed to process image",
                    "message": "Could not convert image to binary data"
                }

            # Try POST /faces with subject parameter (newer CompreFace API)
            url = f"{self.recognition_api}/faces"

            # Use multipart/form-data with binary image data and subject parameter
            files = {
                'file': ('image.jpg', image_data, 'image/jpeg')
            }
            data = {
                'subject': subject_id
            }

            response = requests.post(url, files=files, data=data, headers={'x-api-key': self.api_key}, timeout=60)

            response.raise_for_status()

            result = response.json()

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
            # Convert image to binary data
            image_data = self._get_image_data(image_url)
            if not image_data:
                return {
                    "success": False,
                    "error": "Failed to process image",
                    "message": "Could not convert image to binary data"
                }

            url = f"{self.recognition_api}/recognize"

            # Use multipart/form-data for recognition too
            files = {
                'file': ('image.jpg', image_data, 'image/jpeg')
            }
            data = {
                'limit': limit
            }

            response = requests.post(url, files=files, data=data, headers={'x-api-key': self.api_key}, timeout=60)
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

    def test_api_endpoints(self) -> Dict:
        """
        Test available API endpoints for debugging
        """
        try:
            # Test basic connectivity first
            response = requests.get(self.base_url, timeout=10)

            # Test recognition API subjects endpoint (the one that works)
            url = f"{self.recognition_api}/subjects"
            response = requests.get(url, headers=self._get_headers(), timeout=10)
            subjects = response.json()

            # Test different add face endpoints
            test_endpoints = [
                f"{self.recognition_api}/faces",
                f"{self.recognition_api}/subjects/test_subject"
            ]

            endpoint_tests = {}
            for endpoint in test_endpoints:
                try:
                    # Test OPTIONS or HEAD to see what methods are allowed
                    head_response = requests.head(endpoint, headers=self._get_headers(), timeout=5)
                    endpoint_tests[endpoint] = {
                        "status_code": head_response.status_code,
                        "allowed_methods": head_response.headers.get('Allow', 'Unknown')
                    }
                except Exception as ep_e:
                    endpoint_tests[endpoint] = {"error": str(ep_e)}

            return {
                "success": True,
                "connectivity": "OK",
                "subjects_count": len(subjects.get("subjects", [])),
                "endpoint_tests": endpoint_tests
            }
        except requests.exceptions.ConnectionError as e:
            frappe.logger().error(f"Connection error to CompreFace: {str(e)}")
            return {
                "success": False,
                "error": f"Cannot connect to CompreFace server at {self.base_url}",
                "details": str(e)
            }
        except Exception as e:
            frappe.logger().error(f"CompreFace test error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    def test_add_face(self) -> Dict:
        """
        Test add face functionality with a simple test
        """
        try:
            # Create a simple test subject first
            create_result = self.create_subject("test_student", "Test Student")
            if not create_result["success"]:
                return create_result

            # Create a simple test image (1x1 pixel JPEG)
            from PIL import Image
            import io

            # Create a small red square as test image
            test_image = Image.new('RGB', (100, 100), color='red')
            img_buffer = io.BytesIO()
            test_image.save(img_buffer, format='JPEG')
            test_image_data = img_buffer.getvalue()

            # Try to add the test face
            add_result = self.add_face_to_subject("test_student", "data:image/jpeg;base64," + base64.b64encode(test_image_data).decode('utf-8'))

            # Clean up test subject
            self.delete_subject("test_student")

            return {
                "success": add_result["success"],
                "create_result": create_result,
                "add_result": add_result
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
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

    def get_subject_photos_count(self, subject_id: str) -> Dict:
        """
        Get the number of photos for a subject
        
        Args:
            subject_id: Subject identifier
            
        Returns:
            Dict with photos count information
        """
        try:
            # Get all faces for the subject
            url = f"{self.recognition_api}/faces"
            params = {'subject': subject_id}
            
            response = requests.get(url, params=params, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            
            result = response.json()
            faces = result.get('faces', [])
            photos_count = len(faces)
            
            return {
                "success": True,
                "data": {
                    "subject_id": subject_id,
                    "photos_count": photos_count,
                    "faces": faces
                },
                "message": f"Subject {subject_id} has {photos_count} photo(s)"
            }
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return {
                    "success": False,
                    "error": "Subject not found",
                    "message": f"Subject {subject_id} does not exist"
                }
            else:
                frappe.log_error(f"HTTP Error getting subject photos: {str(e)}", "CompreFace Service")
                return {
                    "success": False,
                    "error": f"HTTP Error: {e.response.status_code}",
                    "message": f"Failed to get photos for subject {subject_id}"
                }
                
        except Exception as e:
            frappe.log_error(f"Error getting subject photos count: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to get photos for subject {subject_id}"
            }
    
    def check_subject_complete(self, subject_id: str) -> Dict:
        """
        Check if a subject exists and has photos
        
        Args:
            subject_id: Subject identifier
            
        Returns:
            Dict with complete status information
        """
        try:
            # First check if subject exists
            subject_info = self.get_subject_info(subject_id)
            
            if not subject_info["success"]:
                return {
                    "success": True,
                    "data": {
                        "subject_exists": False,
                        "has_photos": False,
                        "photos_count": 0,
                        "status": "no_subject"
                    },
                    "message": f"Subject {subject_id} does not exist"
                }
            
            # Subject exists, now check photos
            photos_info = self.get_subject_photos_count(subject_id)
            
            if photos_info["success"]:
                photos_count = photos_info["data"]["photos_count"]
                has_photos = photos_count > 0
                
                status = "complete" if has_photos else "subject_only"
                
                return {
                    "success": True,
                    "data": {
                        "subject_exists": True,
                        "has_photos": has_photos,
                        "photos_count": photos_count,
                        "status": status
                    },
                    "message": f"Subject {subject_id} exists with {photos_count} photo(s)"
                }
            else:
                # Couldn't get photos info, assume no photos
                return {
                    "success": True,
                    "data": {
                        "subject_exists": True,
                        "has_photos": False,
                        "photos_count": 0,
                        "status": "subject_only"
                    },
                    "message": f"Subject {subject_id} exists but couldn't verify photos"
                }
                
        except Exception as e:
            frappe.log_error(f"Error checking subject complete status: {str(e)}", "CompreFace Service")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to check complete status for subject {subject_id}"
            }


# Singleton instance
compreFace_service = CompreFaceService()
