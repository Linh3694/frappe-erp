# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute():
    """Add Pillow dependency if not already installed"""
    try:
        import PIL
        frappe.logger().info("Pillow is already installed")
    except ImportError:
        frappe.logger().info("Pillow not found, attempting to install...")
        try:
            import subprocess
            import sys

            # Try to install Pillow using pip
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", "Pillow>=9.0.0"
            ], capture_output=True, text=True)

            if result.returncode == 0:
                frappe.logger().info("Pillow installed successfully")
            else:
                frappe.logger().error(f"Failed to install Pillow: {result.stderr}")

        except Exception as e:
            frappe.logger().error(f"Error installing Pillow: {str(e)}")

    # Log completion
    frappe.logger().info("add_pillow_dependency patch completed")
