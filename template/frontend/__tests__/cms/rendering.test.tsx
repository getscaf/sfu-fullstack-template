{% raw %}import { expect, test } from 'vitest'

import ContentPage from '@/components/cms/ContentPage'
import { render, screen } from '@/utils/test-utils'

test('renders CMS content, rendition metadata and child navigation', () => {
  render(
    <ContentPage
      page={{
        id: 1,
        meta: { type: 'cms.ContentPage', slug: 'home', html_url: null },
        title: 'Managed content',
        intro: 'An introduction',
        body: '<p>Published body</p>',
        hero_image: { url: 'https://assets.example.test/hero.jpg', width: 1200, height: 600, alt: 'Hero description' }
      }}
      navigation={[{ id: 2, title: 'Child page', href: '/content/child' }]}
    />
  )
  expect(screen.getByRole('heading', { level: 1, name: 'Managed content' })).toBeInTheDocument()
  expect(screen.getByText('Published body')).toBeInTheDocument()
  expect(screen.getByAltText('Hero description')).toHaveAttribute('width', '1200')
  expect(screen.getByRole('link', { name: 'Child page' })).toHaveAttribute('href', '/content/child')
}){% endraw %}
