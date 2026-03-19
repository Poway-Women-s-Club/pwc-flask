"""
Shared utilities for validation, authorization, and error handling.

Each function has a single responsibility:
- require_json: parse and validate request body
- require_fields: check that required fields are present
- require_auth: verify user is logged in
- require_admin: verify user is admin
- handle_errors: decorator that catches exceptions and returns consistent error responses
"""

from functools import wraps
from flask import request, jsonify
from flask_login import current_user


class APIError(Exception):
    """Raised when an API operation fails in an expected way."""
    def __init__(self, message, status_code=400):
        self.message = message
        self.status_code = status_code


def require_json():
    """Parse JSON body from request. Raises APIError if missing or invalid."""
    data = request.get_json(silent=True)
    if not data:
        raise APIError("Request body must be valid JSON", 400)
    return data


def require_fields(data, *fields):
    """Check that all required fields are present and non-empty in data dict."""
    missing = [f for f in fields if not data.get(f)]
    if missing:
        raise APIError(f"Missing required fields: {', '.join(missing)}", 400)


def require_auth():
    """Return current user or raise APIError if not authenticated."""
    if not current_user.is_authenticated:
        raise APIError("Login required", 401)
    return current_user


def require_admin():
    """Return current user or raise APIError if not admin."""
    user = require_auth()
    if user.role != "admin":
        raise APIError("Admin access required", 403)
    return user


def require_owner_or_admin(resource_owner_id):
    """Check that current user owns the resource or is admin."""
    user = require_auth()
    if user.id != resource_owner_id and user.role != "admin":
        raise APIError("Not authorized", 403)
    return user


def handle_errors(f):
    """
    Decorator that wraps a route function with consistent error handling.
    Catches APIError for expected failures, and Exception for unexpected ones.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except APIError as e:
            return jsonify({"error": e.message}), e.status_code
        except Exception as e:
            # Log the real error for debugging, return generic message to client
            print(f"[ERROR] {f.__name__}: {e}")
            return jsonify({"error": "An unexpected error occurred"}), 500
    return decorated