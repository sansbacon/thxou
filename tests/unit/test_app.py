from thxou import create_app


def test_health_without_supabase_is_degraded():
    client = create_app({"TESTING": True, "SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": ""}).test_client()
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json == {"status": "degraded"}


def test_home_renders():
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/").status_code == 200
