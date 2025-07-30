"""
SIS (Student Information System) Data Migration
Migrate students, classes, schools, teachers, etc. from MongoDB to Frappe
"""

import frappe
from frappe import _
from datetime import datetime
import logging
from .data_migration import MongoToFrappeDataMigration

logger = logging.getLogger(__name__)


class SISDataMigration(MongoToFrappeDataMigration):
    """SIS specific migrations"""
    
    def migrate_schools(self):
        """Migrate Schools collection"""
        try:
            schools_collection = self.mongo_db.schools
            total_schools = schools_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_schools} schools...")
            
            for school_doc in schools_collection.find():
                try:
                    # Check if school already exists
                    if frappe.db.exists("ERP School", {"school_name": school_doc.get('name')}):
                        logger.info(f"School {school_doc.get('name')} already exists, skipping...")
                        continue
                    
                    new_school = frappe.get_doc({
                        "doctype": "ERP School",
                        "school_name": school_doc.get('name'),
                        "school_code": school_doc.get('code'),
                        "address": school_doc.get('address'),
                        "phone": school_doc.get('phone'),
                        "email": school_doc.get('email'),
                        "principal": school_doc.get('principal'),
                        "established_year": school_doc.get('establishedYear'),
                        "mongo_id": str(school_doc.get('_id'))
                    })
                    
                    new_school.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate school {school_doc.get('name', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("schools", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("schools", "failed", str(e))
            logger.error(f"Error migrating schools: {str(e)}")
    
    def migrate_school_years(self):
        """Migrate School Years collection"""
        try:
            school_years_collection = self.mongo_db.schoolyears
            total_years = school_years_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_years} school years...")
            
            for year_doc in school_years_collection.find():
                try:
                    # Check if school year already exists
                    if frappe.db.exists("ERP School Year", {"year_name": year_doc.get('year')}):
                        logger.info(f"School year {year_doc.get('year')} already exists, skipping...")
                        continue
                    
                    new_year = frappe.get_doc({
                        "doctype": "ERP School Year",
                        "year_name": year_doc.get('year'),
                        "start_date": year_doc.get('startDate'),
                        "end_date": year_doc.get('endDate'),
                        "is_current": year_doc.get('isCurrent', False),
                        "description": year_doc.get('description'),
                        "mongo_id": str(year_doc.get('_id'))
                    })
                    
                    new_year.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate school year {year_doc.get('year', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("schoolyears", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("schoolyears", "failed", str(e))
            logger.error(f"Error migrating school years: {str(e)}")
    
    def migrate_grade_levels(self):
        """Migrate Grade Levels collection"""
        try:
            grade_levels_collection = self.mongo_db.gradelevels
            total_grades = grade_levels_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_grades} grade levels...")
            
            for grade_doc in grade_levels_collection.find():
                try:
                    # Check if grade level already exists
                    if frappe.db.exists("ERP Grade Level", {"grade_name": grade_doc.get('name')}):
                        logger.info(f"Grade level {grade_doc.get('name')} already exists, skipping...")
                        continue
                    
                    new_grade = frappe.get_doc({
                        "doctype": "ERP Grade Level",
                        "grade_name": grade_doc.get('name'),
                        "grade_code": grade_doc.get('code'),
                        "sequence": grade_doc.get('sequence', 0),
                        "description": grade_doc.get('description'),
                        "mongo_id": str(grade_doc.get('_id'))
                    })
                    
                    new_grade.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate grade level {grade_doc.get('name', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("gradelevels", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("gradelevels", "failed", str(e))
            logger.error(f"Error migrating grade levels: {str(e)}")
    
    def migrate_subjects(self):
        """Migrate Subjects collection"""
        try:
            subjects_collection = self.mongo_db.subjects
            total_subjects = subjects_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_subjects} subjects...")
            
            for subject_doc in subjects_collection.find():
                try:
                    # Check if subject already exists
                    if frappe.db.exists("ERP Subject", {"subject_name": subject_doc.get('name')}):
                        logger.info(f"Subject {subject_doc.get('name')} already exists, skipping...")
                        continue
                    
                    new_subject = frappe.get_doc({
                        "doctype": "ERP Subject",
                        "subject_name": subject_doc.get('name'),
                        "subject_code": subject_doc.get('code'),
                        "subject_type": subject_doc.get('type'),
                        "credits": subject_doc.get('credits', 0),
                        "description": subject_doc.get('description'),
                        "mongo_id": str(subject_doc.get('_id'))
                    })
                    
                    new_subject.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate subject {subject_doc.get('name', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("subjects", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("subjects", "failed", str(e))
            logger.error(f"Error migrating subjects: {str(e)}")
    
    def migrate_teachers(self):
        """Migrate Teachers collection"""
        try:
            teachers_collection = self.mongo_db.teachers
            total_teachers = teachers_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_teachers} teachers...")
            
            for teacher_doc in teachers_collection.find():
                try:
                    # Get user email if linked
                    user_email = self.get_user_email_by_mongo_id(str(teacher_doc.get('user'))) if teacher_doc.get('user') else None
                    
                    # Check if teacher already exists
                    if frappe.db.exists("ERP Teacher", {"teacher_name": teacher_doc.get('name')}):
                        logger.info(f"Teacher {teacher_doc.get('name')} already exists, skipping...")
                        continue
                    
                    new_teacher = frappe.get_doc({
                        "doctype": "ERP Teacher",
                        "teacher_name": teacher_doc.get('name'),
                        "employee_id": teacher_doc.get('employeeId'),
                        "user": user_email,
                        "email": teacher_doc.get('email'),
                        "phone": teacher_doc.get('phone'),
                        "department": teacher_doc.get('department'),
                        "qualification": teacher_doc.get('qualification'),
                        "specialization": teacher_doc.get('specialization'),
                        "hire_date": teacher_doc.get('hireDate'),
                        "status": teacher_doc.get('status', 'Active'),
                        "mongo_id": str(teacher_doc.get('_id'))
                    })
                    
                    new_teacher.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate teacher {teacher_doc.get('name', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("teachers", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("teachers", "failed", str(e))
            logger.error(f"Error migrating teachers: {str(e)}")
    
    def migrate_classes(self):
        """Migrate Classes collection"""
        try:
            classes_collection = self.mongo_db.classes
            total_classes = classes_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_classes} classes...")
            
            for class_doc in classes_collection.find():
                try:
                    # Get school name
                    school_name = None
                    if class_doc.get('school'):
                        school_name = self.get_school_name_by_mongo_id(str(class_doc.get('school')))
                    
                    # Get grade level name
                    grade_level_name = None
                    if class_doc.get('gradeLevel'):
                        grade_level_name = self.get_grade_level_name_by_mongo_id(str(class_doc.get('gradeLevel')))
                    
                    # Get homeroom teacher
                    homeroom_teacher = None
                    if class_doc.get('homeroomTeacher'):
                        homeroom_teacher = self.get_teacher_name_by_mongo_id(str(class_doc.get('homeroomTeacher')))
                    
                    # Check if class already exists
                    if frappe.db.exists("ERP Class", {"class_name": class_doc.get('name')}):
                        logger.info(f"Class {class_doc.get('name')} already exists, skipping...")
                        continue
                    
                    new_class = frappe.get_doc({
                        "doctype": "ERP Class",
                        "class_name": class_doc.get('name'),
                        "class_code": class_doc.get('code'),
                        "school": school_name,
                        "grade_level": grade_level_name,
                        "homeroom_teacher": homeroom_teacher,
                        "max_capacity": class_doc.get('maxCapacity', 30),
                        "current_enrollment": class_doc.get('currentEnrollment', 0),
                        "status": class_doc.get('status', 'Active'),
                        "mongo_id": str(class_doc.get('_id'))
                    })
                    
                    new_class.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate class {class_doc.get('name', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("classes", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("classes", "failed", str(e))
            logger.error(f"Error migrating classes: {str(e)}")
    
    def migrate_students(self):
        """Migrate Students collection"""
        try:
            students_collection = self.mongo_db.students
            total_students = students_collection.count_documents({})
            migrated_count = 0
            failed_count = 0
            
            logger.info(f"Starting migration of {total_students} students...")
            
            for student_doc in students_collection.find():
                try:
                    # Check if student already exists
                    if frappe.db.exists("ERP Student", {"student_id": student_doc.get('studentId')}):
                        logger.info(f"Student {student_doc.get('studentId')} already exists, skipping...")
                        continue
                    
                    new_student = frappe.get_doc({
                        "doctype": "ERP Student",
                        "student_id": student_doc.get('studentId'),
                        "first_name": student_doc.get('firstName'),
                        "last_name": student_doc.get('lastName'),
                        "full_name": f"{student_doc.get('firstName', '')} {student_doc.get('lastName', '')}".strip(),
                        "date_of_birth": student_doc.get('dateOfBirth'),
                        "gender": student_doc.get('gender'),
                        "nationality": student_doc.get('nationality'),
                        "address": student_doc.get('address'),
                        "phone": student_doc.get('phone'),
                        "email": student_doc.get('email'),
                        "emergency_contact": student_doc.get('emergencyContact'),
                        "admission_date": student_doc.get('admissionDate'),
                        "status": student_doc.get('status', 'Active'),
                        "mongo_id": str(student_doc.get('_id'))
                    })
                    
                    new_student.insert(ignore_permissions=True)
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to migrate student {student_doc.get('studentId', 'Unknown')}: {str(e)}")
                    failed_count += 1
            
            self.log_migration("students", "completed", 
                             f"Migrated: {migrated_count}, Failed: {failed_count}", 
                             migrated_count)
            
        except Exception as e:
            self.log_migration("students", "failed", str(e))
            logger.error(f"Error migrating students: {str(e)}")
    
    def get_school_name_by_mongo_id(self, mongo_id):
        """Get school name by MongoDB ID"""
        try:
            school = frappe.db.get_value("ERP School", {"mongo_id": mongo_id}, "school_name")
            return school
        except:
            return None
    
    def get_grade_level_name_by_mongo_id(self, mongo_id):
        """Get grade level name by MongoDB ID"""
        try:
            grade_level = frappe.db.get_value("ERP Grade Level", {"mongo_id": mongo_id}, "grade_name")
            return grade_level
        except:
            return None
    
    def get_teacher_name_by_mongo_id(self, mongo_id):
        """Get teacher name by MongoDB ID"""
        try:
            teacher = frappe.db.get_value("ERP Teacher", {"mongo_id": mongo_id}, "teacher_name")
            return teacher
        except:
            return None
    
    def run_sis_migration(self):
        """Run complete SIS migration"""
        logger.info("Starting SIS data migration...")
        
        if not self.connect_mongodb():
            return False
        
        try:
            # Migration order is important due to dependencies
            logger.info("=== Starting School Migration ===")
            self.migrate_schools()
            
            logger.info("=== Starting School Year Migration ===")
            self.migrate_school_years()
            
            logger.info("=== Starting Grade Level Migration ===")
            self.migrate_grade_levels()
            
            logger.info("=== Starting Subject Migration ===")
            self.migrate_subjects()
            
            logger.info("=== Starting Teacher Migration ===")
            self.migrate_teachers()
            
            logger.info("=== Starting Class Migration ===")
            self.migrate_classes()
            
            logger.info("=== Starting Student Migration ===")
            self.migrate_students()
            
            logger.info("=== SIS Migration Summary ===")
            for log_entry in self.migration_log:
                print(f"{log_entry['collection']}: {log_entry['status']} - {log_entry['record_count']} records")
            
            return True
            
        except Exception as e:
            logger.error(f"SIS migration failed: {str(e)}")
            return False
        finally:
            self.disconnect_mongodb()


@frappe.whitelist()
def start_sis_migration(mongo_uri=None, mongo_db_name=None):
    """API endpoint to start SIS migration"""
    try:
        migrator = SISDataMigration(mongo_uri, mongo_db_name)
        success = migrator.run_sis_migration()
        
        return {
            "status": "success" if success else "failed",
            "message": "SIS migration completed" if success else "SIS migration failed",
            "log": migrator.migration_log
        }
        
    except Exception as e:
        frappe.log_error(f"SIS migration error: {str(e)}", "SIS Migration")
        frappe.throw(_("SIS migration failed: {0}").format(str(e)))