export function Logo({ compact }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2 font-bold tracking-tight">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="9" className="fill-primary" />
        <circle cx="16" cy="14" r="7" fill="none" stroke="white" strokeWidth="2.2" strokeDasharray="3 2.4" />
        <path d="M16 8.5a5.5 5.5 0 0 1 5.5 5.5c0 4.2-5.5 9.5-5.5 9.5s-5.5-5.3-5.5-9.5A5.5 5.5 0 0 1 16 8.5Z" fill="white" />
        <circle cx="16" cy="14" r="2" className="fill-primary" />
      </svg>
      {!compact && <span className="text-[17px]">GeoAttend</span>}
    </span>
  );
}
