from urllib.parse import urljoin

import nh3
from django.conf import settings
from wagtail.rich_text import expand_db_html


def public_media_url(value):
    if value.startswith(("/media/", "/documents/")):
        return urljoin(settings.CMS_BACKEND_BASE_URL + "/", value)
    return value


def render_body(value):
    """Expand Wagtail references and keep the starter's display HTML safe for SSR."""

    def attribute_filter(tag, attribute, value):
        if attribute in {"href", "src"}:
            return public_media_url(value)
        return value

    return nh3.clean(
        expand_db_html(value or ""),
        tags={
            "p",
            "h2",
            "h3",
            "strong",
            "b",
            "em",
            "i",
            "ol",
            "ul",
            "li",
            "a",
            "img",
            "br",
        },
        attributes={
            "a": {"href", "title"},
            "img": {"src", "alt", "width", "height", "class"},
        },
        url_schemes={"http", "https", "mailto", "tel"},
        attribute_filter=attribute_filter,
    )
