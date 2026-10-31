import type { ReactNode } from 'react'
export function OwlLogo() {
  return <svg className="owl-logo" viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M7 17 5 5l13 7a26 26 0 0 1 12 0l13-7-2 12c3 4 4 8 3 13-2 10-10 15-20 15S6 40 4 30c-1-5 0-9 3-13Z" fill="#1675F8"/><path d="M9 22c0-6 8-10 15-3 7-7 15-3 15 3v5c0 8-9 12-15 7-6 5-15 1-15-7v-5Z" fill="white"/><circle cx="16.5" cy="24" r="4.5" fill="#143461"/><circle cx="31.5" cy="24" r="4.5" fill="#143461"/><circle cx="18" cy="22.5" r="1.4" fill="white"/><circle cx="33" cy="22.5" r="1.4" fill="white"/><path d="m20 30 4 6 4-6h-8Z" fill="#FFBC48"/></svg>
}
export function UiIcon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    edit: <><path d="M12 5H5v14h14v-7"/><path d="m10 14 1-4L18 3l3 3-7 7-4 1Z"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    shield: <><path d="m12 3 8 4v5c0 4-4 7-8 9-4-2-8-5-8-9V7l8-4Z"/><path d="m8 12 3 3 5-6"/></>,
    chat: <path d="M20 12a8 8 0 0 1-8 8H4l2-5a8 8 0 1 1 14-3Z"/>,
    folder: <path d="M3 6h7l2 3h9v11H3V6Z"/>,
    upload: <><path d="M7 17H5a4 4 0 0 1-1-8 7 7 0 0 1 13-2 5 5 0 0 1 2 10h-2"/><path d="M12 21V10m-4 4 4-4 4 4"/></>,
    file: <><path d="M5 3h10l4 4v14H5V3Z"/><path d="M14 3v5h5M9 12h6m-6 4h6"/></>,
    spark: <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    download: <><path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    chevron: <path d="m9 6 6 6-6 6"/>,
  }
  return <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.file}</svg>
}
