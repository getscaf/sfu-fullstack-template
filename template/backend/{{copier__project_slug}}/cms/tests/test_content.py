import importlib
import tempfile
from io import BytesIO

from PIL import Image as PillowImage
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.test.utils import isolate_apps
from django.urls import clear_url_caches
from wagtail.documents import get_document_model
from wagtail.images import get_image_model
from wagtail.models import PAGE_MODEL_CLASSES, Collection, CollectionViewRestriction, Page, Site
{% if copier__create_nextjs_frontend %}
from unittest.mock import patch
from wagtail.contrib.redirects.models import Redirect
from wagtail.models import PageViewRestriction
{% endif %}

from ..models import CMSPage, ContentPage
from ..rendering import render_body


@override_settings(
    CMS_PUBLIC_BASE_URL="https://site.example.test",
    CMS_BACKEND_BASE_URL="https://api.example.test",
)
class ContentTests(TestCase):
    def setUp(self):
        self.home = Site.objects.get(is_default_site=True).root_page.specific
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        storage = override_settings(MEDIA_ROOT=media.name)
        storage.enable()
        self.addCleanup(storage.disable)

    def page(self, slug, parent=None, publish=True):
        page = (parent or self.home).add_child(
            instance=ContentPage(title=slug, slug=slug, body="<p>Published content</p>", live=False)
        )
        revision = page.save_revision()
        if publish:
            revision.publish()
        page.refresh_from_db()
        return page

    def test_published_content_is_searchable(self):
        page = self.page("searchregression")
        results = ContentPage.objects.live().search("searchregression")
        self.assertEqual([result.pk for result in results], [page.pk])

    def test_initialize_cms_indexes_seed_pages_and_is_idempotent(self):
        example = self.home.get_children().specific().get(slug="example")
        call_command("initialize_cms", verbosity=0)
        example.refresh_from_db()
        self.assertIsNotNone(example.latest_revision_id)
        self.assertIsNotNone(example.live_revision_id)
        self.assertIsNotNone(example.first_published_at)
        self.assertEqual(list(ContentPage.objects.live().search("Example")), [example])
        revision_id, published_at = example.latest_revision_id, example.first_published_at
        example.title = "User edit"
        example.save_revision().publish()
        edited_revision = example.latest_revision_id
        call_command("initialize_cms", verbosity=0)
        example.refresh_from_db()
        self.assertEqual(example.title, "User edit")
        self.assertEqual(example.latest_revision_id, edited_revision)
        self.assertNotEqual(example.latest_revision_id, revision_id)
        self.assertEqual(example.first_published_at, published_at)
        example.delete()
        call_command("initialize_cms", verbosity=0)
        self.assertFalse(ContentPage.objects.filter(slug="example").exists())

    def test_seeded_tree_and_canonical_origins(self):
        self.assertEqual(Page.find_problems(), ([], [], [], [], []))
        self.assertEqual(self.home.numchild, 1)
        self.assertEqual(self.home.full_url, "https://site.example.test/content{% if not copier__create_nextjs_frontend %}/{% endif %}")
        with override_settings(CMS_PUBLIC_BASE_URL="https://api.prod.example.test"):
            self.assertEqual(self.home.full_url, "https://api.prod.example.test/content{% if not copier__create_nextjs_frontend %}/{% endif %}")

    @isolate_apps()
    def test_another_cms_model_inherits_public_url_policy(self):
        class AnotherPage(CMSPage):
            class Meta:
                app_label = "cms"

        # isolate_apps restores Django's registry; Wagtail also keeps its own list.
        self.addCleanup(PAGE_MODEL_CLASSES.remove, AnotherPage)
        page = AnotherPage(title="Another", slug="another", url_path=f"{self.home.url_path}another/")
        self.assertEqual(page.full_url, "https://site.example.test/content/another{% if not copier__create_nextjs_frontend %}/{% endif %}")

    def test_hero_description_and_title_fallback(self):
        output = BytesIO()
        PillowImage.new("RGB", (20, 10), "red").save(output, format="PNG")
        image = get_image_model().objects.create(
            title="IMG_2043", description="Red sunset over the sea",
            file=SimpleUploadedFile("hero.png", output.getvalue()),
        )
        page = self.page("hero-alt")
        page.hero_image = image
        page.save_revision().publish()
        for description, expected in [("Red sunset over the sea", "Red sunset over the sea"), ("", "IMG_2043")]:
            image.description = description
            image.save()
{% if copier__create_nextjs_frontend %}
            self.assertEqual(self.detail(page).json()["hero_image"]["alt"], expected)
{% else %}
            self.assertContains(self.client.get("/content/hero-alt/"), f'alt="{expected}"')
{% endif %}

    def test_rich_text_expansion_and_sanitizing(self):
        child = self.page("linked")
        html = render_body(
            f'<p><a linktype="page" id="{child.pk}">Page</a>'
            '<a href="/documents/12/file.pdf">Document</a>'
            '<img src="/media/images/example.jpg" alt="Example" width="20" height="10" onerror="alert(1)">'
            '<a href="javascript:alert(1)">Bad link</a><script>alert(1)</script></p>'
        )
        self.assertIn('/content/linked{% if not copier__create_nextjs_frontend %}/{% endif %}"', html)
        self.assertIn('https://api.example.test/documents/12/file.pdf', html)
        self.assertIn('https://api.example.test/media/images/example.jpg', html)
        self.assertIn('alt="Example"', html)
        self.assertNotIn("onerror", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("<script", html)

    def test_documents_are_served_only_through_permission_view(self):
        collection = Collection.get_first_root_node().add_child(name="Private documents")
        CollectionViewRestriction.objects.create(collection=collection, restriction_type="login")
        document = get_document_model().objects.create(
            title="Private document", collection=collection,
            file=SimpleUploadedFile("private.txt", b"private document bytes"),
        )
        self.assertNotEqual(self.client.get(document.url).status_code, 200)
        self.client.force_login(get_user_model().objects.create_user(username="reader", password="test"))
        response = self.client.get(document.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"private document bytes")
        self.client.logout()
        public_file = default_storage.save(
            "images/public.txt", SimpleUploadedFile("public.txt", b"public media bytes")
        )
        document_paths = [
            document.file.name,
            "/" + document.file.name,
            "./" + document.file.name,
            "images/../" + document.file.name,
            document.file.name.replace("/", "//", 1),
            "images%2F..%2F" + document.file.name,
            document.file.name.replace("documents/", "DOCUMENTS/", 1),
        ]
        from config import urls
        try:
            for media_url in ["/media/", "/uploads/"]:
                with override_settings(DEBUG=True, MEDIA_URL=media_url):
                    importlib.reload(urls)
                    clear_url_caches()
                    for path in document_paths:
                        with self.subTest(media_url=media_url, path=path):
                            self.assertEqual(
                                self.client.get(media_url + path).status_code, 404
                            )
                    response = self.client.get(default_storage.url(public_file))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        b"".join(response.streaming_content), b"public media bytes"
                    )
        finally:
            importlib.reload(urls)
            clear_url_caches()

