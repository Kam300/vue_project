export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function downloadText(content: string, filename: string, type = 'text/plain;charset=utf-8'): void {
  const blob = new Blob([content], { type })
  downloadBlob(blob, filename)
}

export function openLinkInNewTab(url: string): void {
  window.open(url, '_blank', 'noopener,noreferrer')
}
