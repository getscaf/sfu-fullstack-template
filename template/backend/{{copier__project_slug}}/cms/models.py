from django.conf import settings
from django.db import models
from django.utils.safestring import mark_safe
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page
{% if copier__create_nextjs_frontend %}
from wagtail.api import APIField
from wagtail_headless_preview.models import HeadlessMixin

from .serializers import HeroImageField, RichTextHTMLField
{% endif %}
from .rendering import render_body


class CMSPage({% if copier__create_nextjs_frontend %}HeadlessMixin, {% endif %}Page):
    """Shared URL policy for all public CMS page models."""

    class Meta:
        abstract = True

    def get_url_parts(self, request=None):
        parts = super().get_url_parts(request=request)
        if parts is None or parts[2] is None:
            return parts
        site_id, _, path = parts
        return site_id, settings.CMS_PUBLIC_BASE_URL, path


class ContentPage(CMSPage):
    """A starter page, usable as both a CMS home and a nested content page."""

    intro = models.TextField(blank=True)
    body = RichTextField(
        blank=True,
        features=["h2", "h3", "bold", "italic", "ol", "ul", "link", "document-link", "image"],
    )
    hero_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    content_panels = Page.content_panels + [
        FieldPanel("intro"),
        FieldPanel("body"),
        FieldPanel("hero_image"),
    ]
    parent_page_types = ["wagtailcore.Page", "cms.ContentPage"]
    subpage_types = ["cms.ContentPage"]
    template = "cms/content_page.html"
{% if copier__create_nextjs_frontend %}
    api_fields = [
        APIField("intro"),
        APIField("body", serializer=RichTextHTMLField()),
        APIField("hero_image", serializer=HeroImageField()),
    ]
{% endif %}

    @property
    def display_body(self):
        # render_body expands references and sanitizes HTML with nh3 before marking it safe.
        return mark_safe(render_body(self.body))  # nosec B308, B703

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["content_children"] = self.get_children().live().public().specific()
        return context
