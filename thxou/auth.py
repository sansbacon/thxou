from functools import wraps
from flask import current_app, g, redirect, request, session, url_for
import httpx


def _client():
    return httpx.Client(base_url=current_app.config["SUPABASE_URL"], timeout=current_app.config["DATA_TIMEOUT"])


def current_user():
    token = request.cookies.get("access_token")
    if not token or not current_app.config["SUPABASE_URL"]:
        return None
    try:
        response = _client().get("/auth/v1/user", headers={"apikey": current_app.config["SUPABASE_PUBLISHABLE_KEY"], "Authorization": f"Bearer {token}"})
        return response.json() if response.is_success else None
    except httpx.HTTPError:
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        g.user = current_user()
        if not g.user:
            if request.path.startswith("/api/"):
                return {"error": "unauthorized"}, 401
            return redirect(url_for("main.sign_in", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def clear_session(response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    session.clear()
    return response
