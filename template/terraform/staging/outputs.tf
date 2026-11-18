output "talosconfig" {
  description = "The generated talosconfig"
  value       = module.cluster.talosconfig
  sensitive   = true
}

output "kubeconfig" {
  description = "The generated kubeconfig"
  value       = module.cluster.kubeconfig
  sensitive   = true
}

output "machineconfig" {
  description = "The generated machineconfig"
  value       = module.cluster.machineconfig
  sensitive   = true
}

output "cnpg-iam-role-arn" {
  description = "CloudNativePG iam role arn"
  value       = module.cluster.cnpg-iam-role-arn
  sensitive   = false
}

output "cnpg_user_access_key" {
  value = module.cluster.cnpg_user_access_key
}

output "cnpg_user_secret_key" {
  sensitive = true
  value     = module.cluster.cnpg_user_secret_key
}
{% if copier__mail_service == "Amazon SES" %}

output "amazon_ses_user_key" {
  value = module.cluster.amazon_ses_user_key
}

output "amazon_ses_user_secret_key" {
  sensitive = true
  value     = module.cluster.amazon_ses_user_key
}
{% endif %}

output "control_plane_nodes_public_ips" {
  description = "The public ip addresses of the talos control plane nodes"
  value       = module.cluster.control_plane_nodes_public_ips
}

output "control_plane_nodes_private_ips" {
  description = "The private ip addresses of the talos control plane nodes"
  value       = module.cluster.control_plane_nodes_private_ips
}

{% if copier__operating_system == "k3s" %}
output "public_deploy_key" {
  description = "SSH public key for accessing EC2 instances during k3s bootstrap and cluster management"
  value       = module.cluster.public_deploy_key
}

output "private_deploy_key" {
  description = "SSH private key for accessing EC2 instances during k3s bootstrap and cluster management"
  sensitive   = true
  value       = module.cluster.private_deploy_key
}
{% endif %}

output "cloudfront_distribution_id" {
  description = "The CloudFront distribution ID"
  value       = module.cluster.cloudfront_distribution_id
}

output "cloudfront_domain_name" {
  description = "The CloudFront distribution domain name"
  value       = module.cluster.cloudfront_domain_name
}
