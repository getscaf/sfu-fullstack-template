"""
Frontend availability tests.
Verifies that the frontend is accessible and renders correctly.
"""

import pytest
import httpx


pytestmark = pytest.mark.asyncio


@pytest.mark.frontend
async def test_frontend_http_200(frontend_url):
    """Verify frontend responds with HTTP 200 OK."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(frontend_url)
        
        assert response.status_code == 200, \
            f"Frontend returned {response.status_code}, expected 200. " \
            f"Response: {response.text[:200]}"


@pytest.mark.frontend
async def test_frontend_contains_html(frontend_url):
    """Verify frontend response contains valid HTML markup."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(frontend_url)
        content = response.text.lower()
        
        # Check for HTML markers
        has_html = "<html" in content or "<!doctype" in content
        assert has_html, \
            "Frontend response does not contain HTML markup. " \
            f"First 500 chars: {response.text[:500]}"


@pytest.mark.frontend
async def test_frontend_contains_head_tag(frontend_url):
    """Verify frontend response contains <head> tag."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(frontend_url)
        content = response.text.lower()
        
        assert "<head" in content, \
            "Frontend response missing <head> tag. " \
            f"First 500 chars: {response.text[:500]}"


@pytest.mark.frontend
async def test_frontend_contains_root_element(frontend_url):
    """Verify frontend renders application root element."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(frontend_url)
        content = response.text
        
        # Check for common root element IDs (Next.js, React, Vue)
        # Next.js uses <div id="__next"> or <html>
        # React typically uses <div id="root">
        # Vue typically uses <div id="app">
        has_root = any([
            'id="__next"' in content,
            'id="root"' in content,
            'id="app"' in content,
            '<main' in content.lower(),  # Semantic HTML
        ])
        assert has_root, \
            "Frontend response missing application root element. " \
            f"Expected id='__next', id='root', id='app', or <main>. " \
            f"First 1000 chars: {response.text[:1000]}"


@pytest.mark.frontend
async def test_frontend_content_type(frontend_url):
    """Verify frontend returns HTML content type."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(frontend_url)
        
        content_type = response.headers.get('content-type', '').lower()
        assert 'text/html' in content_type, \
            f"Expected text/html content type, got: {content_type}"


@pytest.mark.frontend
async def test_frontend_no_error_status(frontend_url):
    """Verify frontend does not return error status codes."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(frontend_url)
        
        # Check it's not a 4xx or 5xx error
        assert response.status_code < 400, \
            f"Frontend returned error status: {response.status_code}. " \
            f"Response: {response.text[:200]}"


@pytest.mark.frontend
async def test_frontend_response_not_empty(frontend_url):
    """Verify frontend returns non-empty response."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(frontend_url)
        
        assert len(response.text) > 0, \
            "Frontend returned empty response"
        
        assert len(response.text) > 100, \
            f"Frontend response too small ({len(response.text)} bytes). " \
            f"This may indicate an error page."
