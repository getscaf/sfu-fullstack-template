variable "account_id" {
  description = "The AWS account ID"
  type        = string
  default     = "{{ copier__aws_account_id }}"
}

variable "aws_region" {
  type        = string
  description = "AWS Region"
  default     = "{{ copier__aws_region }}"
}

variable "app_name" {
  description = "Application Name"
  type        = string
  default     = "{{ copier__project_dash }}"
}

variable "environment" {
  description = "Environment Name"
  type        = string
  default     = "sandbox"
}

variable "cluster_name" {
  description = "Name of cluster"
  type        = string
  default     = "{{ copier__project_dash }}-sandbox"
}

variable "domain_name" {
  type    = string
  default = "{{ copier__domain_name }}"
}

variable "api_domain_name" {
  type    = string
  default = "api.{{ copier__domain_name }}"
}

variable "cluster_domain_name" {
  type    = string
  default = "k8s.{{ copier__domain_name }}"
}
{% if copier__create_nextjs_frontend %}
variable "nextjs_domain_name" {
  type    = string
  default = "nextjs.{{ copier__domain_name }}"
}
{% endif %}

variable "argocd_domain_name" {
  type    = string
  default = "argocd.{{ copier__domain_name }}"
}


variable "prometheus_domain_name" {
  type    = string
  default = "prometheus.{{ copier__domain_name }}"
}

variable "control_plane" {
  description = "Info for control plane that will be created"
  type = object({
    instance_type      = optional(string, "t3a.medium")
    ami_id             = optional(string, null)
    num_instances      = optional(number, 3)
    config_patch_files = optional(list(string), [])
    tags               = optional(map(string), {})
    disk_size          = optional(number, 100)
  })

  validation {
    condition     = var.control_plane.ami_id != null ? (length(var.control_plane.ami_id) > 4 && substr(var.control_plane.ami_id, 0, 4) == "ami-") : true
    error_message = "The ami_id value must be a valid AMI id, starting with \"ami-\"."
  }

  default = {}
}

variable "cluster_vpc_cidr" {
  description = "The IPv4 CIDR block for the VPC."
  type        = string
  default     = "172.16.0.0/16"
}

{% if copier__operating_system == "talos" %}
variable "config_patch_files" {
  description = "Path to talos config path files that applies to all nodes"
  type        = list(string)
  default     = []
}
{%- endif %}

variable "repo_name" {
  type    = string
  default = "{{ copier__repo_name }}"
}

variable "repo_url" {
  type    = string
  default = "{{ copier__repo_url }}"
}

{% if copier__create_nextjs_frontend %}
variable "frontend_ecr_repo" {
  description = "The Frontend ECR repository name"
  type        = string
  default     = "{{ copier__project_dash }}-sandbox-frontend"
}
{% endif %}

variable "backend_ecr_repo" {
  description = "The backend ECR repository name"
  type        = string
  default     = "{{ copier__project_dash }}-sandbox-backend"
}

variable "admin_allowed_ips" {
  description = "A list of CIDR blocks that are allowed to access the kubernetes api"
  type        = string
  default     = "0.0.0.0/0"
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "existing_hosted_zone" {
  description = "Name of existing hosted zone to use instead of creating a new one"
  type        = string
  default     = "{{ copier__existing_hosted_zone }}"
}

variable "disposable" {
  description = "Permit destructive teardown of data in a sandbox provisioned for demo or E2E use"
  type        = bool
  default     = false
}
