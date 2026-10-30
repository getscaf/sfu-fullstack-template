from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from django.views import defaults as default_views
from django.views.generic import TemplateView

{%- if copier__use_wagtail %}
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls
from {{ copier__project_slug }}.cms.views import serve_public_media
{%- if copier__create_nextjs_frontend %}
from {{ copier__project_slug }}.cms.api import api_router, resolve_redirect
{%- endif %}
{%- endif %}

{%- if copier__create_nextjs_frontend %}
from django.views.decorators.csrf import csrf_exempt
from strawberry.django.views import GraphQLView

from .schema import schema

{%- endif %}

urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path(
        "about/", TemplateView.as_view(template_name="pages/about.html"), name="about"
    ),
    # Django Admin, use {% raw %}{% url 'admin:index' %}{% endraw %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("{{ copier__project_slug }}.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    # Your stuff: custom urls includes go here
]
{%- if copier__use_wagtail %}
urlpatterns += [
    path("cms/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
]
{%- if copier__create_nextjs_frontend %}
urlpatterns += [
    path("api/cms/v2/redirect/", resolve_redirect, name="cms_redirect"),
    path("api/cms/v2/", api_router.urls),
]
{%- endif %}
urlpatterns += [path("content/", include(wagtail_urls))]
urlpatterns += static(
    settings.MEDIA_URL, view=serve_public_media, document_root=settings.MEDIA_ROOT
)
{%- else %}
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
{%- endif %}
if settings.DEBUG:
    # Static file serving when using Gunicorn + Uvicorn for local web socket development
    urlpatterns += staticfiles_urlpatterns()

{%- if copier__create_nextjs_frontend %}
urlpatterns += [
    path("graphql/", csrf_exempt(GraphQLView.as_view(schema=schema))),
]
{%- endif %}

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
