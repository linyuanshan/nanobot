from pathlib import Path

from fastapi.testclient import TestClient

from hatchery.app import HatcherySettings, create_app


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(HatcherySettings(database_path=tmp_path / "hatchery.db"))
    return TestClient(app)


def test_gui_route_serves_acceptance_console(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/gui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    assert "海参育苗一期验收台" in html
    assert "运维控制台" in html
    assert "Bridge 工具台" in html
    assert 'lang="zh-CN"' in html
    assert "apiBase" in html
    assert "bridgeBase" in html


def test_root_redirects_to_gui(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/gui"
