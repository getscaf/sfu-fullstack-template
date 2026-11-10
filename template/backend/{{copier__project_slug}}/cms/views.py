import posixpath

from django.http import Http404
from django.views.static import serve


def serve_public_media(request, path, **kwargs):
    # Check the same normalized path that Django's development file server uses.
    path = posixpath.normpath(path).lstrip("/")
    if path.split("/", 1)[0].casefold() == "documents":
        raise Http404
    return serve(request, path, **kwargs)
