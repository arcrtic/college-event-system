"""
Centralized validation so every feature (events, resources, requests)
raises the same kind of error and the UI can render it the same way.
Using a single ValidationError type (instead of letting raw ValueError /
KeyError bubble up) is what lets the route layer turn failures into a
flash message instead of a Python traceback -- required by section 9.
"""
from datetime import datetime


class ValidationError(Exception):
    """Raised for any user-facing validation failure."""
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def parse_datetime(value, field_label="date/time"):
    """
    Accepts the string format produced by an HTML <input type="datetime-local">
    (e.g. '2026-09-20T10:00') and returns a datetime, or raises ValidationError.
    """
    if not value:
        raise ValidationError(f"{field_label} is required.")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise ValidationError(f"{field_label} is not a valid date/time.")


def validate_event_window(start_dt, end_dt):
    if end_dt <= start_dt:
        raise ValidationError("Event end time must be after the start time.")


def validate_attendance(value):
    try:
        attendance = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Expected attendance must be a whole number.")
    if attendance <= 0:
        raise ValidationError("Expected attendance must be a positive number.")
    return attendance


def require_text(value, field_label):
    if not value or not value.strip():
        raise ValidationError(f"{field_label} is required.")
    return value.strip()
