import type { FileStatus, MeasurementStatus } from "../types";

type Tone = "good" | "warning" | "critical" | "muted";

interface BadgeSpec {
  label: string;
  icon: string;
  tone: Tone;
}

// Status is never conveyed by colour alone: every badge has an icon and a label.
const MEASUREMENT: Record<MeasurementStatus, BadgeSpec> = {
  MEASURED: { label: "Measured", icon: "✓", tone: "good" },
  NOT_APPLICABLE: { label: "Not applicable", icon: "–", tone: "muted" },
  UNSUPPORTED: { label: "Unsupported", icon: "!", tone: "warning" },
  NO_GEOMETRY: { label: "No geometry", icon: "∅", tone: "muted" },
  FAILED: { label: "Failed", icon: "✕", tone: "critical" },
};

const FILE: Record<FileStatus, BadgeSpec> = {
  PENDING: { label: "Pending", icon: "…", tone: "muted" },
  PROCESSING: { label: "Processing", icon: "⟳", tone: "muted" },
  COMPLETED: { label: "Completed", icon: "✓", tone: "good" },
  FAILED: { label: "Failed", icon: "✕", tone: "critical" },
};

function Badge({ spec }: { spec: BadgeSpec }) {
  return (
    <span className={`badge tone-${spec.tone}`}>
      <span className="badge-icon" aria-hidden="true">
        {spec.icon}
      </span>
      {spec.label}
    </span>
  );
}

export const MeasurementBadge = ({ status }: { status: MeasurementStatus }) => (
  <Badge spec={MEASUREMENT[status]} />
);

export const FileBadge = ({ status }: { status: FileStatus }) => <Badge spec={FILE[status]} />;
