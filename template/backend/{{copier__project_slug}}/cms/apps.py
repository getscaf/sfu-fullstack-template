from django.apps import AppConfig


class CmsConfig(AppConfig):
    name = "{{ copier__project_slug }}.cms"
    verbose_name = "Content"
    default_auto_field = "django.db.models.BigAutoField"
