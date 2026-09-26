from fastapi.testclient import TestClient
from travel_agent.main import create_app


def test_health_has_only_liveness():
    with TestClient(create_app(), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/api/v1/auth/xhs/sessions").status_code == 404


def test_dns_rebinding_and_cross_origin_blocked():
    with TestClient(create_app(), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/health", headers={"Host": "evil.example"}).status_code == 403
        assert client.get("/health", headers={"Origin": "https://evil.example"}).status_code == 403
        assert "access-control-allow-origin" not in client.get("/health").headers


def test_built_local_page_and_assets():
    from travel_agent.settings import PROJECT_ROOT
    with TestClient(create_app(), base_url="http://127.0.0.1:8765") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "TravelAgent · 本机研究" in response.text
        for asset in (PROJECT_ROOT / "apps/web/dist/assets").iterdir():
            assert client.get("/assets/" + asset.name).status_code == 200
