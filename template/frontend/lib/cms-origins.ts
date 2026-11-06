// Server-only configuration shared by CMS fetching and preview framing.
import { env } from 'node:process'

type CmsOriginName = 'CMS_INTERNAL_BASE_URL' | 'CMS_BACKEND_BASE_URL' | 'CMS_PUBLIC_BASE_URL'

export function cmsOrigin(name: CmsOriginName): URL {
  const fallback =
    name === 'CMS_INTERNAL_BASE_URL'
      ? `http://${env.DJANGO_ADDRESS ?? 'localhost:8000'}`
      : name === 'CMS_PUBLIC_BASE_URL'
        ? 'http://localhost:3000'
        : 'http://localhost:8000'
  let url: URL
  try {
    url = new URL(env[name] ?? fallback)
  } catch {
    throw new Error(`Invalid ${name}`)
  }
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  ) {
    throw new Error(`Invalid ${name}`)
  }
  return url
}
