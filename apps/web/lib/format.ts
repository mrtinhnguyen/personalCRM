export const APP_LOCALE = "en-US";

export function formatNumber(value: number): string {
  return value.toLocaleString(APP_LOCALE);
}

export function formatDate(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium" },
): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(APP_LOCALE, options).format(date);
}
