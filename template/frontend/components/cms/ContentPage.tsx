{% raw %}/* eslint-disable @next/next/no-img-element -- Wagtail provides pre-sized image renditions. */
import Head from 'next/head'
import Link from 'next/link'

import type { CmsPageProps } from '@/types/cms'

export default function ContentPage({ page, navigation }: CmsPageProps) {
  return (
    <>
      <Head>
        <title>{page.title}</title>
        {page.meta.html_url ? <link rel='canonical' href={page.meta.html_url} /> : null}
      </Head>
      <article className='py-6'>
        <h1 className='mb-4 text-3xl font-bold'>{page.title}</h1>
        {page.intro ? <p className='mb-4 text-lg'>{page.intro}</p> : null}
        {page.hero_image ? (
          <img
            src={page.hero_image.url}
            width={page.hero_image.width}
            height={page.hero_image.height}
            alt={page.hero_image.alt}
            className='mb-4 h-auto max-w-full'
          />
        ) : null}
        {/* The CMS expands references and sanitizes this HTML for both renderers. */}
        <div className='cms-body' dangerouslySetInnerHTML={{ __html: page.body }} />
      </article>
      {navigation.length ? (
        <nav aria-label='Content pages'>
          <ul className='list-inside list-disc'>
            {navigation.map(child => (
              <li key={child.id}>
                <Link href={child.href}>{child.title}</Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </>
  )
}{% endraw %}
