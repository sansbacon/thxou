from datetime import datetime, timezone


def error_code(exc):
    return {"error": "dependency_unavailable", "message": "Please try again."} if exc else None


def phase(deadline_at, resolved_count, question_count, published):
    if not published:
        return "draft"
    if datetime.now(timezone.utc) < deadline_at:
        return "open"
    if resolved_count == question_count:
        return "completed"
    return "resolving"
