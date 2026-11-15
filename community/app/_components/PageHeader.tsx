import { RefreshCw } from "lucide-react";

type Props = {
  title: string;
  subtitle?: string;
  checked?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  children?: React.ReactNode;
};

export default function PageHeader({ title, subtitle, checked, onRefresh, refreshing, children }: Props) {
  return (
    <div className="page-header">
      <div className="page-heading">
        <h1 className="page-title">{title}</h1>
        {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
        {children}
      </div>
      {checked !== undefined ? (
        <div className="checked">
          <span>{checked ? `Checked ${checked}` : "Checking…"}</span>
          <button
            type="button"
            className={`icon-btn small${refreshing ? " spinning" : ""}`}
            aria-label="Refresh"
            onClick={onRefresh}
            disabled={refreshing}
          >
            <RefreshCw size={14} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
