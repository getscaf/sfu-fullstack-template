# Terraform

This directory contains the Terraform configurations for the Scaf project. The
configurations are organized into several directories, each serving a specific
purpose. Below is a brief overview of each directory and instructions on how to
run the Terraform configurations.

## Directory Structure

- **bootstrap**: Bootstraps the Terraform state in an S3 bucket and a DynamoDB
  table. This configuration contains the states for all environments and only
  needs to be run once.

- **github**: Sets up a GitHub OIDC provider to allow GitHub to push container
  images to ECR repositories.

- **modules**: Contains a base module that is used by all environments.

- **prod**: Contains the configuration for the production environment.

- **sandbox**: Contains the configuration for the sandbox environment.

- **staging**: Contains the configuration for the staging environment.

## Setup Instructions

### Step 1: AWS Configuration

Ensure that you have installed AWS CLI version 2, as AWS SSO support is only
available in version 2 and above. Create a new AWS profile in `~/.aws/config`.
Here's an example of the `~/.aws/config` profile:

```
[profile scaf]
sso_start_url = https://sixfeetup.awsapps.com/start
sso_region = us-east-1
sso_account_id = <replace with your AWS account id>
sso_role_name = admin
region = us-east-1
output = json
```

Note the `sso_role_name` setting above. Make sure to use a role that provides
you with the necessary permissions to deploy infrastructure on your AWS account.

The GitHub repository must already exist. Authenticate the GitHub CLI with an
account that can access it (`gh auth login`). The GitHub Terraform configuration
uses `gh api` to read its canonical name and owner/repository IDs. Its OIDC trust
policy accepts both the legacy name-only subject and the immutable subject for
that repository, retaining exact IDs rather than wildcarding them. See
[GitHub's subject format documentation](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims).

Export the `AWS_PROFILE` environment variable:

```
$ export AWS_PROFILE=scaf
```
Then, to deploy to sandbox you can run:

```
$ task deploy-sandbox
```

TODO: replace with automation between the environment creation and the argocd bootstrap:


```
{% if copier__create_nextjs_frontend %}
6. After the environment is successfully deployed, note the CloudFront distribution ID that was created, and update the `DISTRIBUTION_ID` value in the corresponding kustomization.yaml file (e.g., sandbox/kustomization.yaml or production/kustomization.yaml) to reflect the correct value.
{% endif %}

