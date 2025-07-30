"""
Install migration dependencies
"""

import subprocess
import sys
import os

def install_dependencies():
    """Install required dependencies for migration"""
    try:
        # Path to requirements file
        requirements_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
        
        if not os.path.exists(requirements_file):
            print("Requirements file not found!")
            return False
        
        # Install dependencies
        print("Installing migration dependencies...")
        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', '-r', requirements_file
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Dependencies installed successfully!")
            return True
        else:
            print(f"❌ Failed to install dependencies: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error installing dependencies: {str(e)}")
        return False

def test_imports():
    """Test if migration imports work"""
    try:
        import pymongo
        from pymongo import MongoClient
        from bson import ObjectId
        print("✅ MongoDB dependencies imported successfully!")
        return True
    except ImportError as e:
        print(f"❌ Import error: {str(e)}")
        return False

if __name__ == "__main__":
    print("=== Migration Dependencies Setup ===")
    
    # Install dependencies
    if install_dependencies():
        # Test imports
        if test_imports():
            print("🎉 Migration setup completed successfully!")
        else:
            print("⚠️ Dependencies installed but imports failed. Please check your environment.")
    else:
        print("❌ Migration setup failed!")
        
    print("\nNext steps:")
    print("1. Configure MongoDB connection settings")
    print("2. Test connection: frappe.call('erp.migration.data_migration.test_mongodb_connection')")
    print("3. Run migration: frappe.call('erp.migration.migration_manager.start_full_migration')")