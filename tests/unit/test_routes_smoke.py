from unittest.mock import patch

from thxou import create_app
from thxou.routes import safe_next
from thxou.supabase_gateway import SupabaseGateway


CONTEST_ID = "11111111-1111-4111-8111-111111111111"
QUESTION_ID = "22222222-2222-4222-8222-222222222222"


def test_safe_next_defaults_missing_and_external_targets_to_home():
    assert safe_next(None) == "/"
    assert safe_next("https://example.com") == "/"
    assert safe_next("/contests/new") == "/contests/new"


def rpc_result(name, payload=None):
    if name == "list_my_contests":
        return []
    if name == "get_my_profile":
        return {"name": "Test User", "username": "tester"}
    if name == "create_draft":
        return {"id": CONTEST_ID}
    if name in {"get_contest_invitation", "get_my_contest_for_edit"}:
        return {
            "id": CONTEST_ID,
            "title": "Test contest",
            "description": "",
            "creator_timezone": "America/New_York",
            "questions": [{"id": QUESTION_ID, "text": "Will this work?"}],
            "answers": {},
            "version": 0,
        }
    if name == "get_leaderboard":
        return {
            "phase": "open",
            "resolved_count": 0,
            "question_count": 1,
            "as_of": "2026-11-25T23:00:00Z",
            "standings": [],
        }
    return None


def test_all_documented_routes_respond_without_external_calls():
    app = create_app(
        {
            "TESTING": True,
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "test-publishable-key",
        }
    )
    client = app.test_client()
    contest = f"/c/{CONTEST_ID}"

    with (
        patch("thxou.routes.current_user", return_value={"id": "user"}),
        patch("thxou.auth.current_user", return_value={"id": "user"}),
        patch.object(SupabaseGateway, "rpc", autospec=True, side_effect=lambda self, name, payload=None: rpc_result(name, payload)),
        patch.object(SupabaseGateway, "request_otp"),
        patch.object(
            SupabaseGateway,
            "verify_otp",
            return_value={"access_token": "access", "refresh_token": "refresh"},
        ),
        patch.object(
            SupabaseGateway,
            "refresh_session",
            return_value={"access_token": "access-2", "refresh_token": "refresh-2"},
        ),
        patch.object(SupabaseGateway, "revoke_session"),
    ):
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/sign-in").status_code == 200
        assert client.post("/auth/otp/request", data={"phone": "+15555550100"}).status_code == 200
        assert client.post(
            "/auth/otp/verify",
            data={"phone": "+15555550100", "code": "000000"},
        ).status_code == 302
        client.set_cookie("refresh_token", "refresh")
        assert client.post("/auth/refresh").status_code == 204
        client.set_cookie("access_token", "access")
        assert client.post("/auth/logout").status_code == 302
        assert client.get("/profile").status_code == 200
        assert client.post("/profile", data={"name": "Test User", "username": "tester"}).status_code == 302
        assert client.get("/contests/new").status_code == 200
        contest_form = {
            "title": "Test contest",
            "deadline": "2027-01-15T12:00",
            "timezone": "America/New_York",
            "question": "Will this work?",
        }
        assert client.post("/contests", data=contest_form).status_code == 302
        assert client.get(contest).status_code == 200
        assert client.get(f"{contest}/edit").status_code == 200
        assert client.post(f"{contest}/edit", data=contest_form).status_code == 302
        assert client.post(f"{contest}/publish").status_code == 302
        assert client.get(f"{contest}/leaderboard").status_code == 200
        assert client.get(f"/api/contests/{CONTEST_ID}/leaderboard").status_code == 200
        assert client.post(
            f"{contest}/ballot",
            data={"answer": f"{QUESTION_ID}:true", "version": "0"},
        ).status_code == 302
        assert client.post(
            f"{contest}/questions/{QUESTION_ID}/resolve",
            data={"correct_answer": "true", "confirmation": "yes"},
        ).status_code == 302
