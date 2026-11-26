import hmac

import httpx
from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from .auth import clear_session, current_user, login_required
from .supabase_gateway import SupabaseGateway
from .validation import local_deadline, normalize_username, validate_name
from urllib.parse import urlsplit

bp = Blueprint("main", __name__)


def csrf_token():
    return URLSafeTimedSerializer(current_app.secret_key, salt="family-login").dumps("family-login")


def valid_csrf_token(value):
    try:
        payload = URLSafeTimedSerializer(
            current_app.secret_key, salt="family-login"
        ).loads(value, max_age=3600)
        return hmac.compare_digest(payload, "family-login")
    except BadSignature:
        return False


def valid_request_origin():
    origin = request.headers.get("Origin")
    if not origin:
        return True
    if origin == "null":
        return request.headers.get("Sec-Fetch-Site") == "same-origin"
    return origin.rstrip("/") == request.host_url.rstrip("/")


def username_conflict(exc):
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    try:
        return exc.response.status_code == 409 and exc.response.json().get("code") == "23505"
    except (ValueError, AttributeError):
        return False


def safe_next(value):
    target = value or "/"
    parsed = urlsplit(target)
    return target if not parsed.scheme and not parsed.netloc and target.startswith("/") else "/"


def set_session_cookies(response, session_data):
    options = {
        "secure": current_app.config["COOKIE_SECURE"],
        "httponly": True,
        "samesite": "Lax",
        "path": "/",
    }
    response.set_cookie("access_token", session_data["access_token"], **options)
    response.set_cookie("refresh_token", session_data["refresh_token"], **options)
    return response


@bp.after_request
def security_headers(response):
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.path == "/" or request.path.startswith(("/c/", "/profile", "/api/", "/sign-in", "/auth/")):
        response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/api/health")
def health():
    configured = bool(current_app.config["SUPABASE_URL"] and current_app.config["SUPABASE_PUBLISHABLE_KEY"] and current_app.config["FAMILY_ACCESS_CODE"].strip())
    return {"status": "ok" if configured else "degraded"}, 200 if configured else 503


@bp.get("/")
def home():
    g.user = current_user()
    contests = []
    if g.user:
        try:
            contests = SupabaseGateway().rpc("list_my_contests")
        except Exception:
            flash("Contests are temporarily unavailable.", "error")
    return render_template("home.html", contests=contests, user=g.user)


@bp.route("/sign-in", methods=["GET"])
def sign_in():
    return render_template("sign_in.html", next_path=safe_next(request.args.get("next")), csrf=csrf_token())


@bp.post("/auth/family")
def family_sign_in():
    next_path = safe_next(request.form.get("next"))
    session_data = None

    def failure(message, status):
        flash(message, "error")
        response = current_app.make_response((render_template(
            "sign_in.html", next_path=next_path, csrf=csrf_token(),
            name=request.form.get("name", ""), username=request.form.get("username", ""),
        ), status))
        # Preserve a newly created/rotated identity so retrying a profile write
        # does not create another anonymous account (including ambiguous timeouts).
        return set_session_cookies(response, session_data) if session_data else response

    supplied_csrf = request.form.get("csrf", "")
    if not valid_csrf_token(supplied_csrf) or not valid_request_origin():
        return failure("Please reload the sign-in page and try again.", 400)

    configured_code = current_app.config["FAMILY_ACCESS_CODE"]
    if not configured_code.strip():
        return failure("Family sign-in is not configured. Ask the host to set FAMILY_ACCESS_CODE.", 503)
    supplied_code = request.form.get("access_code", "")
    if not hmac.compare_digest(configured_code.encode("utf-8"), supplied_code.encode("utf-8")):
        return failure("Incorrect family access code. Ask the host and try again.", 401)
    if not current_app.config["SUPABASE_URL"] or not current_app.config["SUPABASE_PUBLISHABLE_KEY"]:
        return failure("Sign-in is unavailable because Supabase is not configured. Contact the host.", 503)
    try:
        name = validate_name(request.form.get("name"))
        username = normalize_username(request.form.get("username"))
    except ValueError as exc:
        return failure(str(exc), 400)

    try:
        user = current_user(raise_on_error=True)
        if user:
            token = request.cookies["access_token"]
        else:
            refresh_token = request.cookies.get("refresh_token")
            candidate = (SupabaseGateway.refresh_session(refresh_token) if refresh_token
                         else SupabaseGateway.sign_in_anonymously())
            if not isinstance(candidate, dict) or not all(
                isinstance(candidate.get(key), str) and candidate[key]
                for key in ("access_token", "refresh_token")
            ):
                raise ValueError("Invalid authentication response")
            session_data = candidate
            token = session_data["access_token"]
        SupabaseGateway(token=token).rpc("upsert_my_profile", {"p_name": name, "p_username": username})
    except (httpx.HTTPError, ValueError) as exc:
        if username_conflict(exc):
            return failure("That username is already taken. Choose another username; it cannot recover a previous account.", 409)
        return failure("Sign-in or profile saving is temporarily unavailable. Retry with the same browser. If this continues, ask the host to check Supabase anonymous sign-ins and authentication settings.", 503)

    response = redirect(next_path)
    return set_session_cookies(response, session_data) if session_data else response


@bp.post("/auth/refresh")
def refresh():
    token = request.cookies.get("refresh_token")
    if not token:
        return {"error": "unauthorized"}, 401
    try:
        response = current_app.make_response(("", 204))
        return set_session_cookies(response, SupabaseGateway.refresh_session(token))
    except Exception:
        response = current_app.make_response((jsonify(error="unauthorized"), 401))
        return clear_session(response)


