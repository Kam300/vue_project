const DISPLAY_DATE_PATTERN = /^(\d{2})\.(\d{2})\.(\d{4})$/
const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/

export function normalizeDateToDisplayFormat(value: string): string {
  const raw = value.trim()
  if (!raw) return ''
  if (DISPLAY_DATE_PATTERN.test(raw)) return raw

  const isoMatch = raw.match(ISO_DATE_PATTERN)
  if (isoMatch) {
    const [, year, month, day] = isoMatch
    return `${day}.${month}.${year}`
  }

  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw

  const day = String(parsed.getDate()).padStart(2, '0')
  const month = String(parsed.getMonth() + 1).padStart(2, '0')
  const year = String(parsed.getFullYear())
  return `${day}.${month}.${year}`
}

export function displayDateToISO(value: string): string {
  const match = value.trim().match(DISPLAY_DATE_PATTERN)
  if (!match) return ''
  const [, day, month, year] = match
  return `${year}-${month}-${day}`
}

export function isDisplayDateValid(value: string): boolean {
  const match = value.trim().match(DISPLAY_DATE_PATTERN)
  if (!match) return false
  const [, dayStr, monthStr, yearStr] = match
  const day = Number(dayStr)
  const month = Number(monthStr)
  const year = Number(yearStr)

  if (month < 1 || month > 12) return false
  if (year < 1900 || year > 2200) return false

  const date = new Date(year, month - 1, day)
  return (
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
  )
}

export function formatDateForHuman(value: string): string {
  return normalizeDateToDisplayFormat(value)
}

export function nowIso(): string {
  return new Date().toISOString()
}
