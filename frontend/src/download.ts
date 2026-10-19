/** Downloads use a temporary Blob URL, never a credential-bearing API URL. */
export function safeZipFilename(value: string): string {
  const basename = value.split(/[\\/]/).pop() || ''
  let name = basename.replace(/[^A-Za-z0-9_. -]/g, '_').replace(/^\.+/, '').trim().slice(0, 140)
  if (!name) return 'questionnaire-export.zip'
  if (!/\.zip$/i.test(name)) name += '.zip'
  if (/^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)/i.test(name)) name = `download-${name}`
  return name
}

export function startZipDownload(blob: Blob, filename: string): string {
  const safeName = safeZipFilename(filename)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  try {
    anchor.href = url; anchor.download = safeName; anchor.hidden = true
    document.body.appendChild(anchor)
    anchor.click()
  } catch (cause) {
    URL.revokeObjectURL(url)
    throw cause
  } finally { anchor.remove() }
  // Let the browser consume the click before releasing the URL. The file is already in memory.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  return safeName
}