@bp.post("/auth/logout")
def logout():
    response = redirect(url_for("main.home"))
    token = request.cookies.get("access_token")
    if token:
        try:
            SupabaseGateway.revoke_session(token)
        except Exception:
            pass
    return clear_session(response)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        try:
            SupabaseGateway().rpc("upsert_my_profile", {"p_name": validate_name(request.form.get("name")), "p_username": normalize_username(request.form.get("username"))})
            return redirect(url_for("main.profile"))
        except ValueError as exc:
            flash(str(exc), "error")
        except Exception as exc:
            if username_conflict(exc):
                flash("That username is already taken. Choose another username.", "error")
            else:
                flash("Profile saving is temporarily unavailable. Please try again.", "error")
    try:
        profile_data = SupabaseGateway().rpc("get_my_profile")
    except Exception:
        profile_data = None
        flash("Profile is temporarily unavailable.", "error")
    return render_template("profile.html", user=g.user, profile=profile_data)


@bp.get("/contests/new")
@login_required
def new_contest():
    return render_template("contest_editor.html", contest=None)


@bp.post("/contests")
@login_required
def create_contest():
    try:
        timezone_name = request.form.get("timezone", "")
        deadline = local_deadline(request.form.get("deadline", ""), timezone_name, request.form.get("timezone_offset"))
        result = SupabaseGateway().rpc("create_draft", {"p_title": request.form.get("title", "").strip(), "p_description": request.form.get("description", "").strip(), "p_deadline_at": deadline.isoformat(), "p_creator_timezone": timezone_name, "p_questions": request.form.getlist("question")})
        if not result or not result.get("id"):
            raise ValueError("Supabase returned no contest id")
        flash("Draft created. You can edit, publish, or copy its stable link below.", "success")
        return redirect(url_for("main.contest", contest_id=result["id"]))
    except Exception:
        flash("Unable to create contest.", "error")
        return redirect(url_for("main.new_contest"))


@bp.get("/c/<uuid:contest_id>")
@login_required
def contest(contest_id):
    try:
        data = SupabaseGateway().rpc("get_contest_invitation", {"p_contest_id": str(contest_id)})
    except Exception:
        data = None
    return render_template("contest.html", contest=data, contest_id=contest_id), 200 if data else 404


@bp.route("/c/<uuid:contest_id>/edit", methods=["GET", "POST"])
@login_required
def edit_contest(contest_id):
    if request.method == "POST":
        try:
            timezone_name = request.form.get("timezone", "")
            deadline = local_deadline(request.form.get("deadline", ""), timezone_name, request.form.get("timezone_offset"))
            SupabaseGateway().rpc("edit_draft", {
                "p_contest_id": str(contest_id),
                "p_title": request.form.get("title", "").strip(),
                "p_description": request.form.get("description", "").strip(),
                "p_deadline_at": deadline.isoformat(),
                "p_creator_timezone": timezone_name,
                "p_questions": request.form.getlist("question"),
            })
            flash("Contest changes saved.", "success")
            return redirect(url_for("main.contest", contest_id=contest_id))
        except Exception:
            flash("Unable to save contest.", "error")
    try:
        contest_data = SupabaseGateway().rpc("get_my_contest_for_edit", {"p_contest_id": str(contest_id)})
    except Exception:
        contest_data = None
    return render_template("contest_editor.html", contest=contest_data)


@bp.post("/c/<uuid:contest_id>/publish")
@login_required
def publish(contest_id):
    try:
        SupabaseGateway().rpc("publish_contest", {"p_contest_id": str(contest_id)})
        flash("Contest published. Its share link is ready.", "success")
    except Exception:
        flash("Contest could not be published.", "error")
    return redirect(url_for("main.contest", contest_id=contest_id))


@bp.get("/c/<uuid:contest_id>/leaderboard")
@login_required
def leaderboard(contest_id):
    try:
        data = SupabaseGateway().rpc("get_leaderboard", {"p_contest_id": str(contest_id)})
    except Exception:
        flash("Standings are temporarily unavailable.", "error")
        return render_template("leaderboard.html", contest_id=contest_id, leaderboard=None), 503
    return render_template("leaderboard.html", contest_id=contest_id, leaderboard=data), 200 if data else 403


@bp.get("/api/contests/<uuid:contest_id>/leaderboard")
@login_required
def leaderboard_json(contest_id):
    try:
        data = SupabaseGateway().rpc("get_leaderboard", {"p_contest_id": str(contest_id)})
        if not data:
            return jsonify(error="forbidden"), 403
        return jsonify(data)
    except Exception:
        return jsonify(error="dependency_unavailable", message="Please try again."), 503


@bp.post("/c/<uuid:contest_id>/ballot")
@login_required
def ballot(contest_id):
    try:
        SupabaseGateway().rpc("submit_ballot", {"p_contest_id": str(contest_id), "p_answers": request.form.getlist("answer"), "p_expected_version": int(request.form.get("version", 0))})
        flash("Your complete ballot was saved.", "success")
        return redirect(url_for("main.contest", contest_id=contest_id))
    except Exception:
        flash("Your ballot could not be saved.", "error")
        return redirect(url_for("main.contest", contest_id=contest_id))


@bp.post("/c/<uuid:contest_id>/questions/<uuid:question_id>/resolve")
@login_required
def resolve(contest_id, question_id):
    try:
        SupabaseGateway().rpc("resolve_question", {"p_contest_id": str(contest_id), "p_question_id": str(question_id), "p_correct_answer": request.form.get("correct_answer") == "true", "p_confirmation": request.form.get("confirmation") == "yes"})
        flash("Result saved. Results are final.", "success")
    except Exception:
        flash("Result could not be saved.", "error")
    return redirect(url_for("main.leaderboard", contest_id=contest_id))
