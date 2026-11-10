import type { GetServerSidePropsContext } from 'next'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getContentChildren, getContentPage, getContentRedirect } from '@/lib/cms'
import { getServerSideProps } from '@/pages/content/[[...slug]]'

vi.mock('@/lib/cms', () => ({
  getContentChildren: vi.fn(),
  getContentPage: vi.fn(),
  getContentRedirect: vi.fn()
}))

describe('CMS server route', () => {
  const context = {
    params: { slug: ['old'] },
    resolvedUrl: '/content/old?campaign=example',
    res: { setHeader: vi.fn() }
  } as unknown as GetServerSidePropsContext<{ slug?: string[] }>

  beforeEach(() => vi.resetAllMocks())

  it('consults Wagtail redirects only when the published page is missing', async () => {
    vi.mocked(getContentPage).mockResolvedValue(null)
    vi.mocked(getContentRedirect).mockResolvedValue({ destination: '/content/new', statusCode: 301 })
    expect(await getServerSideProps(context)).toEqual({ redirect: { destination: '/content/new', statusCode: 301 } })
    expect(getContentRedirect).toHaveBeenCalledWith('/content/old?campaign=example')
    expect(getContentChildren).not.toHaveBeenCalled()
    expect(context.res.setHeader).toHaveBeenCalledWith('Cache-Control', 'no-store')
  })

  it('returns 404 when neither a page nor a redirect exists', async () => {
    vi.mocked(getContentPage).mockResolvedValue(null)
    vi.mocked(getContentRedirect).mockResolvedValue(null)
    expect(await getServerSideProps(context)).toEqual({ notFound: true })
  })

  it('does not replace an existing page with an editor redirect', async () => {
    const page = { id: 3, title: 'Existing' } as Awaited<ReturnType<typeof getContentPage>>
    vi.mocked(getContentPage).mockResolvedValue(page)
    vi.mocked(getContentChildren).mockResolvedValue([])
    expect(await getServerSideProps(context)).toEqual({ props: { page, navigation: [] } })
    expect(getContentRedirect).not.toHaveBeenCalled()
  })

  it('propagates backend failures instead of returning 404 or a redirect', async () => {
    vi.mocked(getContentPage).mockRejectedValue(new Error('CMS unavailable'))
    await expect(getServerSideProps(context)).rejects.toThrow('CMS unavailable')
    expect(getContentRedirect).not.toHaveBeenCalled()
  })
})
