/** Only ordinary API routes are forwarded. Recovery and arbitrary paths are excluded. */
export function allowedApiPath(url: string): boolean {
  const path = url.split('?')[0]
  return /^\/api\/(?:health|session|documents|export)$/.test(path) ||
    /^\/api\/(?:questionnaires|questionnaire-items|answers|evidence|memberships|audit|workflow-jobs|retrieval)(?:\/[A-Za-z0-9-]+)*$/.test(path)
}
