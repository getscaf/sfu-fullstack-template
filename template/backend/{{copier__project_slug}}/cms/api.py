import logging
from urllib.parse import urlparse, urlsplit

from django.core.signing import BadSignature
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from wagtail.api.v2.router import WagtailAPIRouter
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.contrib.redirects.middleware import get_redirect
from wagtail.contrib.redirects.models import Redirect

from .models import ContentPage

logger = logging.getLogger(__name__)


class PublishedPagesAPIViewSet(PagesAPIViewSet):
    def get_queryset(self):
        # Use concrete page URL hooks in list responses too, retaining native
        # live/site/ancestor permission filtering and routing.
        return super().get_queryset().specific()


class PagePreviewAPIViewSet(PagesAPIViewSet):
    # Register additional page models here when extending the starter.
    preview_models = (ContentPage,)

    def listing_view(self, request):
        self.action = "detail_view"
        return self.detail_view(request, 0)

    def get_object(self):
        if hasattr(self, "_cached_object"):
            return self._cached_object
        content_type = self.request.GET.get("content_type", "")
        token = self.request.GET.get("token", "")
        model = next(
            (
                model
                for model in self.preview_models
                if model._meta.label_lower == content_type
            ),
            None,
        )
        if model is None or not token or len(token) > 255:
            raise Http404
        try:
            model.get_preview_signer().unsign(token, max_age=600)
            page = model.get_page_from_preview_token(token)
        except (BadSignature, ValueError):
            raise Http404 from None
        if page is None:
            raise Http404
        if page.pk is None:
            # The native API requires an ID when reversing its detail URLs.
            page.pk = 0
            page.id = 0
        self._cached_object = page
        return self._cached_object

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


@never_cache
@require_GET
def resolve_redirect(request):
    """Match an encoded public path using Wagtail's redirect normalization."""
    path = request.GET.get("path", "")
    if (
        not path
        or len(path) > 2048
        or any(ord(char) < 32 for char in path)
        or "\\" in path
    ):
        raise Http404
    try:
        url = urlsplit(path)
    except ValueError:
        raise Http404 from None
    if (
        url.scheme
        or url.netloc
        or url.fragment
        or not (url.path == "/content" or url.path.startswith("/content/"))
    ):
        raise Http404

    # The frontend supplies an already encoded URL. Do not put it in request.path:
    # Django's get_full_path() would encode percent signs for a second time.
    normalized = Redirect.normalise_path(path, decode_unicode=False)
    redirect = get_redirect(request, normalized)
    if redirect is None:
        without_query = urlparse(normalized).path
        if without_query != normalized:
            redirect = get_redirect(request, without_query)
    if redirect is None or not redirect.link:
        return JsonResponse({}, status=404)
    destination = redirect.link
    try:
        target = urlsplit(destination)
    except ValueError:
        target = None
    if (
        target is None
        or (target.scheme and target.scheme.lower() not in ("http", "https"))
        or (not target.scheme and not destination.startswith("/"))
        or destination.startswith("//")
        or (target.scheme and not target.netloc)
        or target.username
        or target.password
        or "\\" in destination
        or any(ord(char) < 32 for char in destination)
    ):
        logger.warning(
            "Ignoring unsupported CMS redirect target (redirect_id=%s)",
            redirect.pk,
        )
        return JsonResponse({}, status=404)
    return JsonResponse(
        {
            "destination": destination,
            "status_code": 301 if redirect.is_permanent else 302,
        }
    )


api_router = WagtailAPIRouter("cmsapi")
api_router.register_endpoint("pages", PublishedPagesAPIViewSet)
api_router.register_endpoint("page_preview", PagePreviewAPIViewSet)
