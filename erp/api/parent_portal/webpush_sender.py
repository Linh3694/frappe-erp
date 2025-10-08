"""
Simplified Web Push Sender
Không cần pywebpush, chỉ dùng requests và cryptography
"""

import json
import base64
from urllib.parse import urlparse

try:
    import requests
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    import os
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install requests cryptography")


def send_web_push(subscription_info, data, vapid_private_key, vapid_claims):
    """
    Gửi web push notification đơn giản
    
    Args:
        subscription_info: Dict chứa endpoint, keys (p256dh, auth)
        data: String data để gửi
        vapid_private_key: VAPID private key (PEM format)
        vapid_claims: Dict với "sub" key (mailto:email)
    
    Returns:
        requests.Response object
    """
    
    # Parse subscription
    endpoint = subscription_info.get("endpoint")
    p256dh = subscription_info.get("keys", {}).get("p256dh")
    auth = subscription_info.get("keys", {}).get("auth")
    
    if not all([endpoint, p256dh, auth]):
        raise ValueError("Invalid subscription_info")
    
    # Prepare payload
    if isinstance(data, dict):
        data = json.dumps(data)
    
    payload = data.encode('utf-8') if isinstance(data, str) else data
    
    # For simplicity, send without encryption if payload is small
    # Production should implement proper encryption
    
    # Generate VAPID headers
    headers = generate_vapid_headers(
        endpoint=endpoint,
        vapid_private_key=vapid_private_key,
        vapid_claims=vapid_claims
    )
    
    # Add content headers
    headers.update({
        'Content-Type': 'application/octet-stream',
        'Content-Encoding': 'aes128gcm',
        'TTL': '86400'  # 24 hours
    })
    
    # Send request
    response = requests.post(
        endpoint,
        data=payload,
        headers=headers,
        timeout=10
    )
    
    return response


def generate_vapid_headers(endpoint, vapid_private_key, vapid_claims):
    """
    Generate VAPID authorization headers
    
    Simplified version - for production use proper JWT signing
    """
    try:
        import jwt
        from datetime import datetime, timedelta
        
        # Parse endpoint to get audience
        parsed = urlparse(endpoint)
        audience = f"{parsed.scheme}://{parsed.netloc}"
        
        # Create JWT claims
        claims = {
            "aud": audience,
            "exp": datetime.utcnow() + timedelta(hours=12),
            "sub": vapid_claims.get("sub", "mailto:admin@example.com")
        }
        
        # Sign JWT with private key
        token = jwt.encode(
            claims,
            vapid_private_key,
            algorithm="ES256"
        )
        
        # Get public key from private key for header
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        
        private_key = serialization.load_pem_private_key(
            vapid_private_key.encode() if isinstance(vapid_private_key, str) else vapid_private_key,
            password=None,
            backend=default_backend()
        )
        
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        
        public_key_b64 = base64.urlsafe_b64encode(public_bytes).decode('utf-8').rstrip('=')
        
        return {
            'Authorization': f'vapid t={token}, k={public_key_b64}'
        }
        
    except ImportError:
        print("PyJWT not installed, using basic headers")
        return {
            'Authorization': 'vapid t=, k='
        }


def send_simple_notification(subscription_info, title, body, icon=None, data=None):
    """
    Wrapper đơn giản để gửi notification
    Sử dụng khi không có VAPID setup
    """
    endpoint = subscription_info.get("endpoint")
    
    payload = {
        "title": title,
        "body": body,
        "icon": icon or "/icon.png",
        "data": data or {}
    }
    
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers={
                'Content-Type': 'application/json',
                'TTL': '86400'
            },
            timeout=10
        )
        return response
    except Exception as e:
        print(f"Error sending notification: {e}")
        return None

