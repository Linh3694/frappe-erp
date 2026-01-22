"""
Centralized Logging Module cho WIS Frappe Backend
Tất cả logs được output tới single file: sites/{site}/logs/logging.log
Format: JSON structured để dễ parse trên Grafana/Loki
"""

import logging
import json
import os
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any

import frappe


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter cho structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Vietnam timezone: UTC+7
        vietnam_tz = timezone(timedelta(hours=7))
        vn_time = datetime.now(vietnam_tz)
        
        log_entry = {
            "timestamp": vn_time.strftime("%d/%m/%Y %H:%M:%S"),  # Format: 12/11/2025 09:22:54
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present in record
        if hasattr(record, "user"):
            log_entry["user"] = record.user
        if hasattr(record, "action"):
            log_entry["action"] = record.action
        if hasattr(record, "resource"):
            log_entry["resource"] = record.resource
        if hasattr(record, "ip"):
            log_entry["ip"] = record.ip
        if hasattr(record, "response_time"):
            log_entry["response_time_ms"] = record.response_time
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "details"):
            log_entry["details"] = record.details
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry, ensure_ascii=False, default=str)


class CentralizedLogger:
    """Centralized logger instance cho toàn bộ WIS"""
    
    _instance = None
    _loggers = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CentralizedLogger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.setup_logging()
    
    @staticmethod
    def setup_logging():
        """Setup centralized logging configuration"""
        try:
            # Get site path from frappe
            site_path = frappe.get_site_path() if hasattr(frappe, 'local') and hasattr(frappe.local, 'site') else None
            
            if not site_path:
                return  # Skip if no site context
            
            # Ensure logs directory exists
            log_dir = os.path.join(site_path, 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
            log_file = os.path.join(log_dir, 'logging.log')
            
            # Create logger
            logger = logging.getLogger('wis_centralized')
            logger.setLevel(logging.INFO)
            logger.propagate = False
            
            # Remove existing handlers
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
            
            # Create rotating file handler (max 100MB per file, keep 20 backups)
            handler = RotatingFileHandler(
                log_file,
                maxBytes=100 * 1024 * 1024,  # 100MB
                backupCount=20
            )
            
            # Set formatter
            formatter = JSONFormatter()
            handler.setFormatter(formatter)
            
            # Add handler to logger
            logger.addHandler(handler)
            
            # Store in frappe for easy access
            frappe.wis_logger = logger
            
        except Exception as e:
            frappe.errprint(f"Failed to setup centralized logging: {str(e)}")
    
    @staticmethod
    def get_logger() -> logging.Logger:
        """Get the centralized logger instance"""
        if not hasattr(frappe, 'wis_logger'):
            CentralizedLogger.setup_logging()
        return frappe.wis_logger


def get_logger() -> logging.Logger:
    """Helper function to get logger"""
    return CentralizedLogger.get_logger()


def log_authentication(user: str, action: str, ip: str, status: str = "success", details: Optional[Dict[str, Any]] = None):
    """Log authentication events"""
    logger = get_logger()
    record = logging.LogRecord(
        name='wis_centralized',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg=f'Xác thực người dùng: {action}',
        args=(),
        exc_info=None
    )
    record.user = user
    record.action = action
    record.ip = ip
    record.status = status
    record.details = details or {}
    
    logger.handle(record)


def log_api_call(user: str, method: str, endpoint: str, response_time_ms: float, status_code: int, details: Optional[Dict[str, Any]] = None):
    """Log API calls with response time and colored indicators"""
    logger = get_logger()
    
    # Determine icon and level based on response time
    if response_time_ms > 3000:
        icon = "🔴"  # Red - very slow
        level = logging.WARNING
    elif response_time_ms > 1000:
        icon = "🟡"  # Yellow - medium
        level = logging.INFO
    else:
        icon = "🟢"  # Green - fast
        level = logging.INFO
    
    # Override level if error status code
    # Ensure status_code is int
    if not isinstance(status_code, int):
        status_code = 200
    
    if status_code >= 400:
        level = logging.WARNING
        if status_code >= 500:
            icon = "🔴"
    
    record = logging.LogRecord(
        name='wis_centralized',
        level=level,
        pathname='',
        lineno=0,
        msg=f'{icon} {method} {endpoint} ({response_time_ms:.0f}ms)',
        args=(),
        exc_info=None
    )
    record.user = user
    record.action = f'API {method}'
    record.resource = endpoint
    record.response_time = response_time_ms
    record.status_code = status_code
    record.details = details or {}
    
    logger.handle(record)


def log_file_operation(user: str, operation: str, filename: str, filesize_kb: float, doctype: str, docname: str, is_private: bool = False, details: Optional[Dict[str, Any]] = None):
    """Log file upload/delete operations"""
    logger = get_logger()
    record = logging.LogRecord(
        name='wis_centralized',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg=f'File {operation}: {filename}',
        args=(),
        exc_info=None
    )
    record.user = user
    record.action = f'File {operation}'
    record.resource = f'{doctype}/{docname}'
    record.details = {
        'filename': filename,
        'filesize_kb': filesize_kb,
        'attached_to_doctype': doctype,
        'attached_to_name': docname,
        'is_private': is_private,
        **(details or {})
    }
    
    logger.handle(record)


def log_crud_operation(doctype: str, operation: str, docname: str, user: str, changes: Optional[Dict[str, Any]] = None, details: Optional[Dict[str, Any]] = None):
    """Log CRUD operations on critical doctypes"""
    logger = get_logger()
    record = logging.LogRecord(
        name='wis_centralized',
        level=logging.INFO,
        pathname='',
        lineno=0,
        msg=f'{doctype} {operation}: {docname}',
        args=(),
        exc_info=None
    )
    record.user = user
    record.action = f'{doctype} {operation}'
    record.resource = f'{doctype}/{docname}'
    record.details = {
        'doctype': doctype,
        'docname': docname,
        'operation': operation,
        'changes': changes or {},
        **(details or {})
    }
    
    logger.handle(record)


def log_error(user: str, action: str, error_message: str, resource: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
    """Log errors with details"""
    logger = get_logger()
    
    # Format error message with icon
    msg = f'❌ {action}'
    if resource:
        msg += f' | {resource}'
    msg += f' | {error_message}'
    
    record = logging.LogRecord(
        name='wis_centralized',
        level=logging.ERROR,
        pathname='',
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None
    )
    record.user = user
    record.action = action
    if resource:
        record.resource = resource
    record.details = {
        'error_message': error_message,
        'timestamp': datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M:%S"),
        **(details or {})
    }
    
    logger.handle(record)


def log_http_error(user: str, method: str, endpoint: str, status_code: int, error_message: str, response_time_ms: float = 0, details: Optional[Dict[str, Any]] = None):
    """Log HTTP errors (4xx, 5xx responses)"""
    logger = get_logger()
    
    # Determine error severity
    if status_code >= 500:
        icon = "❌"
        level = logging.ERROR
        severity = "Server Error"
    elif status_code >= 400:
        icon = "⚠️"
        level = logging.WARNING
        severity = "Client Error"
    else:
        icon = "❌"
        level = logging.ERROR
        severity = "Error"
    
    msg = f'{icon} {severity} {status_code} | {method} {endpoint}'
    if response_time_ms > 0:
        msg += f' ({response_time_ms:.0f}ms)'
    msg += f' | {error_message[:100]}'
    
    record = logging.LogRecord(
        name='wis_centralized',
        level=level,
        pathname='',
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None
    )
    record.user = user
    record.action = f'HTTP {status_code}'
    record.resource = endpoint
    record.status_code = status_code
    record.response_time = response_time_ms
    record.details = {
        'status_code': status_code,
        'method': method,
        'endpoint': endpoint,
        'error_message': error_message,
        'response_time_ms': response_time_ms,
        'timestamp': datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M:%S"),
        **(details or {})
    }
    
    logger.handle(record)

