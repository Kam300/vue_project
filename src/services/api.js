const API_BASE = '/api'

async function parseResponse(response) {
  const text = await response.text()
  if (!text) {
    return null
  }

  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`
  const headers = options.body
    ? { 'Content-Type': 'application/json', ...(options.headers || {}) }
    : (options.headers || {})

  const response = await fetch(url, {
    ...options,
    headers,
  })

  const payload = await parseResponse(response)
  if (!response.ok) {
    const message = payload?.error || `Request failed with status ${response.status}`
    throw new Error(message)
  }

  return payload
}

export function healthCheck() {
  return request('/health')
}

export function registerFace(data) {
  return request('/register_face', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function recognizeFace(data) {
  return request('/recognize_face', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function deleteFace(memberId) {
  return request(`/delete_face/${encodeURIComponent(memberId)}`, {
    method: 'DELETE',
  })
}

export function listFaces() {
  return request('/list_faces')
}

export function clearAll() {
  return request('/clear_all', {
    method: 'DELETE',
  })
}

export function generatePdf(data) {
  return request('/generate_pdf', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function buildDownloadPdfUrl(driveId) {
  return `${API_BASE}/download_pdf/${encodeURIComponent(driveId)}`
}

export default {
  healthCheck,
  registerFace,
  recognizeFace,
  deleteFace,
  listFaces,
  clearAll,
  generatePdf,
  buildDownloadPdfUrl,
}
