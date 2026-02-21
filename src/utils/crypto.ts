function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function sha256FromString(input: string): Promise<string> {
  const encoder = new TextEncoder()
  const hash = await crypto.subtle.digest('SHA-256', encoder.encode(input))
  return bytesToHex(new Uint8Array(hash))
}

export async function sha256FromBytes(input: ArrayBuffer | Uint8Array): Promise<string> {
  const source = input instanceof Uint8Array ? input : new Uint8Array(input)
  const normalized = new Uint8Array(source.byteLength)
  normalized.set(source)
  const hash = await crypto.subtle.digest('SHA-256', normalized)
  return bytesToHex(new Uint8Array(hash))
}
