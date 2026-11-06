import type { GetServerSideProps } from 'next'

import ContentPage from '@/components/cms/ContentPage'
import { getContentPreview } from '@/lib/cms'
import { cmsOrigin } from '@/lib/cms-origins'
import type { CmsPageProps } from '@/types/cms'

export const getServerSideProps: GetServerSideProps<CmsPageProps> = async ({ query, res }) => {
  res.setHeader('Cache-Control', 'private, no-store')
  res.setHeader('Referrer-Policy', 'no-referrer')
  res.setHeader('X-Robots-Tag', 'noindex, nofollow')
  const backendOrigin = cmsOrigin('CMS_BACKEND_BASE_URL').origin
  res.setHeader('Content-Security-Policy', `frame-ancestors 'self' ${backendOrigin}`)
  if (typeof query.content_type !== 'string' || typeof query.token !== 'string') return { notFound: true }
  const page = await getContentPreview(query.content_type, query.token)
  if (!page) return { notFound: true }
  return { props: { page, navigation: [] } }
}

export default ContentPage
