import json
import re
from unittest.mock import patch

import httpx
import pytest

from thxou import create_app
from thxou.supabase_gateway import SupabaseGateway


def make_client(**config):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "unit-test-only-secret",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "test-publishable-key",
        "FAMILY_ACCESS_CODE": "private-test-code",
        "APP_BASE_URL": "http://localhost",
        **config,
    }).test_client()


def submit(client, **fields):
    page = client.get("/sign-in")
    csrf = re.search(rb'name="csrf" value="([^"]+)"', page.data).group(1).decode()
    return client.post("/auth/family", data={
        "csrf": csrf, "access_code": "private-test-code",
        "name": " Guest ", "username": " Guest_1 ", **fields,
    })


def dependency_error(status=503, code="unavailable"):
    response = httpx.Response(status, json={"code": code, "message": "private dependency details"},
                              request=httpx.Request("POST", "https://example.supabase.co/"))
    return httpx.HTTPStatusError("private dependency details", request=response.request, response=response)


@pytest.mark.parametrize("code,status,message", [
    ("", 503, b"FAMILY_ACCESS_CODE"),
    ("   ", 503, b"FAMILY_ACCESS_CODE"),
    ("different", 401, b"Incorrect family access code"),
])
def test_missing_or_wrong_passcode_fails_before_auth(code, status, message):
    client = make_client(FAMILY_ACCESS_CODE=code)
    with patch.object(SupabaseGateway, "sign_in_anonymously") as signup:
        response = submit(client)
    assert response.status_code == status
    assert message in response.data
    assert b"private-test-code" not in response.data
    signup.assert_not_called()
    assert client.get_cookie("access_token") is None


def test_passcode_uses_constant_time_comparison_and_handles_unicode():
    client = make_client(FAMILY_ACCESS_CODE="private-test-code-ü")
    with patch("thxou.routes.hmac.compare_digest", wraps=__import__("hmac").compare_digest) as compare:
        response = submit(client, access_code="wrong-ü")
    assert response.status_code == 401
    compare.assert_any_call("private-test-code-ü".encode(), "wrong-ü".encode())


@pytest.mark.parametrize("fields", [
    {"name": ""}, {"name": "x" * 81}, {"username": "admin"},
    {"username": "ab"}, {"username": "two words"}, {"username": "x" * 25},
])
def test_existing_validators_run_before_signup(fields):
    with patch.object(SupabaseGateway, "sign_in_anonymously") as signup:
        assert submit(make_client(), **fields).status_code == 400
    signup.assert_not_called()


def test_login_requires_csrf_and_rejects_cross_origin():
    client = make_client()
    with patch.object(SupabaseGateway, "sign_in_anonymously") as signup:
        assert client.post("/auth/family").status_code == 400
        page = client.get("/sign-in")
        csrf = re.search(rb'name="csrf" value="([^"]+)"', page.data).group(1).decode()
        assert client.post("/auth/family", data={"csrf": csrf},
                           headers={"Origin": "https://other.example"}).status_code == 400
    signup.assert_not_called()


def test_login_csrf_does_not_require_a_prelogin_cookie():
    page = make_client().get("/sign-in")
    csrf = re.search(rb'name="csrf" value="([^"]+)"', page.data).group(1).decode()
    client = make_client()

    response = client.post("/auth/family", data={
        "csrf": csrf,
        "access_code": "wrong-code",
        "name": "Guest",
        "username": "guest_1",
    })

    assert response.status_code == 401
    assert b"Incorrect family access code" in response.data


