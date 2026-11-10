# Wagtail CMS

This project includes Wagtail {{ 'with Next.js rendering' if copier__create_nextjs_frontend else 'with Django rendering' }}. The existing users, Django admin{% if copier__create_nextjs_frontend %}, GraphQL API and Apollo client{% endif %} remain available.

## First use

Start the project using the normal development setup and `tilt up`. The existing migration step creates a CMS home and a published example page once.

The migration init container automatically runs `initialize_cms` after `migrate`. It completes revisions, publication dates and search indexing for live starter pages that have no revision yet. Re-running it preserves edited pages and does not recreate deleted content. When running Django outside the provided Kubernetes setup, run `python manage.py initialize_cms` after the initial migrations.

Create an administrator using the existing backend shell:

```bash
make shell-backend
python manage.py createsuperuser
```

| Local URL | Purpose |
| --- | --- |
| `http://localhost:8000/cms/` | Wagtail editor login |
| `http://localhost:{{ '3000' if copier__create_nextjs_frontend else '8000' }}/content{{ '' if copier__create_nextjs_frontend else '/' }}` | CMS home |
| `http://localhost:{{ '3000' if copier__create_nextjs_frontend else '8000' }}/content/example{{ '' if copier__create_nextjs_frontend else '/' }}` | Published example |
| `http://localhost:8000/admin/` | Existing Django admin, subject to the configured admin URL |

In Wagtail, select **Pages → Content**, add a **Content page**, enter its title/body and publish. Nested pages receive routes automatically. Preview also works before the first publication and for unsaved edits. No seeding command, frontend route file or rebuild is needed for another page of the starter type. Re-running migrations preserves edits and does not recreate deleted example pages.

{% if copier__create_nextjs_frontend %}
## Headless rendering and preview

Next.js Pages Router renders `/content/[[...slug]]` with `getServerSideProps`. It reads fresh published content on every request. If a page is missing, it checks Wagtail redirects through `/api/cms/v2/redirect/?path=/content/old`; supported matches return their native 301/302 status. This includes automatic redirects after a slug change, encoded Unicode/space paths and query-string matching. The starter uses one default Wagtail Site; redirects tied to that site take precedence over global redirects. Selecting different sites from multiple public domains requires additional routing for both page lookup and redirects. Without a redirect, unknown, unpublished or restricted pages return 404; backend outages remain errors. Redirect lookup is limited to `/content` routes; destinations support relative paths and HTTP/HTTPS. Unsupported targets such as FTP/FTPS are ignored with a warning and return no match. Root and About keep their existing behavior.

Headless public URLs have no trailing slash, matching Next.js canonical URLs. Django-rendered projects retain Wagtail's trailing slashes. Navigation skips child URLs outside the configured public CMS origin/path and logs the page ID so that one incompatible model does not break its parent page. Invalid API responses and backend outages still raise errors.

The native REST API lives at `/api/cms/v2/pages/`. Resolve a nested path with `/api/cms/v2/pages/find/?html_path=/parent/child/`; Wagtail returns a redirect to its page detail endpoint. The frontend follows only a validated detail path on the configured backend. Navigation uses `child_of`, with up to 100 direct published children. Rich text is expanded/sanitized by Django and shared by native/Next.js renderers. Image renditions include dimensions and alt text. If a hero's source file is missing, the API logs its image ID and returns `hero_image: null`, keeping text content available; other unexpected failures remain errors.

`wagtail-headless-preview` stores the editor's draft snapshot. Its thin API adapter at `/api/cms/v2/page_preview/` validates the signed token with a ten-minute maximum age. The frontend `/cms-preview` page uses the normal content component, allows framing by the CMS origin and disables caching/indexing. Refresh the editor preview after a token expires. Drafts are never added to public navigation; no extra preview secret is required.

