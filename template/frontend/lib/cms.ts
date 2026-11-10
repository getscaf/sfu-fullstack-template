// Import this module only from getServerSideProps. Next.js removes those imports
// from browser bundles; Node's process import also prevents accidental client use.
import { cmsOrigin } from '@/lib/cms-origins'
import type { CmsImage, CmsLink, CmsPage } from '@/types/cms'

const API_ROOT = '/api/cms/v2/'
const PAGE_FIELDS = 'title,intro,body,hero_image,slug,html_url'

function request(path: string, query?: Record<string, string>): Promise<Response> {
  const url = new URL(path, cmsOrigin('CMS_INTERNAL_BASE_URL'))
  if (query) url.search = new URLSearchParams(query).toString()
  // No browser cookies/authorization are forwarded to the public CMS API.
  return fetch(url, {
    headers: { Accept: 'application/json' },
    redirect: 'manual',
    cache: 'no-store',
    signal: AbortSignal.timeout(5000)
  })
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function image(value: unknown): value is CmsImage {
  return (
    record(value) &&
    typeof value.url === 'string' &&
    typeof value.width === 'number' &&
    typeof value.height === 'number' &&
    typeof value.alt === 'string'
  )
}

function parsePage(value: unknown): CmsPage {
  if (
    !record(value) ||
    !record(value.meta) ||
    value.meta.type !== 'cms.ContentPage' ||
    typeof value.meta.slug !== 'string' ||
    (value.meta.html_url !== null && value.meta.html_url !== undefined && typeof value.meta.html_url !== 'string') ||
    typeof value.id !== 'number' ||
    typeof value.title !== 'string' ||
    typeof value.intro !== 'string' ||
    typeof value.body !== 'string' ||
    (value.hero_image !== null && !image(value.hero_image))
  ) {
    throw new Error('Unsupported CMS page response. Check the page serializer and renderer.')
  }
  // Select only browser-facing fields; native API detail URLs may be internal.
  return {
    id: value.id,
    meta: {
      type: value.meta.type,
      slug: value.meta.slug,
      html_url: typeof value.meta.html_url === 'string' ? value.meta.html_url : null
    },
    title: value.title,
    intro: value.intro,
    body: value.body,
    hero_image: value.hero_image
  }
}

async function readPage(response: Response): Promise<CmsPage | null> {
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`CMS upstream returned ${response.status}`)
  return parsePage(await response.json())
}

export async function getContentPage(segments: string[]): Promise<CmsPage | null> {
  if (
    segments.length > 20 ||
    segments.some(segment => !segment || segment === '.' || segment === '..' || /[/\\?#\u0000-\u001f]/.test(segment))
  ) {
    return null
  }
  const found = await request(`${API_ROOT}pages/find/`, {
    html_path: segments.length ? `/${segments.join('/')}/` : '/',
    fields: PAGE_FIELDS
  })
  if (found.status === 404) return null
  if (found.status !== 302) throw new Error(`CMS page lookup returned ${found.status}`)
  const location = found.headers.get('location')
  if (!location) throw new Error('CMS page lookup omitted its redirect')
  const detail = new URL(location, cmsOrigin('CMS_INTERNAL_BASE_URL'))
  const publicBackend = cmsOrigin('CMS_BACKEND_BASE_URL').origin
  if (
    ![cmsOrigin('CMS_INTERNAL_BASE_URL').origin, publicBackend].includes(detail.origin) ||
    !/^\/api\/cms\/v2\/pages\/\d+\/$/.test(detail.pathname)
  ) {
    throw new Error('CMS page lookup returned an unexpected redirect')
  }
  // Preserve Wagtail's field selection while keeping requests on the trusted backend.
  return readPage(await request(detail.pathname, { fields: PAGE_FIELDS }))
}

export async function getContentChildren(parentId: number): Promise<CmsLink[]> {
  const response = await request(`${API_ROOT}pages/`, {
    child_of: String(parentId),
    fields: 'title,html_url',
    limit: '100'
  })
  if (!response.ok) throw new Error(`CMS navigation returned ${response.status}`)
  const data: unknown = await response.json()
  if (!record(data) || !Array.isArray(data.items)) throw new Error('Invalid CMS navigation response')
  const publicOrigin = cmsOrigin('CMS_PUBLIC_BASE_URL').origin
  return data.items.flatMap((item: unknown) => {
    if (
      !record(item) ||
      !record(item.meta) ||
      typeof item.id !== 'number' ||
      typeof item.title !== 'string' ||
      typeof item.meta.html_url !== 'string'
    )
      throw new Error('Invalid CMS navigation item')
    let url: URL
    try {
      url = new URL(item.meta.html_url)
    } catch {
      console.warn('Skipping CMS navigation item with an invalid public URL', { pageId: item.id })
      return []
    }
    if (url.origin !== publicOrigin || url.username || url.password || !url.pathname.startsWith('/content/')) {
      console.warn('Skipping CMS navigation item with an unexpected public URL', { pageId: item.id })
      return []
    }
    return [{ id: item.id, title: item.title, href: url.pathname }]
  })
}

export async function getContentRedirect(path: string): Promise<{ destination: string; statusCode: 301 | 302 } | null> {
  if (!path.startsWith('/') || path.startsWith('//') || path.length > 2048 || /[\\#\u0000-\u001f]/.test(path)) {
    return null
  }
  const publicOrigin = cmsOrigin('CMS_PUBLIC_BASE_URL').origin
  const source = new URL(path, publicOrigin)
  if (source.pathname !== '/content' && !source.pathname.startsWith('/content/')) return null
  const response = await request(`${API_ROOT}redirect/`, { path })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`CMS redirect lookup returned ${response.status}`)
  const data: unknown = await response.json()
  if (
    !record(data) ||
    typeof data.destination !== 'string' ||
    (data.status_code !== 301 && data.status_code !== 302) ||
    data.destination.startsWith('//') ||
    /[\\\u0000-\u001f]/.test(data.destination)
  ) {
    throw new Error('Invalid CMS redirect response')
  }
  const destination = new URL(data.destination, publicOrigin)
  if (['ftp:', 'ftps:'].includes(destination.protocol)) {
    console.warn('Ignoring unsupported CMS redirect protocol')
    return null
  }
  if (
    !/^(\/|https?:\/\/)/i.test(data.destination) ||
    !['http:', 'https:'].includes(destination.protocol) ||
    destination.username ||
    destination.password
  ) {
    throw new Error('Invalid CMS redirect destination')
  }
  // Editors may configure external redirects; these are browser destinations,
  // never fetched by the server. Normalize only our own CMS page URLs.
  if (destination.origin === publicOrigin) {
    if (destination.pathname.startsWith('/content/')) destination.pathname = destination.pathname.replace(/\/+$/, '')
    return { destination: destination.pathname + destination.search + destination.hash, statusCode: data.status_code }
  }
  return { destination: destination.href, statusCode: data.status_code }
}

export async function getContentPreview(contentType: string, token: string): Promise<CmsPage | null> {
  return readPage(
    await request(`${API_ROOT}page_preview/`, {
      content_type: contentType,
      token,
      fields: PAGE_FIELDS
    })
  )
}