def test_login_allows_null_origin_only_for_same_origin_navigation():
    page = make_client().get("/sign-in")
    csrf = re.search(rb'name="csrf" value="([^"]+)"', page.data).group(1).decode()

    accepted = make_client().post("/auth/family", data={
        "csrf": csrf,
        "access_code": "wrong-code",
        "name": "Guest",
        "username": "guest_1",
    }, headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
    rejected = make_client().post("/auth/family", data={
        "csrf": csrf,
    }, headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"})

    assert accepted.status_code == 401
    assert b"Incorrect family access code" in accepted.data
    assert rejected.status_code == 400
    assert b"Please reload the sign-in page" in rejected.data


def test_live_adapter_contract_profile_and_cookie_wiring(caplog):
    client = make_client(COOKIE_SECURE=True)
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["apikey"] == "test-publishable-key"
        if request.url.path == "/auth/v1/signup":
            assert json.loads(request.content) == {}
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})
        assert request.headers["authorization"] == "Bearer access"
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": "anonymous-user", "is_anonymous": True})
        if request.url.path == "/rest/v1/rpc/list_my_contests":
            return httpx.Response(200, json=[])
        if request.url.path == "/rest/v1/rpc/upsert_my_profile":
            assert json.loads(request.content) == {"p_name": "Guest", "p_username": "guest_1"}
        else:
            assert request.url.path == "/rest/v1/rpc/get_my_profile"
        return httpx.Response(200, json={"name": "Guest", "username": "guest_1"})

    real_client = httpx.Client
    with patch("thxou.supabase_gateway.httpx.Client",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
        response = submit(client, next="/contests/new", phone="ignored")
        profile = client.get("/profile")
        assert profile.status_code == 200
        assert b'value="Guest"' in profile.data
        assert b'value="guest_1"' in profile.data
        assert client.get("/").status_code == 200
    assert response.status_code == 302
    assert response.location == "/contests/new"
    assert len(calls) == 6
    assert all(b"private-test-code" not in r.content and b"phone" not in r.content for r in calls)
    assert "private-test-code" not in caplog.text
    cookies = response.headers.getlist("Set-Cookie")
    for name in ("access_token", "refresh_token"):
        cookie = next(c for c in cookies if c.startswith(name + "="))
        assert all(attribute in cookie for attribute in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"))
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("error", [
    dependency_error(), dependency_error(422, "anonymous_provider_disabled"),
    dependency_error(429, "over_request_rate_limit"), httpx.ConnectError("private dependency details"),
])
def test_auth_dependency_errors_are_explicit_and_redacted(error, caplog):
    client = make_client()
    with patch.object(SupabaseGateway, "sign_in_anonymously", side_effect=error):
        response = submit(client)
    assert response.status_code == 503
    assert b"Supabase anonymous sign-ins" in response.data
    assert b"private dependency details" not in response.data
    assert "private dependency details" not in caplog.text
    assert client.get_cookie("access_token") is None


@pytest.mark.parametrize("candidate", [{}, {"access_token": "access"}, None])
def test_malformed_auth_response_does_not_set_auth_cookies(candidate):
    client = make_client()
    with patch.object(SupabaseGateway, "sign_in_anonymously", return_value=candidate):
        assert submit(client).status_code == 503
    assert client.get_cookie("access_token") is None


@pytest.mark.parametrize("error,status,message", [
    (dependency_error(409, "23505"), 409, b"username is already taken"),
    (httpx.ReadTimeout("private dependency details"), 503, b"temporarily unavailable"),
])
def test_failed_profile_save_retains_identity_and_retry_reuses_it(error, status, message):
    client = make_client()
    with (
        patch.object(SupabaseGateway, "sign_in_anonymously",
                     return_value={"access_token": "access", "refresh_token": "refresh"}) as signup,
        patch.object(SupabaseGateway, "rpc", side_effect=error),
    ):
        response = submit(client)
    assert response.status_code == status
    assert message in response.data
    assert b'value=" Guest "' in response.data
    assert b"private-test-code" not in response.data
    assert client.get_cookie("access_token").value == "access"
    signup.assert_called_once()
    with (
        patch("thxou.routes.current_user", return_value={"id": "same-user"}),
        patch.object(SupabaseGateway, "sign_in_anonymously") as signup,
        patch.object(SupabaseGateway, "rpc", autospec=True) as rpc,
    ):
        assert submit(client, username="another_name").status_code == 302
    signup.assert_not_called()
    gateway = rpc.call_args.args[0]
    assert gateway.headers["Authorization"] == "Bearer access"
    assert rpc.call_args.args[2] == {"p_name": "Guest", "p_username": "another_name"}


def test_expired_access_refreshes_existing_identity():
    client = make_client()
    client.set_cookie("refresh_token", "original-refresh")
    with (
        patch.object(SupabaseGateway, "refresh_session",
                     return_value={"access_token": "rotated-access", "refresh_token": "rotated-refresh"}) as refresh,
        patch.object(SupabaseGateway, "sign_in_anonymously") as signup,
        patch.object(SupabaseGateway, "rpc", autospec=True) as rpc,
    ):
        assert submit(client).status_code == 302
    refresh.assert_called_once_with("original-refresh")
    signup.assert_not_called()
    assert rpc.call_args.args[0].token == "rotated-access"
    assert client.get_cookie("refresh_token").value == "rotated-refresh"


def test_user_validation_outage_does_not_create_new_identity():
    client = make_client()
    client.set_cookie("access_token", "existing-access")
    real_client = httpx.Client
    with (
        patch("thxou.auth.httpx.Client", side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kw)),
        patch.object(SupabaseGateway, "sign_in_anonymously") as signup,
    ):
        assert submit(client).status_code == 503
    signup.assert_not_called()
    assert client.get_cookie("access_token").value == "existing-access"


def test_refresh_failure_does_not_silently_replace_identity():
    client = make_client()
    client.set_cookie("refresh_token", "original-refresh")
    with (
        patch.object(SupabaseGateway, "refresh_session", side_effect=dependency_error(401)),
        patch.object(SupabaseGateway, "sign_in_anonymously") as signup,
    ):
        assert submit(client).status_code == 503
    signup.assert_not_called()
    assert client.get_cookie("refresh_token").value == "original-refresh"


def test_wrong_passcode_cannot_update_an_existing_session_profile():
    client = make_client()
    client.set_cookie("access_token", "existing-access")
    with (
        patch("thxou.routes.current_user") as user,
        patch.object(SupabaseGateway, "rpc") as rpc,
    ):
        assert submit(client, access_code="wrong").status_code == 401
    user.assert_not_called()
    rpc.assert_not_called()


def test_missing_supabase_configuration_and_health():
    client = make_client(SUPABASE_URL="")
    assert submit(client).status_code == 503
    assert client.get("/api/health").status_code == 503
    assert make_client(FAMILY_ACCESS_CODE="").get("/api/health").status_code == 503
    assert make_client().get("/api/health").status_code == 200


def test_active_ui_has_no_phone_captcha_or_otp_routes():
    client = make_client()
    html = client.get("/sign-in").data.lower()
    assert b'type="password"' in html
    assert b"private-test-code" not in html
    assert all(word not in html for word in (b"phone", b"captcha", b"twilio", b"turnstile"))
    assert client.post("/auth/otp/request").status_code == 404
    assert client.post("/auth/otp/verify").status_code == 404
    with patch("thxou.auth.current_user", return_value={"id": "user"}), patch.object(SupabaseGateway, "rpc"):
        assert b"phone" not in client.get("/profile").data.lower()


def test_profile_edit_reports_duplicate_username():
    with (
        patch("thxou.auth.current_user", return_value={"id": "user"}),
        patch.object(SupabaseGateway, "rpc", side_effect=dependency_error(409, "23505")),
    ):
        response = make_client().post("/profile", data={"name": "Guest", "username": "guest_1"})
    assert b"username is already taken" in response.data


def test_external_next_does_not_redirect_off_site():
    with (
        patch.object(SupabaseGateway, "sign_in_anonymously",
                     return_value={"access_token": "access", "refresh_token": "refresh"}),
        patch.object(SupabaseGateway, "rpc"),
    ):
        assert submit(make_client(), next="https://other.example").location == "/"
