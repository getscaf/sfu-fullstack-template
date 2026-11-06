import type { GetServerSideProps } from 'next'

import ContentPage from '@/components/cms/ContentPage'
import { getContentChildren, getContentPage, getContentRedirect } from '@/lib/cms'
import type { CmsPageProps } from '@/types/cms'

export const getServerSideProps: GetServerSideProps<CmsPageProps, { slug?: string[] }> = async ({
  params,
  res,
  resolvedUrl
}) => {
  res.setHeader('Cache-Control', 'no-store')
  const page = await getContentPage(params?.slug ?? [])
  if (!page) {
    const redirect = await getContentRedirect(resolvedUrl)
    return redirect ? { redirect } : { notFound: true }
  }
  const navigation = await getContentChildren(page.id)
  return { props: { page, navigation } }
}

export default ContentPage
