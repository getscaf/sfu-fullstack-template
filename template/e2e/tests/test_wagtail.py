"""Publish a Wagtail edit and verify it from an anonymous public request."""

import json
import os
import subprocess
from uuid import uuid4

import httpx
import pytest
from bs4 import BeautifulSoup

pytestmark = [
    pytest.mark.wagtail,
    pytest.mark.skipif(
        os.environ.get("SCAF_E2E_WAGTAIL") != "1", reason="Wagtail is disabled"
    ),
]

EDITOR_FIXTURE = """
import json
from secrets import token_urlsafe
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.urls import reverse
from wagtail.models import Site

site = Site.objects.get(is_default_site=True)
page = site.root_page.get_children().get(slug="example").specific
username = "scaf-e2e-" + uuid4().hex[:12]
password = token_urlsafe()
get_user_model().objects.create_superuser(
    username=username, email=f"{username}@example.test", password=password
)
print(json.dumps({
    "username": username,
    "password": password,
    "login": reverse("wagtailadmin_login"),
    "edit": reverse("wagtailadmin_pages:edit", args=[page.pk]),
    "public": page.get_url_parts()[2],
    "intro": page.intro,
}))
"""


def create_editor():
    context = os.environ["SCAF_E2E_CONTEXT"]
    assert context.startswith("kind-scaf-e2e-") and os.environ.get(
        "KUBECONFIG"
    ), "Wagtail publication tests require the disposable cluster from e2e-run.sh"
    result = subprocess.run(
        [
            "kubectl",
            "--context",
            context,
            "exec",
            "deployment/backend",
            "-c",
            "backend",
            "--",
            "python",
            "manage.py",
            "shell",
            "--no-imports",
            "-c",
            EDITOR_FIXTURE,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"Could not prepare the CMS editor: {result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def form_fields(response, selector):
    assert response.status_code == 200, f"Could not load {response.url.path}"
    form = BeautifulSoup(response.text, "html.parser").select_one(selector)
    assert form is not None, f"Could not find the expected form at {response.url.path}"
    data = {
        field["name"]: field.get("value", "")
        for field in form.select(
            "input[type=hidden][name]:not([disabled]), input[name=title], input[name=slug]"
        )
    }
    for field in form.select("textarea[name]:not([disabled])"):
        data[field["name"]] = field.get_text()
    assert data.get("csrfmiddlewaretoken"), "Wagtail form is missing its CSRF token"
    return data


def test_editor_publishes_updated_intro(backend_url, public_client, nextjs):
    editor = create_editor()
    path = editor["public"].rstrip("/") if nextjs else editor["public"]
    intro = f"Scaf E2E edited content {uuid4().hex}"
    before = public_client.get(path)
    assert before.status_code == 200
    assert editor["intro"] in before.text
    assert intro not in before.text

    with httpx.Client(base_url=backend_url, timeout=15, trust_env=False) as client:
        login = client.get(editor["login"])
        fields = form_fields(login, "form:has(input[name=password])")
        fields.update(username=editor["username"], password=editor["password"])
        response = client.post(editor["login"], data=fields)
        assert response.is_redirect, f"Wagtail login returned {response.status_code}"

        edit = client.get(editor["edit"])
        fields = form_fields(edit, "form:has(textarea[name=intro])")
        fields.update(intro=intro)
        fields["action-publish"] = "1"
        response = client.post(editor["edit"], data=fields)
        if not response.is_redirect:
            errors = BeautifulSoup(response.text, "html.parser").select(
                ".error-message, .errorlist"
            )
            pytest.fail(
                f"Wagtail publication returned {response.status_code}: "
                + "; ".join(error.get_text(" ", strip=True) for error in errors)
            )

    published = public_client.get(path)
    assert published.status_code == 200
    text = BeautifulSoup(published.text, "html.parser").get_text(" ", strip=True)
    assert intro in text, "The public page still shows the previous version"
