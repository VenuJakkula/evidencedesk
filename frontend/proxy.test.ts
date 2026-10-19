import { describe, expect, it } from 'vitest'
import { allowedApiPath } from './proxy'

describe('development proxy route boundary', () => {
  it.each(['/api/health', '/api/session', '/api/documents', '/api/export', '/api/questionnaires/preview', '/api/questionnaires/id/items?offset=0&limit=100', '/api/questionnaire-items/id/approve', '/api/answers/id'])('allows ordinary API route %s', (path) => {
    expect(allowedApiPath(path)).toBe(true)
  })
  it.each(['/api/local/api-key', '/api/../local/api-key', '/api/%2e%2e/local/api-key', '/api/questionnaires/../../local/api-key', '/api/questionnaires/%2f../local/api-key', '/api//local/api-key', '/api\\local\\api-key', '/api/docs', '/apilocal/api-key'])('blocks recovery and malformed route %s', (path) => {
    expect(allowedApiPath(path)).toBe(false)
  })
})
