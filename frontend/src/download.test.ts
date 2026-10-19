import { afterEach, expect, it, vi } from 'vitest'
import { safeZipFilename, startZipDownload } from './download'
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('keeps ZIP filenames local, bounded and safe on Windows', () => {
  expect(safeZipFilename('../../result.zip')).toBe('result.zip')
  expect(safeZipFilename('C:\\Downloads\\result.zip')).toBe('result.zip')
  expect(safeZipFilename('CON.zip')).toBe('download-CON.zip')
  expect(safeZipFilename('evil.exe')).toBe('evil.exe.zip')
  expect(safeZipFilename('...')).toBe('questionnaire-export.zip')
  expect(safeZipFilename('a'.repeat(500))).toHaveLength(144)
})
it('starts a download and releases its temporary object URL after browser dispatch', () => {
  vi.useFakeTimers()
  const create = vi.fn(() => 'blob:synthetic-test'); const revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  let link: HTMLAnchorElement | undefined
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { link = this })
  const blob = new Blob(['synthetic zip'], { type: 'application/zip' })
  expect(startZipDownload(blob, '../result.zip')).toBe('result.zip')
  expect(create).toHaveBeenCalledWith(blob)
  expect(link!.download).toBe('result.zip'); expect(link!.href).toBe('blob:synthetic-test')
  expect(document.querySelector('a[download]')).toBeNull(); expect(revoke).not.toHaveBeenCalled()
  vi.advanceTimersByTime(1000); expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:synthetic-test')
})
it('removes the anchor and revokes immediately if browser dispatch fails', () => {
  const revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: () => 'blob:failed-test', revokeObjectURL: revoke })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { throw new Error('Download blocked') })
  expect(() => startZipDownload(new Blob(['zip']), 'result.zip')).toThrow('Download blocked')
  expect(document.querySelector('a[download]')).toBeNull(); expect(revoke).toHaveBeenCalledWith('blob:failed-test')
})
