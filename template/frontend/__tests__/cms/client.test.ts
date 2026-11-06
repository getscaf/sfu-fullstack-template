import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getContentChildren, getContentPage, getContentPreview, getContentRedirect } from '@/lib/cms'

const page = {
  id: 3,
  meta: { type: 'cms.ContentPage', slug: 'example', html_url: 'https://site.example.test/content/example' },
  title: 'Example',
  intro: '',
  body: '<p>Content</p>',
  hero_image: null
}

describe('CMS server client', () => {
  const fetchMock = vi.fn<typeof fetch>()
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    vi.stubEnv('CMS_INTERNAL_BASE_URL', 'http://backend:8000')
    vi.stubEnv('CMS_BACKEND_BASE_URL', 'https://api.example.test')
    vi.stubEnv('CMS_PUBLIC_BASE_URL', 'https://site.example.test')
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    fetchMock.mockReset()
  })

  it('resolves a full nested path and follows the public API path internally', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 302, headers: { location: 'https://api.example.test/api/cms/v2/pages/3/' } })
    )
    fetchMock.mockResolvedValueOnce(Response.json(page))
    expect(await getContentPage(['parent', 'example'])).toEqual(page)
    expect(new URL(String(fetchMock.mock.calls[0][0])).searchParams.get('html_path')).toBe('/parent/example/')
    expect(new URL(String(fetchMock.mock.calls[1][0])).origin).toBe('http://backend:8000')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      redirect: 'manual',
      cache: 'no-store',
      headers: { Accept: 'application/json' }
    })
  })

  it('rejects redirects to arbitrary hosts', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 302, headers: { location: 'https://unexpected.example/api/cms/v2/pages/3/' } })
    )
    await expect(getContentPage([])).rejects.toThrow('unexpected redirect')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps upstream outages distinct from missing pages', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }))
    expect(await getContentPage(['missing'])).toBeNull()
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 503 }))
    await expect(getContentPage(['unavailable'])).rejects.toThrow('503')
  })

  it('rejects malformed paths before making an HTTP request', async () => {
    expect(await getContentPage(['..'])).toBeNull()
    expect(await getContentPage(['a/b'])).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('consumes native navigation items without exposing internal detail URLs', async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ items: [page] }))
    expect(await getContentChildren(1)).toEqual([{ id: 3, title: 'Example', href: '/content/example' }])
  })

  it('skips incompatible child URLs without losing valid navigation or logging their URLs', async () => {
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const child = (id: number, html_url: string) => ({ ...page, id, meta: { ...page.meta, html_url } })
    fetchMock.mockResolvedValueOnce(
      Response.json({
        items: [
          child(4, 'http://localhost/content/other'),
          page,
          child(5, 'https://site.example.test/about'),
          child(6, 'invalid-url'),
          child(7, 'https://site.example.test.attacker.test/content/page'),
          child(8, 'https://user:secret@site.example.test/content/page')
        ]
      })
    )
    expect(await getContentChildren(1)).toEqual([{ id: 3, title: 'Example', href: '/content/example' }])
    expect(warning).toHaveBeenCalledTimes(5)
    expect(JSON.stringify(warning.mock.calls)).not.toContain('secret')
    expect(warning).toHaveBeenCalledWith(expect.any(String), { pageId: 4 })
  })

  it('does not hide navigation outages or malformed API responses', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 503 }))
    await expect(getContentChildren(1)).rejects.toThrow('503')
    fetchMock.mockResolvedValueOnce(Response.json({ items: [{ id: 4 }] }))
    await expect(getContentChildren(1)).rejects.toThrow('Invalid CMS navigation item')
  })

  it('resolves editor redirects with native status codes and query strings', async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ destination: 'https://site.example.test/content/new/?q=1#part', status_code: 301 })
    )
    expect(await getContentRedirect('/content/old?b=2&a=1')).toEqual({
      destination: '/content/new?q=1#part',
      statusCode: 301
    })
    const lookup = new URL(String(fetchMock.mock.calls[0][0]))
    expect(lookup.origin).toBe('http://backend:8000')
    expect(lookup.searchParams.get('path')).toBe('/content/old?b=2&a=1')
    fetchMock.mockResolvedValueOnce(Response.json({ destination: 'https://external.example/new/', status_code: 302 }))
    expect(await getContentRedirect('/content/old')).toEqual({
      destination: 'https://external.example/new/',
      statusCode: 302
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('keeps missing redirect matches distinct from upstream outages', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }))
    expect(await getContentRedirect('/content/missing')).toBeNull()
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 503 }))
    await expect(getContentRedirect('/content/missing')).rejects.toThrow('503')
  })

  it.each(['ftp://files.example.test/file', 'ftps://files.example.test/file'])(
    'ignores unsupported redirect protocol %s without exposing the target in logs',
    async destination => {
      const warning = vi.spyOn(console, 'warn').mockImplementation(() => {})
      fetchMock.mockResolvedValueOnce(Response.json({ destination, status_code: 301 }))
      expect(await getContentRedirect('/content/old')).toBeNull()
      expect(warning).toHaveBeenCalledOnce()
      expect(JSON.stringify(warning.mock.calls)).not.toContain(destination)
    }
  )

  it('preserves encoded Unicode, spaces and percent signs in redirect lookups', async () => {
    for (const path of ['/content/caf%C3%A9?q=%C3%A7', '/content/old%20page', '/content/100%25']) {
      fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }))
      expect(await getContentRedirect(path)).toBeNull()
      const lookup = new URL(String(fetchMock.mock.lastCall?.[0]))
      expect(lookup.searchParams.get('path')).toBe(path)
    }
  })

  it.each([
    'javascript:alert(1)',
    '//external.example/path',
    '/\\external.example/path',
    'https://user:secret@external.example/'
  ])('rejects unsafe redirect destination %s', async destination => {
    fetchMock.mockResolvedValueOnce(Response.json({ destination, status_code: 301 }))
    await expect(getContentRedirect('/content/old')).rejects.toThrow('Invalid CMS redirect')
  })

  it('does not query redirects outside the CMS routes', async () => {
    for (const path of ['/about', '//external.example/content/path', '/content/../admin', '/content/old#fragment']) {
      expect(await getContentRedirect(path)).toBeNull()
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('accepts an unsaved preview without a canonical URL', async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ ...page, id: 0, meta: { type: 'cms.ContentPage', slug: 'unsaved' } })
    )
    const preview = await getContentPreview('cms.contentpage', 'private-token')
    expect(preview?.meta.html_url).toBeNull()
    expect(JSON.stringify(preview)).not.toContain('private-token')
  })
})
