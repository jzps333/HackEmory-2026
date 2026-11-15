export function DeviceStatusBar() {
  return (
    <div className="device-status" aria-hidden="true">
      <span>9:41</span>
      <span className="device-status-icons">
        <svg viewBox="0 0 18 13" fill="none">
          <path d="M1 12V9.5h2V12m2 0V7h2v5m2 0V4.5h2V12m2 0V1h2v11" />
        </svg>
        <svg viewBox="0 0 16 13" fill="none">
          <path d="M1 4.5a10 10 0 0 1 14 0L8 12 1 4.5Z" />
        </svg>
        <svg viewBox="0 0 20 12" fill="none">
          <rect x="1" y="1" width="16" height="10" rx="2" />
          <path d="M18 4v4" />
          <rect x="3" y="3" width="11" height="6" rx="1" className="battery-level" />
        </svg>
      </span>
    </div>
  );
}
