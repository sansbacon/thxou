from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for
from .auth import clear_session, current_user, login_required
from .supabase_gateway import SupabaseGateway
from .validation import local_deadline, normalize_username, validate_name
from urllib.parse import urlsplit

bp = Blueprint("main", __name__)


def csrf_token():
    return request.form.get("csrf") or request.args.get("csrf")


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
    if request.path.startswith("/c/") or request.path.startswith("/profile") or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/api/health")
def health():
    configured = bool(current_app.config["SUPABASE_URL"] and current_app.config["SUPABASE_PUBLISHABLE_KEY"])
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
    return render_template("sign_in.html", next_path=request.args.get("next", "/"))


@bp.post("/auth/otp/request")
def otp_request():
    phone = request.form.get("phone", "").strip()
    try:
        SupabaseGateway.request_otp(phone, request.form.get("captcha_token", ""))
    except Exception:
        flash("Unable to send a code. Check the details and try again.", "error")
        return render_template("sign_in.html", next_path=safe_next(request.form.get("next")), pending_phone=phone), 503
    return render_template("sign_in.html", next_path=safe_next(request.form.get("next")), pending_phone=phone, sent=True)


@bp.post("/auth/otp/verify")
def otp_verify():
    try:
        session_data = SupabaseGateway.verify_otp(
            request.form.get("phone", "").strip(),
            request.form.get("code", "").strip(),
        )
        response = redirect(safe_next(request.form.get("next")))
        return set_session_cookies(response, session_data)
    except Exception:
        flash("The code is invalid or expired.", "error")
        return render_template(
            "sign_in.html",
            next_path=safe_next(request.form.get("next")),
            pending_phone=request.form.get("phone", "").strip(),
            sent=True,
        ), 400


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
        except Exception:
            flash("Unable to save profile.", "error")
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
    return render_template("contest.html", contest=data, contest_id=contest_id)


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
    except Exception:
        flash("Contest could not be published.", "error")
    return redirect(url_for("main.contest", contest_id=contest_id))


@bp.get("/c/<uuid:contest_id>/leaderboard")
@login_required
def leaderboard(contest_id):
    return render_template("leaderboard.html", contest_id=contest_id)


@bp.get("/api/contests/<uuid:contest_id>/leaderboard")
@login_required
def leaderboard_json(contest_id):
    try:
        return jsonify(SupabaseGateway().rpc("get_leaderboard", {"p_contest_id": str(contest_id)}))
    except Exception:
        return jsonify(error="dependency_unavailable", message="Please try again."), 503


@bp.post("/c/<uuid:contest_id>/ballot")
@login_required
def ballot(contest_id):
    try:
        SupabaseGateway().rpc("submit_ballot", {"p_contest_id": str(contest_id), "p_answers": request.form.getlist("answer"), "p_expected_version": int(request.form.get("version", 0))})
        return redirect(url_for("main.contest", contest_id=contest_id))
    except Exception:
        flash("Your ballot could not be saved.", "error")
        return redirect(url_for("main.contest", contest_id=contest_id))


@bp.post("/c/<uuid:contest_id>/questions/<uuid:question_id>/resolve")
@login_required
def resolve(contest_id, question_id):
    try:
        SupabaseGateway().rpc("resolve_question", {"p_contest_id": str(contest_id), "p_question_id": str(question_id), "p_correct_answer": request.form.get("correct_answer") == "true", "p_confirmation": request.form.get("confirmation") == "yes"})
    except Exception:
        flash("Result could not be saved.", "error")
    return redirect(url_for("main.leaderboard", contest_id=contest_id))