{% if copier__create_nextjs_frontend %}
    def find(self, path):
        return self.client.get("/api/cms/v2/pages/find/", {"html_path": path})

    def detail(self, page):
        return self.client.get(f"/api/cms/v2/pages/{page.pk}/")

    def preview(self, page):
        snapshot = page.create_page_preview()
        return self.client.get("/api/cms/v2/page_preview/", {
            "content_type": "cms.contentpage", "token": snapshot.token,
            "fields": "title,intro,body,hero_image,slug,html_url",
        })

    def test_nested_lookup_visibility_and_publication(self):
        branch = self.page("branch")
        other = self.page("other")
        page = self.page("same-slug", parent=branch)
        self.page("same-slug", parent=other)
        self.assertIn(f"/pages/{page.pk}/", self.find("/branch/same-slug/")["Location"])
        draft = self.page("draft", publish=False)
        self.assertEqual(self.find("/draft/").status_code, 404)
        self.assertEqual(self.detail(draft).status_code, 404)
        PageViewRestriction.objects.create(page=branch, restriction_type="login")
        self.assertEqual(self.find("/branch/same-slug/").status_code, 404)
        self.assertEqual(self.detail(page).status_code, 404)
        page = self.page("editable")
        page.body = "<p>New draft</p>"
        revision = page.save_revision()
        self.assertIn("Published content", self.detail(page).json()["body"])
        self.assertIn("New draft", self.preview(page).json()["body"])
        revision.publish()
        self.assertIn("New draft", self.detail(page).json()["body"])
        page.unpublish()
        self.assertEqual(self.detail(page).status_code, 404)

    def test_api_origins_rendition_and_native_redirect(self):
        output = BytesIO()
        PillowImage.new("RGB", (20, 10), "red").save(output, format="PNG")
        image = get_image_model().objects.create(title="A red hero", file=SimpleUploadedFile("hero.png", output.getvalue()))
        page = self.page("image")
        page.hero_image = image
        page.save_revision().publish()
        data = self.detail(page).json()
        self.assertEqual(data["meta"]["html_url"], "https://site.example.test/content/image")
        self.assertTrue(data["hero_image"]["url"].startswith("https://api.example.test/media/images/"))
        self.assertEqual(data["hero_image"]["alt"], "A red hero")
        listed = self.client.get("/api/cms/v2/pages/", {
            "child_of": self.home.pk, "limit": 100, "fields": "title,html_url",
        }).json()["items"]
        self.assertTrue(all(item["meta"]["html_url"].startswith("https://site.example.test/") for item in listed))
        self.assertRedirects(self.client.get("/content/image/"), "http://localhost:3000/content/image", fetch_redirect_response=False)

    def test_missing_hero_source_keeps_page_available(self):
        output = BytesIO()
        PillowImage.new("RGB", (21, 13), "green").save(output, format="PNG")
        image = get_image_model().objects.create(title="Missing", file=SimpleUploadedFile("missing.png", output.getvalue()))
        page = self.page("missing-hero")
        page.hero_image = image
        page.save_revision().publish()
        image.file.storage.delete(image.file.name)
        # Test transactions can reuse image IDs while rendition cache survives.
        image.get_rendition_model().cache_backend.clear()
        with self.assertLogs("{{ copier__project_slug }}.cms.serializers", level="WARNING"):
            response = self.detail(page)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["hero_image"])
        self.assertIn("Published content", response.json()["body"])
        with patch.object(get_image_model(), "get_rendition", side_effect=RuntimeError("Unexpected storage failure")):
            with self.assertRaisesRegex(RuntimeError, "Unexpected storage failure"):
                self.detail(page)

    def test_preview_reads_snapshot_once_per_request(self):
        snapshot = self.home.create_page_preview()
        with patch.object(ContentPage, "get_page_from_preview_token", wraps=ContentPage.get_page_from_preview_token) as reader:
            response = self.client.get("/api/cms/v2/page_preview/", {
                "content_type": "cms.contentpage", "token": snapshot.token,
                "fields": "title,intro,body,hero_image,slug,html_url",
            })
        self.assertEqual(response.status_code, 200)
        reader.assert_called_once_with(snapshot.token)

    def test_redirect_lookup_uses_native_site_and_query_matching(self):
        page = self.page("target")
        Redirect.add_redirect("/content/old", redirect_to="https://elsewhere.example/global")
        Redirect.add_redirect("/content/old", redirect_to=page, site=Site.objects.get(is_default_site=True))
        response = self.client.get("/api/cms/v2/redirect/", {"path": "/content/old/?b=2&a=1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"destination": "/content/target", "status_code": 301})
        self.assertIn("no-store", response["Cache-Control"])
        Redirect.add_redirect("/content/old?a=1&b=2", redirect_to="https://elsewhere.example/query", is_permanent=False)
        response = self.client.get("/api/cms/v2/redirect/", {"path": "/content/old/?b=2&a=1"})
        self.assertEqual(response.json(), {"destination": "https://elsewhere.example/query", "status_code": 302})

    def test_redirect_lookup_preserves_encoded_paths(self):
        page = self.page("encoded-target")
        for old_path, encoded in [
            ("/content/café", "/content/caf%C3%A9"),
            ("/content/çığ", "/content/%C3%A7%C4%B1%C4%9F"),
            ("/content/old%20page", "/content/old%20page"),
            ("/content/100%25", "/content/100%25"),
        ]:
            with self.subTest(path=encoded):
                Redirect.add_redirect(old_path, redirect_to=page)
                response = self.client.get("/api/cms/v2/redirect/", {"path": encoded + "?z=2&a=1"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"destination": "/content/encoded-target", "status_code": 301})
                Redirect.add_redirect(old_path + "?a=1&z=2", redirect_to="https://elsewhere.example/query", is_permanent=False)
                response = self.client.get("/api/cms/v2/redirect/", {"path": encoded + "?z=2&a=1"})
                self.assertEqual(response.json(), {"destination": "https://elsewhere.example/query", "status_code": 302})

    def test_unsupported_redirect_targets_are_ignored(self):
        for scheme in ["ftp", "ftps", "javascript"]:
            Redirect.add_redirect("/content/unsupported-" + scheme, redirect_to=scheme + "://files.example.test/private")
            with self.assertLogs("{{ copier__project_slug }}.cms.api", level="WARNING"):
                response = self.client.get("/api/cms/v2/redirect/", {"path": "/content/unsupported-" + scheme})
            self.assertEqual(response.status_code, 404)

    def test_slug_change_creates_a_headless_redirect(self):
        page = self.page("before")
        page.slug = "after"
        # Wagtail creates redirects on transaction commit, as in the editor.
        with self.captureOnCommitCallbacks(execute=True):
            page.save_revision().publish()
        response = self.client.get("/api/cms/v2/redirect/", {"path": "/content/before"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"destination": "/content/after", "status_code": 301})
        self.assertEqual(self.find("/before/").status_code, 404)

    def test_redirect_lookup_is_limited_to_content_paths(self):
        Redirect.add_redirect("/about", redirect_to="https://elsewhere.example/about")
        for path in ["/content/missing", "/about", "https://elsewhere.example/content/old", "//elsewhere.example/content/old", "/content/old\x00", "/content/old#fragment", "/content/old\\bad"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get("/api/cms/v2/redirect/", {"path": path}).status_code, 404)

    def test_unsaved_preview_and_token_failures(self):
        unsaved = ContentPage(title="Unsaved preview", slug="unsaved")
        # Match Wagtail's PreviewOnCreate tree context, without saving the page.
        unsaved.depth = self.home.depth + 1
        unsaved.path = self.home.get_last_child()._inc_path()
        unsaved.set_url_path(self.home)
        response = self.preview(unsaved)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 0)
        self.assertEqual(response.json()["title"], "Unsaved preview")
        self.assertIn("no-store", response["Cache-Control"])
        for query in [{}, {"content_type": "cms.contentpage", "token": "bad"}, {"content_type": "users.user", "token": "bad"}]:
            self.assertEqual(self.client.get("/api/cms/v2/page_preview/", query).status_code, 404)
        with patch("django.core.signing.time.time", return_value=1000):
            token = self.home.create_page_preview().token
        response = self.client.get("/api/cms/v2/page_preview/", {"content_type": "cms.contentpage", "token": token})
        self.assertEqual(response.status_code, 404)
{% else %}
    def test_native_rendering_and_preview(self):
        page = self.page("native")
        self.assertContains(self.client.get("/content/native/"), "Published content")
        page.body = "<p>Unsaved native preview</p>"
        response = page.serve_preview(self.client.request().wsgi_request, "")
        response.render()
        self.assertIn(b"Unsaved native preview", response.content)
        self.assertContains(self.client.get("/content/native/"), "Published content")
{% endif %}
