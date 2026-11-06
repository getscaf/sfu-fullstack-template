export type CmsImage = {
  url: string
  width: number
  height: number
  alt: string
}

export type CmsPage = {
  id: number
  meta: { type: string; slug: string; html_url: string | null }
  title: string
  intro: string
  body: string
  hero_image: CmsImage | null
}

export type CmsLink = { id: number; title: string; href: string }
export type CmsPageProps = { page: CmsPage; navigation: CmsLink[] }
