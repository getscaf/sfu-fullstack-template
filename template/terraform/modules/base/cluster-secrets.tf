locals {
  cluster_secret_names = toset([
    "kubeconfig",
{% if copier__operating_system == "talos" %}
    "talosconfig_yaml",
    "talos_controlplane_yaml",
{% endif %}
  ])
}

resource "aws_secretsmanager_secret" "cluster" {
  for_each = local.cluster_secret_names

  # A scheduled deletion must not reserve the name for a later deployment.
  name_prefix             = "{{ copier__project_slug }}_${var.environment}_${each.key}_"
  recovery_window_in_days = var.disposable ? 0 : 30
  tags                    = local.common_tags
}

output "cluster_secret_arns" {
  description = "Secret identifiers for cluster bootstrap; values are written after provisioning"
  value       = { for name, secret in aws_secretsmanager_secret.cluster : name => secret.arn }
}