`CMS_INTERNAL_BASE_URL` is server-only (`http://backend:8000` in Docker). `CMS_PUBLIC_BASE_URL` selects the frontend's public origin; `CMS_BACKEND_BASE_URL` selects the browser-accessible backend. Local defaults use ports 3000/8000. A shared server helper validates all three as HTTP/HTTPS origins without credentials, path prefixes, query strings or fragments. Keep these origins aligned if developing outside the normal containers.
{% endif %}

## Deployment and document access

Use the existing Terraform, sealed-secret and ArgoCD workflow. CMS addresses and storage values are generated from the normal project inputs:

| Environment | CMS pages | CMS admin/backend | Assets |
| --- | --- | --- | --- |
| Sandbox | `https://{% if not copier__create_nextjs_frontend %}api.{% endif %}sandbox.{{ copier__domain_name }}/content{{ '' if copier__create_nextjs_frontend else '/' }}` | `https://api.sandbox.{{ copier__domain_name }}/cms/` | `https://sandbox.{{ copier__domain_name }}` |
| Production | `https://{% if not copier__create_nextjs_frontend %}api.{% endif %}prod.{{ copier__domain_name }}/content{{ '' if copier__create_nextjs_frontend else '/' }}` | `https://api.prod.{{ copier__domain_name }}/cms/` | `https://prod.{{ copier__domain_name }}` |

{% if copier__create_nextjs_frontend %}
CloudFront uses the separate upstreams `nextjs.sandbox.{{ copier__domain_name }}` and `nextjs.prod.{{ copier__domain_name }}`. Their DNS, ingress and certificate names must stay aligned. Public page links use the public site addresses above.
{% else %}
CMS pages render directly on the backend. The public domain's CloudFront distribution serves assets from S3.
{% endif %}

The sandbox/prod overlays select `{{ copier__project_dash }}-{sandbox|prod}-static-storage`. `STORAGES` uses the existing S3 backends, private objects and CloudFront OAC. The deployment init container runs `collectstatic` before the backend starts. Existing sealed S3 credentials are available to both processes; IAM/SDK credentials remain supported outside that setup.

Only `static/`, `media/original_images/`, `media/images/` and Wagtail profile `media/avatar_images/` are public through CloudFront. Documents use Wagtail's `/documents/` serving view and collection permissions; direct document URLs are denied in development and through S3/CloudFront. Link documents using the editor's document chooser. Keep new private upload directories outside public CDN grants. To add another public media directory, update `public_asset_prefixes` in `terraform/modules/base/locals.tf`; both the bucket grant and CDN routing are derived from that list.

These generated defaults target new projects. Moving domains, existing files or Terraform state in an already deployed application requires a separate migration.

## Extend the starter

`cms/models.py` defines the abstract `CMSPage` and its concrete starter `ContentPage`, with title/slug, intro, rich text and an optional hero image. **Inherit new CMS page models from `CMSPage`, rather than directly from Wagtail's `Page`.** This shares the configured public URL origin and, in headless mode, preview/serving behavior. Update the parent's `subpage_types` and the new model's `parent_page_types` to allow the new type in the tree. Add fields/panels and run normal Django migrations for content-model changes. The initial migration deliberately has no dependency on the optional headless mixin.

{% if copier__create_nextjs_frontend %}
Expose new fields using Wagtail `APIField`, then update `frontend/types/cms.ts`, the response parser in `frontend/lib/cms.ts`, and `frontend/components/cms/ContentPage.tsx`. For a new page model, register it in the preview endpoint's `preview_models` and add its serializer/renderer handling. Keep the published API's `.specific()` queryset: URL overrides on `CMSPage` require concrete model instances. The existing Strawberry schema does not need to change.
{% endif %}

The Django template is `cms/templates/cms/content_page.html`. Both modes use the same restricted rich text renderer; if you enable additional editor features, update its allowed tags/attributes and tests together. Run the existing backend{% if copier__create_nextjs_frontend %} and frontend{% endif %} checks after extending the contract.
