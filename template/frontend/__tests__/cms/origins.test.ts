import { afterEach, expect, it, vi } from 'vitest'

import { cmsOrigin } from '@/lib/cms-origins'

afterEach(() => vi.unstubAllEnvs())

it.each(['CMS_INTERNAL_BASE_URL', 'CMS_BACKEND_BASE_URL', 'CMS_PUBLIC_BASE_URL'] as const)(
  'applies the same origin validation to %s',
  name => {
    vi.stubEnv(name, 'https://EXAMPLE.test:443/')
    expect(cmsOrigin(name).origin).toBe('https://example.test')
    for (const value of [
      'not-a-url',
      'ftp://example.test',
      'https://user:secret@example.test',
      'https://example.test/prefix',
      'https://example.test/?token=secret',
      'https://example.test/#fragment'
    ]) {
      vi.stubEnv(name, value)
      expect(() => cmsOrigin(name)).toThrow(`Invalid ${name}`)
    }
  }
)

it('retains local defaults and the internal DJANGO_ADDRESS fallback', () => {
  vi.stubEnv('CMS_INTERNAL_BASE_URL', undefined)
  vi.stubEnv('CMS_BACKEND_BASE_URL', undefined)
  vi.stubEnv('CMS_PUBLIC_BASE_URL', undefined)
  vi.stubEnv('DJANGO_ADDRESS', 'backend:8000')
  expect(cmsOrigin('CMS_INTERNAL_BASE_URL').origin).toBe('http://backend:8000')
  expect(cmsOrigin('CMS_BACKEND_BASE_URL').origin).toBe('http://localhost:8000')
  expect(cmsOrigin('CMS_PUBLIC_BASE_URL').origin).toBe('http://localhost:3000')
})
