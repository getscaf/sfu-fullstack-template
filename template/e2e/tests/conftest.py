"""Connection details supplied by the Tilt E2E resource."""

import os

import httpx
import pytest


@pytest.fixture(scope="session")
def backend_url():
    return f"http://127.0.0.1:{os.environ['SCAF_E2E_BACKEND_PORT']}"


@pytest.fixture(scope="session")
def nextjs():
    return os.environ["SCAF_E2E_NEXTJS"] == "1"


@pytest.fixture(scope="session")
def public_url(backend_url, nextjs):
    if nextjs:
        return f"http://127.0.0.1:{os.environ['SCAF_E2E_FRONTEND_PORT']}"
    return backend_url


@pytest.fixture
def public_client(public_url):
    with httpx.Client(base_url=public_url, timeout=15, trust_env=False) as client:
        yield client
