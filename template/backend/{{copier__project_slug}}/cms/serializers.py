import logging

from rest_framework import serializers
from wagtail.images.models import SourceImageIOError

from .rendering import public_media_url, render_body

logger = logging.getLogger(__name__)


class RichTextHTMLField(serializers.Field):
    def to_representation(self, value):
        return render_body(value)


class HeroImageField(serializers.Field):
    def to_representation(self, image):
        try:
            rendition = image.get_rendition("fill-1200x600")
        except SourceImageIOError:
            logger.warning(
                "CMS hero source image is unavailable (image_id=%s)", image.pk
            )
            return None
        return {
            "url": public_media_url(rendition.url),
            "width": rendition.width,
            "height": rendition.height,
            "alt": rendition.alt,
        }
