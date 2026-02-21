export function normalizePhone(phone: string): string {
  const cleaned = phone.replace(/[^\d+]/g, '')
  if (!cleaned) return ''

  if (cleaned.startsWith('8') && cleaned.length === 11) {
    return `+7${cleaned.slice(1)}`
  }

  if (!cleaned.startsWith('+') && cleaned.length >= 10) {
    return `+${cleaned}`
  }

  return cleaned
}

export function isPhoneValid(phone: string): boolean {
  const normalized = normalizePhone(phone)
  const digits = normalized.replace('+', '')
  if (digits.length < 10 || digits.length > 15) return false

  if (normalized.startsWith('+7')) return digits.length === 11
  return true
}

export function toTelegramLink(phone: string): string {
  const value = normalizePhone(phone).replace('+', '')
  return `https://t.me/${value}`
}

export function toWhatsAppLink(phone: string): string {
  const value = normalizePhone(phone).replace('+', '')
  return `https://wa.me/${value}`
}

export function toTelLink(phone: string): string {
  return `tel:${normalizePhone(phone)}`
}
