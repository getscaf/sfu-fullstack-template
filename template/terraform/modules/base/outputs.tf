output "cnpg-iam-role-arn" {
  description = "CloudNativePG iam role arn"
  value       = aws_iam_role.ec2_role.arn
  sensitive   = false
}

output "cnpg_user_access_key" {
  value = aws_iam_access_key.cnpg_user_key.id
}

output "cnpg_user_secret_key" {
  sensitive = true
  value     = aws_iam_access_key.cnpg_user_key.secret
}
{% if copier__mail_service == "Amazon SES" %}

output "amazon_ses_user_key" {
  value = aws_iam_access_key.amazon_ses_user_key.id
}

output "amazon_ses_user_secret_key" {
  sensitive = true
  value     = aws_iam_access_key.amazon_ses_user_key.secret
}
{% endif %}

output "control_plane_nodes_public_ips" {
  description = "The public ip addresses of the control plane nodes."
  value       = join(",", module.control_plane_nodes.*.public_ip)
}

output "control_plane_nodes_private_ips" {
  description = "The private ip addresses of the control plane nodes."
  value       = join(",", module.control_plane_nodes.*.private_ip)
}

{% if copier__operating_system == "k3s" %}
output "private_deploy_key" {
  value     = tls_private_key.deploy_key.private_key_openssh
  sensitive = true
}

output "public_deploy_key" {
  value     = tls_private_key.deploy_key.public_key_openssh
}
{% endif %}

output "cloudfront_distribution_id" {
  description = "The CloudFront distribution ID"
  value       = aws_cloudfront_distribution.cloudfront.id
}

output "cloudfront_domain_name" {
  description = "The CloudFront distribution domain name"
  value       = aws_cloudfront_distribution.cloudfront.domain_name
}
{% if copier__create_nextjs_frontend %}
output "frontend_ecr_repo" {
  description = "The Frontend ECR repository"
  value       = module.ecr_frontend.repository_url
}
{% endif %}
output "backend_ecr_repo" {
  description = "The Backend ECR repository"
  value       = module.ecr_backend.repository_url
}
