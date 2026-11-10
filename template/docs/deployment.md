# :package: How to deploy

## Infrastructure provisioning

Terraform can be used to provision AWS resources for your project deployment.
Read [terraform/README.md](/terraform/README.md) for more information and steps for provisioning resources.

Sandbox uses `sandbox.{{ copier__domain_name }}` for the public site/assets and
`api.sandbox.{{ copier__domain_name }}` for Django. Production uses
`prod.{{ copier__domain_name }}` and `api.prod.{{ copier__domain_name }}` respectively.
{% if copier__create_nextjs_frontend %}
CloudFront connects to `nextjs.sandbox.{{ copier__domain_name }}` or
`nextjs.prod.{{ copier__domain_name }}`. Keep DNS, ingress and certificate names aligned.
{% else %}
The public domain serves assets; application pages remain on the Django host.
{% endif %}

Deployment collects static files into the environment's private S3 bucket before
starting Django. Bucket names and asset domains are generated in the overlays;
provide the normal sealed S3 credentials through the existing bootstrap workflow.
Both the backend and static-collection init container use those credentials.
{% if copier__use_wagtail %}
See [Wagtail CMS](wagtail.md) for CMS URLs, document permissions and content extension points.
{% endif %}

## Application deployment

Use ArgoCD and Kubernetes to automate the deployment of your application to your infrastructure. ArgoCD monitors changes within your repository, promptly applying the relevant Kubernetes manifests. Read [bootstrap-cluster/README.md](/bootstrap-cluster/README.md) for more details.
