const dateFormat = new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat('vi-VN', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

// Show the raw value for an unparseable date: Intl throws on Invalid Date and would crash the page
const safeFormat = (format: Intl.DateTimeFormat, iso: string) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : format.format(date)
}

export const formatDate = (iso: string) => safeFormat(dateFormat, iso)
export const formatDateTime = (iso: string) => safeFormat(dateTimeFormat, iso)

export const formatPercent = (value: number, digits = 1) =>
  `${(value * 100).toLocaleString('vi-VN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`

export const formatNumber = (value: number, digits = 2) =>
  value.toLocaleString('vi-VN', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export const initials = (name: string) =>
  name
    .split(' ')
    .filter(Boolean)
    .slice(-2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()
