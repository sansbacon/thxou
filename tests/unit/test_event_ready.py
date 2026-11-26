from pathlib import Path
from unittest.mock import patch

from thxou import create_app
from thxou.supabase_gateway import SupabaseGateway


CONTEST_ID = "11111111-1111-4111-8111-111111111111"
QUESTION_ID = "22222222-2222-4222-8222-222222222222"
ROOT = Path(__file__).parents[2]


def app_client():
    app = create_app({
        "TESTING": True,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "test-key",
        "FAMILY_ACCESS_CODE": "event-code",
        "SERVER_NAME": "example.test",
    })
    return app.test_client()


def contest_projection(*, creator):
    return {
        "id": CONTEST_ID,
        "title": "Event picks",
        "description": "Pick carefully.",
        "deadline_display": "November 26, 2026 at 3:00 PM America/New_York",
        "published_at": None if creator else "2026-11-25T12:00:00Z",
        "phase": "draft" if creator else "open",
        "is_creator": creator,
        "can_edit": creator,
        "can_publish": creator,
        "can_view_leaderboard": creator,
        "can_submit": not creator,
        "results_visible": creator,
        "questions": [{"id": QUESTION_ID, "text": "Will it happen?", "resolved": None, "correct_answer": None}],
        "answers": {},
        "version": 0,
    }


def leaderboard_projection(*, creator):
    return {
        "title": "Event picks",
        "deadline_display": "November 26, 2026 at 3:00 PM America/New_York",
        "phase": "resolving",
        "is_creator": creator,
        "can_resolve": creator,
        "as_of": "2026-11-26T21:00:00Z",
        "standings": [],
        "questions": [
            {"id": QUESTION_ID, "text": "Will it happen?", "resolved": False, "correct_answer": None},
            {"id": "33333333-3333-4333-8333-333333333333", "text": "Was it late?", "resolved": True, "correct_answer": False},
        ],
    }


def authenticated():
    return (
        patch("thxou.routes.current_user", return_value={"id": "actor"}),
        patch("thxou.auth.current_user", return_value={"id": "actor"}),
    )


def test_new_draft_redirects_to_stable_creator_page_with_actions():
    client = app_client()

    def rpc(_self, name, payload=None):
        if name == "create_draft":
            return {"id": CONTEST_ID}
        if name == "get_contest_invitation":
            return contest_projection(creator=True)
        return None

    route_user, auth_user = authenticated()
    with route_user, auth_user, patch.object(SupabaseGateway, "rpc", autospec=True, side_effect=rpc):
        response = client.post("/contests", data={
            "title": "Event picks", "deadline": "2027-01-15T12:00",
            "timezone": "America/New_York", "question": "Will it happen?",
        })
        assert response.headers["Location"].endswith(f"/c/{CONTEST_ID}")
        page = client.get(response.headers["Location"]).data

    assert b"Draft created" in page
    assert b"Creator actions" in page
    assert b">Edit<" in page and b">Publish<" in page and b">Leaderboard<" in page
    assert b"Stable share URL" in page and f"/c/{CONTEST_ID}".encode() in page


def test_participant_projection_has_ballot_but_no_creator_actions():
    client = app_client()
    route_user, auth_user = authenticated()
    with route_user, auth_user, patch.object(
        SupabaseGateway, "rpc", autospec=True,
        side_effect=lambda _self, name, payload=None: contest_projection(creator=False),
    ):
        page = client.get(f"/c/{CONTEST_ID}").data

    assert b"Save complete ballot" in page
    assert b"Creator actions" not in page
    assert b"Stable share URL" not in page
    assert b"/publish" not in page and b"/edit" not in page


def test_result_entry_is_creator_only_and_resolved_values_are_immutable():
    client = app_client()
    route_user, auth_user = authenticated()
    with route_user, auth_user, patch.object(
        SupabaseGateway, "rpc", autospec=True,
        side_effect=lambda _self, name, payload=None: leaderboard_projection(creator=True),
    ):
        creator_page = client.get(f"/c/{CONTEST_ID}/leaderboard").data
    assert b"Enter results" in creator_page
    assert f"/questions/{QUESTION_ID}/resolve".encode() in creator_page
    assert b'value="true"' in creator_page and b'value="false"' in creator_page
    assert b"Final result: No (immutable)" in creator_page

    route_user, auth_user = authenticated()
    with route_user, auth_user, patch.object(
        SupabaseGateway, "rpc", autospec=True,
        side_effect=lambda _self, name, payload=None: leaderboard_projection(creator=False),
    ):
        participant_page = client.get(f"/c/{CONTEST_ID}/leaderboard").data
    assert b"Enter results" not in participant_page
    assert b"/resolve" not in participant_page


def test_editor_has_progressive_1_to_30_question_controls():
    client = app_client()
    route_user, auth_user = authenticated()
    with route_user, auth_user:
        page = client.get("/contests/new").data
    assert page.count(b'name="question"') == 30
    assert b"data-add-question" in page and page.count(b"data-remove-question") == 30
    assert b"Without JavaScript, leave unused question fields blank." in page
    script = (ROOT / "thxou" / "static" / "app.js").read_text(encoding="utf-8")
    assert "visibleRows().length === 1" in script
    assert "visibleRows().length >= 30" in script


def test_active_templates_have_no_stale_phone_auth_wording():
    templates = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (ROOT / "thxou" / "templates").glob("*.html")
    )
    for stale in ("sign in with phone", "one-time code", "send code", "phone otp"):
        assert stale not in templates


def test_forward_migration_protects_results_and_uses_database_actor():
    sql = (ROOT / "supabase" / "migrations" / "0002_event_ready.sql").read_text(encoding="utf-8").lower()
    assert "auth.uid()" in sql
    assert "c.creator_id=auth.uid()" in sql
    assert "exists(select 1 from ballots" in sql
    assert "'correct_answer',case when" in sql
    assert "c.published_at is null" in sql
    assert "revoke execute" in sql and "from public, anon" in sql
    assert "insert into question_results" in sql
    assert "seed" not in sql.replace("-- forward-only event-readiness update for databases where 0001_initial.sql\n-- is already applied. this migration changes projections and authorization\n-- checks only; it creates no records.\n", "")
