const TIMEZONE_SUFFIX = /(Z|[+-]\d{2}:\d{2})$/i

export function serverDate(value: string): Date {
  const normalized = TIMEZONE_SUFFIX.test(value) ? value : `${value}Z`
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? new Date(value) : parsed
}
