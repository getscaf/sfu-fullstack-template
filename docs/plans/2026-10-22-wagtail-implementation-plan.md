# Scaf Wagtail implementation plan

Status: Implemented; completed checks and pending environment verification recorded below. Updated: 2026-10-23.

The user authorized implementation and explicitly requested no commits. Work-unit boundaries below describe review/commit grouping for the user; the agent must not create commits.

Feature: [#197 Add Wagtail as an option](https://github.com/getscaf/sfu-fullstack-template/issues/197). Design subtask: [#199](https://github.com/getscaf/sfu-fullstack-template/issues/199).

Add working Wagtail support to the existing Scaf template. Keep the current application architecture and development/deployment workflows, adapting them wherever Wagtail needs additional configuration to work. When Next.js is selected, the generated application must include a usable headless integration. An editor can create and publish another starter page without manually connecting the CMS, adding frontend routes, or rebuilding the application.

## Scope and change boundary

Preserving the architecture means retaining Django, the existing user model, Strawberry/Apollo, the Next.js Pages Router, and the existing Docker, Tilt, Kubernetes, storage, and deployment approach. It does not mean freezing every setting or manifest. Necessary Wagtail dependencies, middleware, URLs, migrations, rendering, environment values, static/media handling, and deployment adjustments belong in this work.

Use the following rule for infrastructure changes: establish the blocker from the generated configuration or a failing check, identify the missing capability in the existing mechanism, and make the smallest correction that makes Wagtail work. The storage, asset routing, origin/TLS and runtime corrections specified below are required work. Verify all four combinations for shared corrections. Do not leave the CMS broken merely because the necessary fix touches deployment files; do not redesign infrastructure without that connection to the feature.

| Included | Conditional on a demonstrated need | Outside the initial scope |
| --- | --- | --- |
| Independent Wagtail option, CMS admin and starter content | Existing ingress adjustments beyond the explicit origin/asset configuration below | New dynamic-page routing at the apex or a different CDN topology |
| Native rendering, headless rendering and package-based preview | A local media mount or syncback adjustment if current handling loses CMS uploads | Replacing the deployment pipeline or frontend production process |
| Modern storage settings, static collection, consistent environment origins/TLS, asset DNS/routing and private document delivery within existing S3/CloudFront | A narrowly scoped correction to an existing test command | A new media service, mandatory signed URLs for all media or new cloud services |
| Python 3.13 alignment, generation/functional/regression tests and generated documentation | Additional compatibility fixes demonstrated by the supported modes | Repository-wide dependency modernization, new business models or site designs |

## Supported configurations

Keep `copier__create_nextjs_frontend` unchanged. Add `copier__use_wagtail`, a boolean defaulting to `false`, independent of Next.js. Existing answer files that omit it retain their current behavior. Celery, Sentry, repository provider and cluster OS stay independent.

| Next.js | Wagtail | Expected result |
| --- | --- | --- |
| Enabled | Disabled | Current Django and Next.js application |
| Disabled | Disabled | Current Django application |
| Enabled | Enabled | Django/Wagtail CMS consumed by the existing Next.js frontend |
| Disabled | Enabled | Wagtail pages rendered by the existing Django backend |

Normal Scaf project inputs, deployment credentials and administrator creation still apply. Generate CMS integration settings from those inputs; users must not add a new shared preview secret, run a seeding command or wire frontend routes after scaffolding. This plan targets newly generated projects. Retrofitting Wagtail into an already populated generated application, renaming hosts in an existing deployment or migrating existing DNS/Terraform state are separate scenarios.

## Compatibility and dependencies

Use Python 3.13, matching the existing backend image. When Wagtail is enabled, constrain `wagtail>=7.4,<7.5` and `django>=6.0,<6.1`; when Next.js is also enabled, use `wagtail-headless-preview==0.9.0`. This selects a Wagtail LTS release with declared Django 6.0 support and the preview package's declared Wagtail 7 support. Verify the exact resolved combination with dependency checks, migrations and preview tests; successful installation alone does not establish integration compatibility. See the [Wagtail compatibility table](https://docs.wagtail.org/en/stable/releases/upgrading.html#compatible-django-python-versions) and [preview package metadata](https://pypi.org/project/wagtail-headless-preview/). Leave the existing Django requirement unchanged when Wagtail is disabled.

Set generated GitHub CI's Python version and Bitbucket's Python image to 3.13 in a shared compatibility commit. Django 6.0 requires Python 3.12 or later, and the current GitHub 3.10 / Bitbucket 3.12 configuration does not test the backend's actual runtime. Python 3.10 can resolve an older compatible Django release, so the mismatch alone does not prove the current CI is broken. Record resolved versions on Python 3.13 for both Wagtail-enabled and disabled cases. See [Django's Python support](https://docs.djangoproject.com/en/6.0/faq/install/#what-python-version-can-i-use-with-django).

| Dependency | Use |
| --- | --- |
| `wagtail>=7.4,<7.5` and `django>=6.0,<6.1` | Required constraints only when Wagtail is enabled, with its supported native API dependencies. |
| `wagtail-headless-preview==0.9.0` | Required only when both Wagtail and Next.js are enabled. Do not move to Wagtail 8 as part of this work without revisiting preview compatibility. |
| `nh3` | Enabled for the starter’s shared server-side renderer. Rich text is expanded by Wagtail, then restricted to the editor’s supported HTML before Next.js inserts it into SSR output; native rendering uses the same output. Tests cover scripts, event handlers and unsafe link schemes. |

Use native Wagtail REST API v2. Do not add Grapple, strawberry-wagtail, another CMS service or a frontend CMS SDK. Preserve the current Strawberry schema and Apollo client. Native Wagtail API dependencies such as Django REST framework are part of the Wagtail integration, not a separate API framework replacement.

## Routes and generated settings

Use `/content/` for CMS pages. Keep `/`, `/about`, accounts, Django admin and GraphQL behavior. In Next.js-only mode and Django-only mode, no CMS routes or links should remain.

| Route | Behavior |
| --- | --- |
| Backend `/cms/` | Wagtail admin alongside the configurable Django admin URL. |
| `/content/` and `/content/<nested/path>/` | CMS home and descendants, rendered by Next.js when enabled and Django otherwise. |
| Backend `/api/cms/v2/pages/` | Native published-content API when headless integration is enabled. |
| Backend `/api/cms/v2/pages/find/` | Native page lookup using `html_path`. |
| Backend `/api/cms/v2/page_preview/` | Thin preview API integration following the preview package's documented recipe. |
| Frontend `/cms-preview` | SSR preview using the same content component as published pages. |
| Backend `/documents/` | Wagtail's document serving views and permission checks. |

Use the environment names already established by the sandbox/prod Terraform modules. In this table, `<domain>` means the existing `copier__domain_name` input; every value is an origin without a path or trailing slash. Explicitly separate the Next.js upstream hosts by environment:

| Environment | Public site / asset origin | Backend origin | Next.js upstream origin, only when Next.js is enabled |
| --- | --- | --- | --- |
| Sandbox | `https://sandbox.<domain>` | `https://api.sandbox.<domain>` | `https://nextjs.sandbox.<domain>` |
| Production | `https://prod.<domain>` | `https://api.prod.<domain>` | `https://nextjs.prod.<domain>` |

With Next.js, CMS pages render at the public site origin through the existing CloudFront distribution, whose application origin is that environment's Next.js upstream. Without Next.js, pages render at the backend origin under `/content/`, for example `https://api.prod.<domain>/content/`; the public domain remains an asset alias with the existing S3 default origin. Do not move standalone dynamic pages to CloudFront. Local defaults are `http://localhost:3000` for Next.js and `http://localhost:8000` for the backend; local media stays on the backend.

Generate the following values in the existing environment/configmap mechanism:

| Setting | Purpose |
| --- | --- |
| `CMS_INTERNAL_BASE_URL` | Next.js server-to-Django requests, normally `http://backend:8000`; server-only. Reuse the existing backend address convention. |
| `CMS_PUBLIC_BASE_URL` | Public site column when Next.js is enabled; backend column otherwise. Locally use port 3000 or 8000 according to the same condition. |
| `CMS_BACKEND_BASE_URL` | Backend column in both CMS modes, for document links, relative media URLs and admin access; locally port 8000. |
| `WAGTAILADMIN_BASE_URL` | Same origin as `CMS_BACKEND_BASE_URL`, without `/cms/`; not another user-supplied input. |

Generate these settings only when Wagtail is enabled, from existing inputs and the explicit origin table. Set the internal server URL only where the headless integration needs it. The Next.js upstream column is the CloudFront-to-frontend address, not the canonical CMS public URL. Keep page links on the page-rendering origin and document/media links on the correct backend or existing storage origin. Never serialize `backend:8000` into browser-visible URLs. Do not rewrite unrelated external links.

Mount `wagtail.urls` at backend `/content/` in both Wagtail modes so `reverse("wagtail_serve")` remains available. In headless mode the package's serve mixin redirects those backend requests to Next.js; without Next.js normal Wagtail rendering handles them. Register the CMS API/admin/document routes before the page-serving include.

Implement the URL override on an abstract `CMSPage` shared by `ContentPage` and future CMS models. Preserve the site ID and reversed `/content/...` path from `super()`, replace only the root origin with `CMS_PUBLIC_BASE_URL`, and preserve the non-routable return case. Keep `.specific()` in the published API: the override requires a concrete instance. Document that new CMS models must inherit this base. This keeps migration data independent of deployment hosts while providing canonical URLs through Wagtail's normal URL hooks. Test `full_url`, API `meta.html_url`, rich text links and View Live in both local and deployed-origin configurations. Set `WAGTAIL_APPEND_SLASH=False` only in headless mode to match Next.js canonical URLs; native projects retain trailing slashes.

Internal HTTP requests currently depend on `backend` being allowed by Django and on the generated SSL-redirect/proxy configuration. Verify this contract rather than loosening global security settings or adding new public CORS allowances. Report redirects and upstream failures clearly instead of turning every failure into a page 404.

## CMS foundation and initial content

Add a conditional `{{ copier__project_slug }}.cms` app. Its starter `ContentPage` has inherited title/slug fields, `intro`, a `RichTextField` body and an optional hero image. Allow nested starter pages. Project-specific page types remain normal development work, with a documented model/API/renderer extension point.

Add the Wagtail apps, middleware, URL includes and required settings using the selected version's integration guide. Reuse the existing user model and `createsuperuser` workflow. Do not create default administrator credentials.

Create the CMS home, a published example child and the default Wagtail Site association in a one-time data migration. Follow Wagtail's [starter homepage migration](https://github.com/wagtail/wagtail/blob/v7.4/wagtail/project_template/home/migrations/0002_create_homepage.py), adapted to the selected version, historical models and page tree. Keep environment-specific origins out of migration code.

Ship one `0001_initial.py` with `bases=("wagtailcore.page",)` and no preview-package import or Jinja-dependent base classes. `HeadlessMixin` changes runtime serving/preview behavior and must not become a permanent migration dependency in Wagtail-only projects. Run actual migrations with and without the preview package installed; `makemigrations --check` alone does not cover optional-package import failures or base-class differences.

The data migration uses historical models rather than treebeard instance methods. Set `path`, `depth`, `url_path` and `numchild` consistently for the root/home/example structure, including the home's child count. Assert tree integrity after migrating a fresh database using `Page.find_problems()` and explicit parent/child counts; do not repair the tree with `fixtree` to make a broken migration pass.

The existing `manage.py migrate` startup step provisions the initial content. Remove the previous plan's `bootstrap_cms` command, repeated placeholder detection and custom bootstrap locks. Re-running migrations must preserve edits and must not recreate a deleted example child.

## Published API and rendering contract

Use native `PagesAPIViewSet`, `APIField`, rich text serializers and image renditions. Keep Wagtail's site and visibility handling; do not implement a parallel routing or permission engine. Configure one default Wagtail Site and test anonymous access, including restricted ancestors.

Resolve full paths using native `find`, not global slug matching. For example, frontend `/content/a/b/` maps to a site-relative `html_path=/a/b/`. The endpoint returns a 302 redirect to the detail endpoint or a 404, as documented in the [native API guide](https://docs.wagtail.org/en/stable/advanced_topics/api/v2/usage.html#finding-pages-by-html-path). The server client must validate the returned API path and follow it on the configured backend origin. It must not follow arbitrary hosts. Use `child_of=<id>` for public child navigation.

Extend the native detail representation with explicit starter fields; no new resolver endpoint or JSON wrapper is needed. The frontend contract is:

| Field | Type and meaning |
| --- | --- |
| `id` | Number for a persisted page. The preview adapter handles the package's placeholder ID for unsaved pages. |
| `meta.type` | String identifying the supported page model. |
| `meta.slug` | String; not sufficient on its own to identify a nested page. |
| `meta.html_url` | Canonical public page URL; may be absent/null for an unsaved preview. |
| `title` | Plain text. |
| `intro` | Plain text, possibly empty. |
| `body` | Wagtail-expanded display HTML, not its internal rich text storage representation. |
| `hero_image` | Null or a selected rendition with `url`, `width`, `height` and `alt`. |

Select those fields explicitly in the page serializer/API fields and consume the native `items` representation for navigation. Use the URL hook specified above for View Live and rich text page links. Resolve `/documents/...` links against the public backend, never the CDN's physical document path. Resolve relative rendition/embedded-image URLs against the backend while preserving absolute storage URLs. Test an unsaved preview separately: use the package recipe's placeholder ID where required and allow absent/null `meta.html_url` without a serializer error.

Use a restricted starter rich text feature set and Wagtail's supported conversion/expansion path. If an additional sanitizer is introduced, verify that it preserves the intended embedded image and link attributes while removing unsafe markup. Do not add raw HTML blocks or a generic StreamField component framework to this starter.

Implement `pages/content/[[...slug]].tsx` with `getServerSideProps`. The CMS client is server-only, uses bounded timeouts, validates expected responses and never forwards browser credentials to the published-content API. Unknown/unpublished/restricted pages produce 404; malformed paths produce a controlled response; upstream outages remain errors.

After a missing-page response, consult a CMS-only redirect resolver using Wagtail's native `get_redirect` helper and normalization. Pass the encoded public path directly; putting it in a synthetic `request.path` would double-encode percent signs. Preserve the selected single site's redirect precedence, query-string normalization/fallback and 301/302 status codes, including automatic slug-change redirects. Return 404 when no supported match exists and propagate upstream failures. Support relative and HTTP/HTTPS destinations; warn and ignore unsupported targets such as FTP/FTPS. Do not fetch redirect destinations on the server. Keep navigation origin/path checks; skip and log the page ID for an incompatible child URL without dropping valid siblings, while invalid API response shapes and outages remain errors. Use rendition `alt` in both renderers to retain Wagtail's description/title fallback; return a null hero on `SourceImageIOError` only.

Render fresh CMS data per request. Keep existing cache behavior for unrelated routes; do not introduce ISR, webhooks or a new invalidation service. Public edits and unpublishing must be reflected on the next CMS request. Render Wagtail image renditions with `<img>` and explicit dimensions/alt text, avoiding a new Next.js image-host configuration requirement. Production public image URLs use the existing CDN with the access rules below; document bytes are delivered by the backend after Wagtail's permission checks.

Provide the equivalent Django template under the CMS app for the mode without Next.js. Add a CMS navigation link in the existing layouts only when enabled. New pages using the starter type require no new route files. New page types require ordinary model/serializer/renderer development.

## Preview through the standard package

Use [wagtail-headless-preview](https://github.com/torchbox/wagtail-headless-preview) for snapshot creation, serialization and token handling. Apply its headless mixin only in headless mode; use native Wagtail preview otherwise. Set `WAGTAIL_HEADLESS_PREVIEW["CLIENT_URLS"]["default"]` to the frontend's `/cms-preview` URL, `SERVE_BASE_URL` to `CMS_PUBLIC_BASE_URL`, and `REDIRECT_ON_PREVIEW=True` for the selected Wagtail version. Align the preview URL's trailing slash with the existing Next.js configuration.

The package documents an API integration recipe; it does not supply the complete Scaf frontend integration automatically. Add only that thin API adapter and the Next.js preview page using the existing display serializer/component. A saved draft, a first unpublished page and unsaved form edits must preview without changing public content.

The [selected package's signer](https://github.com/torchbox/wagtail-headless-preview/blob/0f1f3aa7a139d017944e981ad23edc3068906c52/src/wagtail_headless_preview/models.py) validates signatures without a maximum age, and its garbage collection runs only when another preview is created. Neither provides bounded token lifetime. The adapter must validate with the page model's `get_preview_signer().unsign(token, max_age=600)` before retrieving the snapshot, preserve the `content_type` filter and restrict it to supported CMS page models. Return 404 for malformed, invalid, expired or missing previews, catching `BadSignature`/`SignatureExpired` rather than returning 500. Ten minutes is Scaf's initial preview lifetime; test expiry independently of snapshot cleanup. No custom cache snapshot service, editor-bound grant system, manually shared secret or new Redis/Celery dependency is required.

Keep preview separate from the published API, avoid caching its responses, do not expose preview tokens in public navigation or content JSON, and configure only the iframe behavior needed by the existing Wagtail admin. Test an actual editor preview when browser access is available. Advanced live-preview integrations and user-bar extensions are outside this initial scope.

## Necessary deployment adaptation

Reuse the current containers, S3 bucket, CloudFront distribution, manifests and deployment commands. The following corrections are part of the implementation, with shared changes covered in all four option combinations.

### Shared storage and runtime corrections

Replace production's removed `DEFAULT_FILE_STORAGE` / `STATICFILES_STORAGE` settings with `STORAGES["default"]` and `STORAGES["staticfiles"]`, pointing to the existing `S3MediaStorage` and `S3StaticStorage` classes. Preserve `media` / `static` locations and media's `file_overwrite=False`. Django removed the legacy settings in 5.1, so this is required for the selected versions, rather than an optional modernization. See [Django's removal notes](https://docs.djangoproject.com/en/5.1/releases/5.1/#features-removed-in-5-1).

Configure the actual bucket before enabling S3-backed collectstatic. Remove the unused base configmap's `CHANGEME_S3_BUCKET_NAME` placeholder and generate `DJANGO_AWS_STORAGE_BUCKET_NAME` explicitly in both deployment overlays, matching Terraform's `${var.app_name}-${var.environment}-static-storage` naming. Production inherits sandbox, so it must override the sandbox value rather than inherit it. Use the following generated values; `production` is the Django environment label, whereas Terraform's bucket suffix is `prod`:

| Deployment overlay | `DJANGO_AWS_STORAGE_BUCKET_NAME` | Asset host matching Terraform's CloudFront alias |
| --- | --- | --- |
| Sandbox | `{{ copier__project_dash }}-sandbox-static-storage` | `sandbox.{{ copier__domain_name }}` |
| Production | `{{ copier__project_dash }}-prod-static-storage` | `prod.{{ copier__domain_name }}` |

The asset hosts follow `terraform/{sandbox,prod}/cluster.tf`. Correct production's currently bare `AWS_S3_CUSTOM_DOMAIN` to match its existing Terraform alias, `prod.{{ copier__domain_name }}`. Keep this asset-origin correction separate from where dynamic pages/admin render. No user-supplied bucket name or additional Terraform-output copying step is required for generated defaults.

Make the deployed credential contract explicit: in production settings map `AWS_S3_ACCESS_KEY_ID = env("AWS_S3_ACCESS_KEY_ID", default=None)` and `AWS_S3_SECRET_ACCESS_KEY = env("AWS_S3_SECRET_ACCESS_KEY", default=None)`. Reuse the existing bootstrap-generated `secrets-config` entries and inject them into both the backend and collectstatic init container. Align `backend/env.example` with those names, replacing the unused `DJANGO_AWS_ACCESS_KEY_ID` / `DJANGO_AWS_SECRET_ACCESS_KEY` examples. Do not expose secrets in configmaps, generated literals, test output or diagnostics.

This explicit mapping documents and tests the deployment contract; its absence is not by itself a confirmed credential-discovery failure. The current [django-storages authentication logic](https://django-storages.readthedocs.io/en/stable/backends/amazon-S3.html#authentication-settings) already reads `AWS_S3_ACCESS_KEY_ID` and `AWS_S3_SECRET_ACCESS_KEY` directly from the environment before falling back to Boto3. The generated secret-based path must work without EC2 metadata access. Retain the SDK's existing role/standard-environment credential discovery when no S3-specific keys are supplied; do not make long-lived keys a new requirement for role-based deployments.

Derive production `STATIC_URL` and `MEDIA_URL` from the same configured asset origin used by the storage backends, with `/static/` and `/media/` prefixes. Do not leave the current unsigned bucket-domain URLs alongside private S3 objects. Keep local URLs relative. The environment-specific aliases above and unconditional asset DNS records below determine the deployed asset origin in every mode.

Set `AWS_DEFAULT_ACL=None` so uploads do not request `public-read`. Keep the bucket private and manage public reads through its existing CloudFront OAC. Declare S3 Block Public Access explicitly for the application asset bucket, with all four protections enabled, rather than relying on account/bucket creation defaults. Do not loosen those protections to make uploads succeed. Public ACLs can make `PutObject` fail under Block Public Access; omitting an ACL is supported by the existing storage backend. See [AWS access controls](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html) and [django-storages settings](https://django-storages.readthedocs.io/en/stable/backends/amazon-S3.html).

Add a `backend-collectstatic` init container to the sandbox deployment overlay, inherited by production, running `python manage.py collectstatic --noinput` against the configured S3 static storage. Use the backend image, configmap, secrets and `DATABASE_URL` mapping, including the final environment-specific bucket and S3 credentials specified above. Preserve the existing database-ready and migration init containers and their order. Ensure the added container uses the resolved backend image in both overlays. Local development continues to use Django's existing static-file serving; collecting into an isolated init container's local filesystem must not become a local asset dependency. A successful generation check must not leave collectstatic targeting a placeholder or the other environment's bucket.

Align generated GitHub and Bitbucket CI with Python 3.13 as specified above. Keep storage activation, correct bucket/credential wiring, ACLs, asset DNS/routing, origin/TLS corrections, static collection and CI alignment together in the shared compatibility commit, so collectstatic is not introduced before its prerequisites. Verify the complete configuration with Wagtail disabled as well as enabled.

### Shared environment origins and TLS

Apply the origin table consistently across Terraform and the built Kubernetes overlays. These corrections also apply to Next.js projects with Wagtail disabled and belong to work unit 0, not a later CMS-only deployment change:

1. In `template/terraform/{sandbox,prod}/cluster.tf`, explicitly pass `nextjs_domain_name="nextjs.sandbox.{{ copier__domain_name }}"` or `"nextjs.prod.{{ copier__domain_name }}"` respectively, only when Next.js is selected. The existing Route53 record and CloudFront origin consume this variable. Do not let either generated environment use the shared `nextjs.<domain>` default.
2. Update `template/k8s/sandbox/ingress-route.yaml` to match the sandbox Next.js host, and add a conditional `frontend-ingress` patch in `template/k8s/prod/kustomization.yaml` for the production host and production issuer annotation. Production must override the inherited sandbox frontend host. Omit frontend patches when Next.js is absent.
3. In `template/k8s/sandbox/certificate.yaml` and the production certificate patch, cover `api.<environment>.<domain>` and `k8s.<environment>.<domain>`, adding `nextjs.<environment>.<domain>` only when Next.js is enabled. Production's replacement of the whole `dnsNames` list must retain its Next.js name. Keep the ingress TLS secret wired to that certificate. The existing CloudFront viewer certificate covers the public site alias separately; the cluster certificate covers the upstream/backend hosts.
4. Correct production's backend and k8s ingress matches to `api.prod.<domain>` and `k8s.prod.<domain>`, matching the already-generated Terraform DNS records. Retain the existing services, ports, ingress mechanism and CloudFront topology.
5. Generate each overlay's `DJANGO_CSRF_TRUSTED_ORIGINS` from its backend origin, plus its public site and Next.js upstream origins when Next.js is enabled. Generate the existing Next.js `CORS_ALLOWED_ORIGINS` as exactly that environment's public site and upstream origins, preserving the existing credential behavior. Override production explicitly instead of inheriting sandbox values. With Next.js disabled, omit its CORS configuration and frontend trust entries. Keep `backend` allowed for internal SSR without broadening global host/CORS policies.

Generate the CMS origin values from the same table in the Wagtail work unit. Preserve the current HTTPS origin connection; [CloudFront requires a certificate matching its origin domain or forwarded Host](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/http-502-bad-gateway.html). Do not bypass certificate verification or downgrade to HTTP to hide a host mismatch. Validate the full DNS → CloudFront origin → ingress → certificate → application settings chain independently for sandbox and production, including their separation.

### Public assets and document access

When Wagtail is enabled, narrow the existing CloudFront service principal's S3 `GetObject` grant to these object prefixes, retaining the distribution's `AWS:SourceArn` condition:

| S3 object prefix | Public use |
| --- | --- |
| `static/*` | Django/Wagtail admin and application CSS/JS/assets. |
| `media/original_images/*` | Wagtail original images. |
| `media/images/*` | Wagtail image renditions. |
| `media/avatar_images/*` | Wagtail user-profile images; required for the existing editor profile UI. |

These image prefixes come from [Wagtail's upload-path implementations](https://github.com/wagtail/wagtail/blob/v7.4/wagtail/images/models.py). With Next.js, add ordered CloudFront behaviors for exactly `/static/*`, `/media/original_images/*` , `/media/images/*` and `/media/avatar_images/*`, targeting the existing S3 origin; keep the current Next.js default and API behaviors. Without Next.js, keep the existing S3 default origin: the narrowed S3 grant still prevents CloudFront from reading documents. Do not add a blanket public `/media/*` behavior in a Wagtail-enabled project.

Do not impose Wagtail's image-directory allowlist on Wagtail-disabled projects. Keep their general-media capability: the existing broader OAC grant remains, and Next.js deployments route `/static/*` and `/media/*` to the same S3 origin. This distinction prevents the shared storage correction from making arbitrary application uploads unreadable.

Create A/AAAA records for the existing CloudFront `var.domain_name` alias in every option combination, including when Next.js and Wagtail are both disabled. CloudFront and its certificate already exist in every mode; these records complete the existing asset delivery path. Keep the Next.js origin CNAME conditional on Next.js alone. Without Next.js, the distribution continues to serve assets from S3 while dynamic pages/admin stay on the backend host. Use the environment-specific asset hosts above in configmaps. Do not require users to copy `cloudfront_domain_name` into configuration or add a separate asset-domain input. Every combination must have a resolvable asset origin; none should fall back to unsigned S3 URLs for private objects.

Set `WAGTAILDOCS_SERVE_METHOD="serve_view"` whenever Wagtail is enabled. Keep physical `media/documents/*` objects private and outside the CloudFront grant. The backend uses its existing authenticated S3 access to stream documents after Wagtail's collection permission checks; do not add a bucket-wide Deny that also blocks this backend access. Public and restricted document links both use `/documents/...`, never a physical S3/CDN URL. `serve_view` alone does not prevent bypass through a public file URL; [Wagtail requires direct access to be blocked too](https://docs.wagtail.org/en/v7.4/advanced_topics/documents/storing_and_serving.html#security-considerations).

Apply the same boundary locally: when Wagtail is enabled, the current DEBUG media-serving helper must not expose `/media/documents/...`. Allow local image paths and reject physical document requests before any generic media route. Test a restricted document through its authorized view, an anonymous view request, and direct local/S3/CloudFront paths. Expected behavior is authorized download, denied anonymous access and denied physical-path access, while public documents remain downloadable through Wagtail.

### Remaining environment checks

Verify image upload and rendition creation, then replace/rebuild the local backend pod through the normal development flow and check media together with Tilt syncback. Add a local mount/sync adjustment only if the existing setup loses uploads or has an ownership problem; a new PVC is not a predetermined requirement.

Verify generated internal/public origins, allowed hosts, proxy behavior and preview framing under the existing ingress. Correct the missing configuration while retaining the existing backend host for standalone Wagtail. Preserve current application startup commands. A blanket signed-media policy, new dynamic apex routing and a frontend Docker production-mode redesign remain outside this work.

## File scope and implementation order

The filenames below are the intended implementation locations. Required deployment corrections are explicit work units; only the final row depends on additional environment findings. Implementation was authorized after review; do not run the generated Git initialization/commit hook in this working session.

| Work unit | Files | Completion condition |
| --- | --- | --- |
| 0. Shared compatibility commit | `template/backend/config/settings/production.py`, `template/backend/env.example`, existing `utils/cloud_storage.py`, `template/k8s/base/app.configmap.yaml`, `template/k8s/{sandbox,prod}/kustomization.yaml`, `template/k8s/sandbox/{ingress-route.yaml,certificate.yaml}`, `template/terraform/{sandbox,prod}/cluster.tf`, `template/terraform/modules/base/{s3.tf,cloudfront.tf,route53.tf}`, `template/.github/workflows/main.yaml`, `template/bitbucket-pipelines.yml`, existing deployment documentation | Modern S3 storage, matching buckets/credentials, private ACLs, public-access blocking, static collection, asset DNS, distinct environment origins with valid ingress/TLS/trust settings, and Python 3.13 CI work with Wagtail off; preserve general media paths. |
| 1. Compatibility and option | `copier.yml`, `template/backend/requirements/base.in`, generation test inputs | Independent default-off option; tested package/runtime combination; no silent unrelated downgrade or upgrade. |
| 2. CMS foundation | New `template/backend/{{copier__project_slug}}/cms/{apps.py,models.py,migrations/0001_initial.py,migrations/0002_create_initial_content.py,templates/cms/content_page.html}`; `template/backend/config/settings/{base.py,local.py,production.py}` and `config/urls.py` | Normal migrations provision usable content; admin and native rendering work; users/auth remain intact. |
| 3. Native API and frontend | New CMS `api.py` and `serializers.py`; new frontend `lib/cms.ts`, `types/cms.ts`, `components/cms/ContentPage.tsx`, `pages/content/[[...slug]].tsx`; existing `components/NavBar.tsx` and `template/backend/{{copier__project_slug}}/templates/base.html` | Published nested pages render through the existing Next.js application; paths, links, media and failure statuses follow the contract. |
| 4. Preview | CMS model mixin/API adapter, new frontend `pages/cms-preview.tsx` | Standard package previews unsaved content using the same renderer; public content remains unchanged. |
| Required Wagtail deployment integration | `template/terraform/modules/base/{s3.tf,cloudfront.tf}`, `template/k8s/{base/app.configmap.yaml,sandbox/kustomization.yaml,prod/kustomization.yaml}`, backend `config/urls.py` and settings | Conditional image-only OAC access and asset behaviors; documents served only through Wagtail; generated public/internal origins using the shared asset DNS setup. |
| 5. Cleanup and tests | `template/tasks.py`; new root `tests/test_template_generation.py` and `tests/test_wagtail_smoke.py`; new backend `cms/tests/` and frontend `__tests__/cms/`; `.github/workflows/test-template.yaml` | All four generated file sets and functional modes are covered; inactive integrations leave no broken imports/routes. |
| 6. Documentation | New `template/docs/wagtail.md`; `template/mkdocs.yml`, `template/docs/{development,deployment}.md`, `template/terraform/README.md`, `template/README.md` and `.github/README.md` | Generated instructions identify URLs, normal deployment configuration, document access rules and extension points for the selected options. |
| Conditional environment fixes | Existing local `template/k8s/` manifests, `template/Tiltfile` and `template/Makefile` | A specific persistence, ownership or test-command blocker is reproduced, corrected minimally and regression-tested without changing the deployment model. |

Keep cleanup changes focused. Move import-time frontend operations under the normal setup entry point and expose a `cleanup_generated_files()` function containing the option-specific filesystem operations. The normal Copier hooks still perform normal setup. Generation tests can exercise cleanup without executing kind, npm, dependency compilation or Git initialization. Do not introduce a public `SCAF_SKIP_SETUP` configuration option just for tests.

Put shared storage/bucket/credential/ACL/DNS/origin/TLS/static/CI corrections in their own commit, with Wagtail-disabled regression checks. Then add the Wagtail option/foundation, its conditional deployment rules, native API/rendering and headless integration/preview in reviewable commits. If separate PRs help review, split along those boundaries. Do not close #197 after foundation alone. Completion requires the agreed working headless behavior and deployment compatibility; a general infrastructure improvement project is not a prerequisite.

## Verification and commands

### Lightweight generation tests

Use standard-library `unittest` plus the Copier dependency already installed by root CI. Snapshot `copier.yml` and `template/` from the working tree into a temporary source directory without `.git`, then generate all four configurations with `defaults=True` and `skip_tasks=True`. This includes uncommitted changes and avoids Copier creating temporary Git commits from a dirty checkout. Load the rendered `tasks.py` without invoking its setup entry point and call its actual cleanup function inside the generated directory.

Assert the generated apps, dependencies, files, imports, URLs and links for each case. Without Wagtail, there must be no active CMS integration. Without Next.js, remove the frontend and current user GraphQL integration while retaining the native CMS when selected. Check that the CMS migration never imports the preview package. Render representative Celery/Sentry and Bitbucket/Talos cases to catch conditional coupling without multiplying every runtime dimension.

Task skipping also skips `scripts/update-node-version.sh`, so `__NODE_LTS_VERSION__` remains in its known target files. Permit that hook placeholder in lightweight generation checks; do not run generated Docker/frontend build checks on unresolved versions. Full trusted generation must execute the Node hook and assert the placeholder is gone.

For all four modes, inspect the rendered production settings, sandbox/prod manifests and Terraform for modern storage aliases, omitted public upload ACLs, public-access blocking, collectstatic initialization, Python 3.13 CI and the selected OAC prefixes. Build the sandbox and prod overlays with the existing Kustomize tooling, then assert that each final configmap's bucket equals the matching Terraform bucket name, the production bucket does not inherit sandbox's value, and no deployed bucket placeholder remains. Check both the backend and collectstatic container's configmap/secret injection, and that each asset host matches its Terraform alias. Assert unconditional A/AAAA records separately from the Next.js-only origin CNAME, and verify that Wagtail-disabled output retains general-media access. These checks require no live cloud resources.

For both Next.js combinations, including Wagtail disabled, compare each environment's Terraform `nextjs_domain_name` / CNAME / CloudFront origin with the built frontend ingress host and certificate SANs. Compare backend DNS with its ingress and certificate, and the public alias with the CloudFront viewer certificate. Assert that production does not retain sandbox frontend/backend hosts, that the two environments use distinct Next.js origin names, and that their CSRF/CORS values match the table. With Next.js disabled, assert that no frontend origin record, ingress, patch target or certificate SAN is generated. With Wagtail enabled, check `CMS_PUBLIC_BASE_URL` according to the Next.js flag and verify both backend/admin origins; otherwise no active CMS settings should remain. These checks must compare the generated layers, not just search each source file for the same literal.

Proposed root command after the test file is implemented:

```bash
python -m unittest discover -s tests -p 'test_template_generation.py'
```

Also exercise full trusted generation hooks through the existing integration workflow, using local checked-out source rather than a remote ref. The old `sixfeetup/scaf-fullstack-template` URL redirects to this same repository; the reason to prefer local source is to test the exact checkout, not to fix a different-repository error. Run frontend-specific workflow steps only when Next.js exists.

### Generated application checks

Use the current lint, backend and frontend test mechanisms. Backend tests cover fresh migrations with and without the preview dependency, seeded Site/tree integrity, preservation of edits after subsequent migrations, nested duplicate leaf slugs, draft/live/unpublish behavior, ancestor restrictions, canonical URLs, document permissions, images and preview failures. Exercise View Live, document/admin links and preview URLs using local, sandbox and production origin settings in both CMS modes. Include unsaved-page serialization, a valid-but-expired token, a bad signature and a mismatched content type. Frontend tests cover the native API contract, find redirects, renderer/navigation, preview and upstream error handling. Existing GraphQL tests must continue to pass.

Use storage-client stubs to verify that the shared S3 configuration uploads without a public ACL and uses the correct bucket and static/media locations. For both storage aliases, supply only dummy `AWS_S3_ACCESS_KEY_ID` / `AWS_S3_SECRET_ACCESS_KEY` environment values, remove standard AWS keys/profile configuration, and disable metadata access; assert that the S3 client receives the supplied credentials without printing them or making a network request. Separately stub and verify SDK credential discovery when S3-specific keys are absent, so explicit mapping does not require static keys for role-based deployments. Test restricted document access through Wagtail separately from direct DEBUG media access; checking only the protected view would miss the bypass. Do not make unit/generation tests depend on real AWS credentials or provision another storage service for tests.

Commands below run from a generated project after its normal environment setup:

Import production storage settings only in an isolated subprocess with dummy application/cloud settings, never by reloading them inside the test session. Preserve interpreter/runtime environment such as Nix library paths and PYTHONPATH, while removing ambient AWS, Django, Mailgun and Sentry settings before applying dummy overrides. A parent-settings equality assertion adds no isolation proof across processes and is omitted. Root CI additionally generates and runs this test for Mailgun, Amazon SES and Other SMTP. Keep `collectstatic` in the existing init container. Native Wagtail cleanup removes the unused headless `api.py` and `serializers.py` modules.

```bash
make check-lint-and-formatting
make backend-test
```

For configurations with Next.js:

```bash
make check-lint-and-test-frontend
```

Inside the configured backend environment, from `backend/`:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
```

The existing `CI=true make backend-test` path contains `cd scafman`; correct that project-slug assumption if it blocks these checks. Run checks on Python 3.13 in the generated providers' existing workflows; broader CI modernization remains outside scope.

### Integrated acceptance

`tests/test_wagtail_smoke.py` is an opt-in integration suite requiring a generated project already running under the existing local/CI Tilt/kind setup and reachable backend/frontend URLs. It does not start clusters or install dependencies when imported. Without `SCAF_RUN_WAGTAIL_SMOKE=1`, skip these tests so generic unit discovery cannot contact services. When opted in, missing configuration or unreachable services is a failure, not a silent skip.

Provide `SCAF_SMOKE_PROJECT_DIR` to locate generated answers/Kubernetes configuration, `SCAF_SMOKE_BACKEND_URL`, and, only for Next.js mode, `SCAF_SMOKE_FRONTEND_URL`. Use the selected project's existing namespace/context for `kubectl exec` into its backend, calling a test-only `cms/tests/smoke_fixtures.py` helper to create/clean fixtures and obtain preview URLs. This avoids a public fixture endpoint, new bootstrap command or database credentials in the HTTP client. Run from the template repository after the generated project's normal `tilt ci`/development startup and port forwarding:

```bash
SCAF_RUN_WAGTAIL_SMOKE=1 \
SCAF_SMOKE_PROJECT_DIR=/tmp/scaf-wagtail-next \
SCAF_SMOKE_BACKEND_URL=http://localhost:8000 \
SCAF_SMOKE_FRONTEND_URL=http://localhost:3000 \
python -m unittest discover -s tests -p 'test_wagtail_smoke.py'
```

For Wagtail-only, point at that generated project and omit the frontend URL; assert native `/content/...` rendering instead. The fixture lifecycle creates a starter page, saves a draft, publishes it and fetches its rendered URL; headless mode also retrieves the draft through the preview endpoint. Cover standalone native preview through backend editor tests and the browser check below, without requiring the headless package or API. Verify that an unpublished page is absent publicly, published edits appear on the next request, and unpublishing returns 404. Add a nested page with a duplicate leaf slug in another branch and check a real image/rendition URL. This must exercise actual backend/frontend interaction rather than a mocked CMS response only.

Also check the editor UI: create and preview a first unpublished page, preview unsaved edits, publish, follow View Live and upload an image. Repeat native rendering/preview without Next.js. Use available browser tooling; do not introduce a large new E2E framework solely for this ticket.

In the established sandbox/production environment, verify that collectstatic finishes successfully against that environment's bucket and the backend reaches readiness. Verify admin CSS/JS, image originals/renditions and public document downloads after deployment. For a restricted document, verify an authenticated download, rejected anonymous view access, and rejection of anonymous direct S3 and CloudFront object URLs. Confirm backend-authenticated S3 reads still work and collectstatic/uploads succeed with public-access blocking enabled and the generated secret-based credentials. Exercise the generated asset DNS in all four modes, including when both options are disabled, without adding a manual configuration step.

Where the established deployment environment is available, check DNS resolution and TLS for the environment's backend and conditional Next.js upstream, then request a published CMS page and editor preview through its public entry point. Confirm sandbox reaches sandbox and production reaches production. Without Wagtail, use an existing frontend route to check the same CloudFront-to-Next.js path. Without Next.js, verify native content at the backend origin and assets at the separate public alias. Configuration assertions alone do not establish a working live DNS/TLS connection.

| Validation | Execution and reporting |
| --- | --- |
| Generation checks, unit/API tests, lint/typecheck, manifest inspection | Run in the agent/CI environment when dependencies are available and record actual commands/results. |
| Full generation, `tilt ci`, integrated HTTP smoke, browser preview | Run using existing local/CI tools when Docker/kind/browser access exists; otherwise identify the exact pending check. |
| Deployment compatibility | Validate rendered production settings/manifests and exercise the established deployment environment when access is available. Do not create another cloud stack or require a new paid sandbox as part of this feature. |

A missing environment is not a passed check. Record outstanding production verification explicitly. Required static/media or routing fixes cannot be deferred while claiming that Wagtail works in the existing deployment.

## Completion criteria

- Wagtail is independent, defaults off and supports all four option combinations.
- The existing architecture/workflows remain recognizable and usable; necessary CMS compatibility changes are included and explained.
- Wagtail-disabled application behavior and existing authentication/GraphQL routes remain compatible.
- Shared storage/bucket/credential/ACL/DNS/origin/TLS/static/CI corrections are isolated in their own commit and checked in all four modes; generic media access is retained when Wagtail is off.
- Both deployed overlays select the matching Terraform bucket and supply the same credential contract to backend/collectstatic; static collection completes and the backend reaches readiness.
- Sandbox/prod CMS origins are explicit; Next.js upstreams are distinct, DNS/ingress/certificate names agree, and production does not inherit sandbox trust/origin values. These corrections also work with Wagtail disabled.
- Normal migrations create valid starter content/tree state without a new user setup step or preview-package dependency in migration code.
- Next.js consumes CMS content automatically, and newly published starter pages need no new route or rebuild.
- Native Django rendering works at the existing backend origin when Next.js is absent.
- Standard package-based headless preview and native preview work without leaking drafts into public content; the headless adapter enforces the ten-minute token lifetime and controlled failures.
- Admin assets, page/document links and images work through the existing deployment/storage mechanisms; asset DNS works in every mode without copying a Terraform output into a configmap.
- Restricted documents cannot be downloaded anonymously through local media, S3 or CloudFront paths; authorized backend delivery works.
- Generated documentation and focused tests cover the promised user journey.

## Reassessment of Claude review

| Review point | Revised decision |
| --- | --- |
| Scope is too large; split PRs | Accept smaller work units and remove optional infrastructure redesign. Keep ready-to-use headless integration in #197 because it is an explicitly clarified requirement. |
| Prefer `wagtail-headless-preview` | Accept. Replace the custom grant/cache system with the maintained package and a thin Scaf API/frontend adapter. |
| Prefer native `find` and `child_of` | Accept. Remove the custom path resolver; handle the native redirect and site-relative path correctly. |
| Prefer a data migration | Accept. Tree creation stays in the historical data migration, with no repeated tree bootstrap or custom advisory lock. A later review adds a narrow `initialize_cms` finalization step after migration for live starter pages without revisions; native Wagtail publication completes timestamps/indexing, and normal row locks prevent duplicate finalization. |
| Standalone CMS on the backend host | Accept. This preserves the domain topology and does not block necessary asset/configuration fixes. |
| Production storage/static defects | Require modern `STORAGES`, matching overlay bucket names, tested credential wiring, private upload ACLs, public-access blocking, asset DNS and collectstatic initialization in one shared compatibility commit. Verify all four modes and preserve general media when Wagtail is off. |
| Bucket placeholder and credential discovery | The bucket placeholder is a confirmed generated-deployment blocker once storage/collectstatic are activated. Explicitly map the injected S3 keys and test without metadata access, but correct the factual claim: django-storages already reads those environment names itself. Preserve SDK discovery when they are absent. |
| CMS origins and the shared Next.js host | Accept an explicit sandbox/prod origin table. Separate `nextjs.sandbox.<domain>` and `nextjs.prod.<domain>` through Terraform, ingress, certificate SANs and trust settings in work unit 0, including Wagtail-disabled checks. A broken existing frontend origin cannot be excluded from a working headless integration. Existing deployed-host migrations remain out of scope. |
| Dependency and Python selection | Choose Wagtail 7.4 LTS / Django 6.0 / preview 0.9.0 on the existing Python 3.13 runtime, conditional on the CMS options. Align both generated CI providers to 3.13; Python 3.10 does not by itself prove a broken Django install because the resolver can select older compatible releases. |
| Migration mixin and tree details | Keep preview imports out of the common migration, migrate both modes and assert tree integrity without automatic repair. |
| Concrete URL and preview behavior | Mount backend `/content/` in both modes, specify `get_url_parts()` and package client/serve URLs, and require signer validation with `max_age=600`. Cleanup frequency is not a token lifetime guarantee. |
| Narrow OAC policy and CDN paths | Accept `static/*`, `media/original_images/*`, `media/images/*` and the verified Wagtail profile prefix `media/avatar_images/*` for Wagtail projects. Preserve general-media capability when Wagtail is disabled. Create the existing distribution's asset DNS records in every mode, retaining backend rendering without Next.js and removing the manual hostname-copying step. |
| Document privacy | Require `serve_view` plus private physical objects and denied direct local/CDN/S3 access; a one-line serving setting alone is insufficient. Keep backend IAM reads working. |
| Document URL, image rendering, internal SSR and sanitizer details | Accept explicit origin handling, rendition-based `<img>` rendering and SSR contract tests. Additional sanitization is conditional. Signed URLs reduce cache reuse when they change, but do not make caching inherently impossible; blanket signed media is not required here. |
| Specify JSON, file scope, commands and test isolation | Accept the contract and concrete file/check lists above. Use Copier task skipping plus the actual cleanup function rather than a new user-facing setup flag. |
| Different repository URL in CI | Correct the factual claim: both URLs identify the same repository. Still prefer generation from the checked-out source. |
| Separate automated and environment-dependent checks | Specify the opt-in smoke command, service/configuration requirements and hook-placeholder handling. Report actual execution rather than assuming agents cannot use browsers, Docker or kind. |

Review this revision for missing adaptations that Wagtail actually requires, unnecessary custom mechanisms, option compatibility, dependency constraints, URL/media correctness and whether the checks prove a usable headless starter. Architecture preservation must not become a reason to ship an installed-but-nonfunctional CMS.

## Implementation findings and local verification (2026-10-23)

- Fix local settings to supply a string `SECRET_KEY` and a parsed `ALLOWED_HOSTS` list; the existing tuple/string values break signing or host validation used by the integration.
- Native API field selection uses flat names (`fields=title,intro,body,hero_image,slug,html_url`). `find` returns a redirect; follow only its validated page-detail path on the configured internal backend.
- Configure `WAGTAILAPI_BASE_URL` to the public backend origin. Resolve concrete models in list responses so `get_url_parts()` also controls their public URLs. Set `WAGTAILAPI_LIMIT_MAX=100` to match the starter navigation limit; a real HTTP check caught the default limit of 20.
- Wagtail 7.4 stores profile images in `avatar_images/`, so the CMS public-prefix allowlist includes this fourth directory. Physical documents remain excluded.
- The existing prod overlay listed the inherited SealedSecret twice. Removing the duplicate resource entry was necessary for `kubectl kustomize` to build production; its existing prod secret patch remains.
- Normal Docker requirement compilation exposed a shared constraint conflict: base resolved `python-dateutil==3.0.0`, while boto3 requires `<3`. This silently selected unsupported old storage/email packages. Add `python-dateutil<3` to the base inputs and require `django-storages[boto3]>=1.14.6`; keep the existing compiler workflow. The resulting supported resolution includes boto3/botocore 1.43.118, django-storages 1.14.6 and Anymail 15.1.
- Current unconstrained frontend dependencies resolved TypeScript 7 / ESLint 10, which failed the existing tooling. Limit these to TypeScript 6 / ESLint 9, verified with the current frontend checks. The current Strawberry test client also needs `assert_no_errors=False` for the existing expected-error test.
- Verified Python 3.13.8 with Django 6.0.9, Wagtail 7.4.4 and headless-preview 0.9.0. Wagtail-disabled modes were checked separately on Django 6.1.2 with neither Wagtail nor the preview package installed.
- Backend suites: 23 tests with Next.js + Wagtail; 17 with native Wagtail; 17 with Next.js only; 13 with both disabled. Frontend: 8 tests, lint and typecheck passed. Generation suite: 4 tests, including all four combinations and built sandbox/prod configuration assertions. CMS-only migration drift checks passed in both CMS modes.
- Full-project `makemigrations --check` also reports pre-existing drift in `sites` options/ID and the user’s `first_name` length. Those unrelated model changes are outside this ticket; the new CMS models have no pending migrations.
- Real HTTP smoke passed in both CMS modes, covering draft visibility, preview, publish/update/unpublish, duplicate nested leaf slugs, restriction filtering and image delivery.
- To repeat HTTP checks with a normal Tilt project, set `SCAF_RUN_WAGTAIL_SMOKE=1`, `SCAF_SMOKE_PROJECT_DIR`, `SCAF_SMOKE_BACKEND_URL` and, for headless mode, `SCAF_SMOKE_FRONTEND_URL`, then run `python -m unittest tests.test_wagtail_smoke`. The default management command uses the generated kind context. For isolated host-process checks, the test-only `SCAF_SMOKE_MANAGE_COMMAND` accepts a Python/manage.py command prefix; supply its normal Django settings/database/origin environment too.
- Normal Linux `make compile` passed with the corrected constraints. A separate kind/Tilt validation used an isolated kubeconfig and alternate ports to protect the existing projects. It was blocked by the Docker VM disk being full (110 GB filesystem, 0 bytes available): PostgreSQL could not initialize. The test cluster was removed. Full container startup, pod replacement and Tilt media persistence remain unverified; no speculative PVC change was made.
- The available computer-use tool reported no browser. Visual editor/iframe verification remains an explicit pending check. Live AWS/S3/CloudFront/DNS/TLS verification requires the established deployment environment; rendered assertions do not substitute for that check.

## E2E follow-up (2026-10-30)

- Normal Scaf generation exposed the existing Node-version hook's GNU-only `sed -i` syntax. The hook now handles both GNU and macOS BSD sed; the complete hook was regression-tested with both implementations, and its test runs in root CI.
- After freeing disk space, the normal PostgreSQL deployment exposed a missing Wagtail integration setting: `django.contrib.postgres` is required by the database search backend. Enable it when Wagtail is selected and the configured database is PostgreSQL; retain SQLite support without adding a PostgreSQL-driver requirement to that mode. This omission was part of the Wagtail implementation, not an unrelated infrastructure error.
- Apply the same settings correction to the existing local `wagtail-e2e` project and rebuild through its actual Tilt server. Migration and backend startup now succeed. Django system checks are clean; Wagtail login, REST pages and Next.js `/content/` return HTTP 200.
- An isolated test Job using the actual backend image passed 24 backend tests on PostgreSQL and 7 CMS tests on SQLite, including the new published-content search regression. Generation/Node-hook suite: 5 tests passed.
- The opt-in HTTP suite must derive the kind cluster name from `copier__project_slug`: normal Scaf answer files omit the computed `copier__project_dash` value.
- Real HTTP smoke against the normal Scaf/Tilt/PostgreSQL project passed (41.6 seconds): draft/preview, publish/edit/unpublish, nested duplicate slugs, access restriction filtering and image delivery. Temporary fixture pages and the test Job were cleaned up; the application remains running. Browser editor/iframe interaction, pod-replacement media persistence and live AWS checks remain separate pending checks.
- CMS browser requests exposed a pre-existing local Debug Toolbar configuration issue: overriding `DISABLE_PANELS` with only Redirects enabled profiling by default. Python 3.12+ profiling does not support concurrent requests. Remove that override to restore the upstream defaults while retaining the other toolbar panels and the existing threaded server. Apply the same correction to the running E2E project; add an opt-in parallel login/sprite HTTP regression.
- Debug Toolbar follow-up verification: the rebuilt E2E backend reports profiling disabled by default; all 16 login/sprite requests over four concurrent connections returned HTTP 200 (5.6 seconds). No Wagtail page model, production setting or server concurrency change was needed.

## Review corrections (2026-10-30)

- Production-storage assertions now run in a fresh interpreter with a dummy environment, preserving the parent test session's database/apps/templates. Root CI generates and tests all three mail-service variants. The shared `collectstatic` init container remains unchanged.
- The abstract `CMSPage` shares origin and headless behavior; `.specific()` remains required. New page-model inheritance is documented. Incompatible child URLs are skipped with page-ID warnings; malformed API responses and upstream outages still fail visibly.
- Missing Next.js content pages consult Wagtail's native redirect matching, preserving 301/302, site priority and query fallback. Slug-change redirects are verified over real HTTP. Headless canonical URLs omit trailing slashes; native URLs retain them. Hero images use rendition alt text. Native generation removes unused API/serializer modules; redundant preview code is removed.
- Validation uses temporary generated projects, Python 3.13 / Django 6.0.9 / Wagtail 7.4.4: backend suites passed 29 headless, 20 native, 17 Next.js-only and 13 with both options off. Frontend passed 21 tests, typecheck and lint. Generation/Node-hook suite passed 5 tests; all three mail variants passed both storage tests. CMS migration drift checks passed in both rendering modes. Ruff and Bandit checks passed.
- The extended HTTP smoke suite passed both tests against isolated Django/Next.js processes and a temporary SQLite database, including draft preview, publishing, edits, images, nested paths, canonical URLs, slug-change 301, restrictions and unpublishing. Temporary servers were stopped and fixture pages cleaned up. These follow-up checks do not claim live AWS or browser-iframe validation.

### Encoding and initialization follow-up

- Replaced the synthetic request/middleware redirect adapter with Wagtail's `get_redirect` helper and native normalization/query fallback. Encoded Unicode, spaces and literal percent signs are covered. Unsupported target schemes return no match with a record-ID warning. The single-site limitation is explicit; public multisite routing is not provided.
- Missing hero sources return null through the API on `SourceImageIOError`, with an image-ID warning; unexpected errors still propagate. Preview caches its resolved object per request. CMS fetches and preview CSP share one server-side HTTP/HTTPS origin validator. Storage subprocesses retain interpreter/runtime environment while filtering ambient application/cloud settings; redundant parent snapshots are removed.
- Tree seeding remains a historical data migration. The existing migration init container now runs `initialize_cms` afterward in both Wagtail modes. It completes revisions, publication dates and indexing through native publication only for live starter pages without revisions. Atomic row locking and deterministic ordering avoid duplicate initialization; edits and deletions are preserved. Wagtail-disabled startup is unchanged.
- Validation: four SQLite backend suites passed 34/21/17/13 tests (85 total), headless/native PostgreSQL suites passed 34/21, frontend passed 28 tests plus typecheck/lint, generation/Node hooks passed 5 tests, and all three mail variants passed storage tests. CMS drift checks, Ruff and Bandit passed. Concurrent PostgreSQL initializers produced exactly two revisions for the two seed pages and searchable example content. Real HTTP smoke passed with Turkish slugs, encoded-space redirects and slug-change 301s, alongside publication/preview/media/restriction checks. Temporary HTTP servers and PostgreSQL container were stopped.
