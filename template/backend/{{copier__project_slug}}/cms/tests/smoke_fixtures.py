"""Test-only fixtures for the opt-in HTTP smoke suite, invoked through manage.py shell."""

from io import BytesIO
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image as PillowImage
from wagtail.contrib.redirects.models import Redirect
from wagtail.images import get_image_model
from wagtail.models import PageViewRestriction, Site

from ..models import ContentPage


def run(action, page_id=None):
    if action == "setup":
        home = Site.objects.get(is_default_site=True).root_page.specific
        slug = "scaf-smoke-" + uuid4().hex[:12]
        branch = home.add_child(instance=ContentPage(title="Smoke branch", slug=slug))
        other = home.add_child(instance=ContentPage(title="Other branch", slug=slug + "-other"))
        page = branch.add_child(instance=ContentPage(
            title="HTTP smoke page", slug="aynı-çığ", body="<p>First smoke body</p>", live=False
        ))
        output = BytesIO()
        PillowImage.new("RGB", (40, 20), "blue").save(output, format="PNG")
        hero = get_image_model().objects.create(
            title="Smoke image", file=SimpleUploadedFile(slug + ".png", output.getvalue())
        )
        page.hero_image = hero
        page.save_revision()
        duplicate = other.add_child(instance=ContentPage(title="Other same leaf", slug="aynı-çığ", live=False))
        duplicate.save_revision().publish()
        space_path = f"/content/{slug}/old%20page"
        Redirect.add_redirect(space_path, redirect_to=page)
        result = {"id": page.pk, "branch": branch.pk, "other": other.pk, "image": hero.pk,
                  "path": page.get_url_parts()[2], "other_path": duplicate.get_url_parts()[2],
                  "space_path": space_path}
{% if copier__create_nextjs_frontend %}
        result["token"] = page.create_page_preview().token
{% endif %}
        return result
    page = ContentPage.objects.get(pk=page_id)
    if action == "publish":
        page.get_latest_revision().publish()
    elif action == "edit":
        page.body = "<p>Updated smoke body</p>"
        page.save_revision().publish()
    elif action == "rename":
        old_path = page.get_url_parts()[2]
        page.slug += "-renamed"
        page.save_revision().publish()
        page.refresh_from_db()
        return {"old_path": old_path, "path": page.get_url_parts()[2]}
    elif action == "unpublish":
        page.unpublish()
    elif action == "restrict":
        PageViewRestriction.objects.create(page=page, restriction_type="login")
    elif action == "delete":
        page.delete()
    return {}


def cleanup(data):
    ContentPage.objects.filter(pk__in=[data["branch"], data["other"]]).delete()
    image = get_image_model().objects.filter(pk=data["image"]).first()
    if image:
        image.delete()
