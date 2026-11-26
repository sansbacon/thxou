from unittest.mock import patch
import re

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
            "deadline_display": "January 15, 2027 at 12:00 PM America/New_York",
            "published_at": "2026-11-25T23:00:00Z",
            "phase": "open",
            "is_creator": True,
            "can_edit": True,
            "can_publish": False,
            "can_submit": True,
            "can_view_leaderboard": True,
            "results_visible": True,
            "questions": [{"id": QUESTION_ID, "text": "Will this work?"}],
            "answers": {},
            "version": 0,
        }
    if name == "get_leaderboard":
        return {
            "title": "Test contest",
            "deadline_display": "January 15, 2027 at 12:00 PM America/New_York",
            "is_creator": True,
            "can_resolve": False,
            "phase": "open",
            "resolved_count": 0,
            "question_count": 1,
            "as_of": "2026-11-25T23:00:00Z",
            "standings": [],
            "questions": [{"id": QUESTION_ID, "text": "Will this work?", "resolved": False, "correct_answer": None}],
        }
    return None


def test_all_documented_routes_respond_without_external_calls():
    app = create_app(
        {
            "TESTING": True,
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "test-publishable-key",
            "FAMILY_ACCESS_CODE": "test-event-code",
        }
    )
    client = app.test_client()
    contest = f"/c/{CONTEST_ID}"

    with (
        patch("thxou.routes.current_user", return_value={"id": "user"}),
        patch("thxou.auth.current_user", return_value={"id": "user"}),
        patch.object(SupabaseGateway, "rpc", autospec=True, side_effect=lambda self, name, payload=None: rpc_result(name, payload)),
        patch.object(
            SupabaseGateway,
            "refresh_session",
            return_value={"access_token": "access-2", "refresh_token": "refresh-2"},
        ),
        patch.object(SupabaseGateway, "revoke_session"),
    ):
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200
        sign_in = client.get("/sign-in")
        assert sign_in.status_code == 200
        client.set_cookie("access_token", "access")
        csrf = re.search(rb'name="csrf" value="([^"]+)"', sign_in.data).group(1).decode()
        assert client.post(
            "/auth/family",
            data={"access_code": "test-event-code", "name": "Test User", "username": "tester", "csrf": csrf},
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
