import { sha256FromBytes } from '@/utils/crypto'

export async function fileToDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Не удалось прочитать изображение'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsDataURL(file)
  })
}

export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const response = await fetch(dataUrl)
  return response.blob()
}

export async function blobToBase64DataUrl(blob: Blob): Promise<string> {
  return fileToDataUrl(blob)
}

export async function loadImageElement(input: Blob | string): Promise<HTMLImageElement> {
  const src = typeof input === 'string' ? input : URL.createObjectURL(input)
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.onerror = () => reject(new Error('Не удалось загрузить изображение'))
    image.onload = () => resolve(image)
    image.src = src
  })

  if (typeof input !== 'string') URL.revokeObjectURL(src)
  return img
}

export async function compressImageToJpeg(
  input: Blob | string,
  options: { maxEdge?: number; quality?: number } = {}
): Promise<Blob> {
  const maxEdge = options.maxEdge ?? 1280
  const quality = options.quality ?? 0.8
  const image = await loadImageElement(input)

  let width = image.width
  let height = image.height

  const maxCurrent = Math.max(width, height)
  if (maxCurrent > maxEdge) {
    const ratio = maxEdge / maxCurrent
    width = Math.max(1, Math.round(width * ratio))
    height = Math.max(1, Math.round(height * ratio))
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) {
    throw new Error('Не удалось подготовить canvas')
  }
  context.drawImage(image, 0, 0, width, height)

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', quality)
  )
  if (!blob) {
    throw new Error('Не удалось сжать изображение')
  }
  return blob
}

export async function makePerceptualHash(input: Blob | string): Promise<string> {
  const image = await loadImageElement(input)
  const canvas = document.createElement('canvas')
  canvas.width = 8
  canvas.height = 8
  const context = canvas.getContext('2d')
  if (!context) {
    throw new Error('Canvas недоступен')
  }

  context.drawImage(image, 0, 0, 8, 8)
  const data = context.getImageData(0, 0, 8, 8).data

  let total = 0
  const brightness: number[] = []
  for (let i = 0; i < data.length; i += 4) {
    const value = Math.floor((data[i] + data[i + 1] + data[i + 2]) / 3)
    brightness.push(value)
    total += value
  }

  const avg = total / 64
  return brightness.map((item) => (item >= avg ? '1' : '0')).join('')
}

export async function imageSha256(input: Blob | string): Promise<string> {
  const blob = typeof input === 'string' ? await dataUrlToBlob(input) : input
  const bytes = await blob.arrayBuffer()
  return sha256FromBytes(bytes)
}

export async function ensureFaceApiPayload(input: Blob | string): Promise<string> {
  if (typeof input === 'string' && input.startsWith('data:image')) return input
  const compressed = await compressImageToJpeg(input, { maxEdge: 640, quality: 0.85 })
  return blobToBase64DataUrl(compressed)
}
