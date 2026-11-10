from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import ContentPage


class Command(BaseCommand):
    help = "Complete revision, publication and search metadata for initial CMS content."

    def handle(self, *args, **options):
        # Historical migration models cannot call Wagtail's revision/index hooks.
        # Row locks prevent concurrent pod initializers from creating two revisions.
        with transaction.atomic():
            pages = (
                ContentPage.objects.select_for_update()
                .filter(live=True, latest_revision__isnull=True)
                .order_by("pk")
            )
            for page in pages:
                page.save_revision().publish()
