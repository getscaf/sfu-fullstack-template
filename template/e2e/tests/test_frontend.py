"""Smoke-test the pages provided by a fresh scaffold."""

import json

import pytest
from bs4 import BeautifulSoup


@pytest.mark.parametrize("route", ["/", "/about"])
def test_starter_page(public_client, nextjs, route):
    path = route if nextjs or route == "/" else route + "/"
    response = public_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = BeautifulSoup(response.text, "html.parser")
    if nextjs:
        assert html.select_one("#__next") is not None
        data = html.select_one("script#__NEXT_DATA__")
        assert data is not None
        assert json.loads(data.get_text())["page"] == route
    else:
        assert html.select_one("nav a[href='/about/']") is not None
        assert "Welcome to your brand-new" in html.get_text(" ", strip=True)
