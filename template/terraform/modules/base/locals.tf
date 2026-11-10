locals {
  public_asset_prefixes = [
    "static/",
    {% if copier__use_wagtail %}
    "media/original_images/",
    "media/images/",
    "media/avatar_images/",
    {% else %}
    "media/",
    {% endif %}
  ]

  common_tags = merge(var.tags, {
    automation          = "terraform"
    "automation.config" = join(".", [var.app_name, var.environment])
    application         = var.app_name
    environment         = var.environment
  })
}
