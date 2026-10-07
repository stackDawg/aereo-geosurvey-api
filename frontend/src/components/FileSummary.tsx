import { formatArea, formatLength, formatSquareMetres } from "../format";
import type { GeoFile, Summary } from "../types";
import { FileBadge } from "./StatusBadge";

interface Props {
  file: GeoFile;
  summary: Summary | null;
  onDelete: () => void;
}

const hasType = (summary: Summary, match: string) =>
  Object.keys(summary.by_geometry_type).some(
    (type) => type.includes(match) || type === "GeometryCollection",
  );

export function FileSummary({ file, summary, onDelete }: Props) {
  const busy = file.status === "PENDING" || file.status === "PROCESSING";
  const hasPolygons = summary !== null && hasType(summary, "Polygon");
  const hasLines = summary !== null && hasType(summary, "LineString");

  return (
    <section className="panel" aria-label="Selected file">
      <div className="panel-heading">
        <h2 title={file.filename}>{file.filename}</h2>
        <FileBadge status={file.status} />
      </div>
      <p className="muted">
        CRS {file.crs ?? "unknown"}
        {file.layers.length > 1 && ` · ${file.layers.length} layers`}
        {file.source_crs && ` · source_crs ${file.source_crs}`}
      </p>

      {busy && <p className="muted">Reading and measuring features…</p>}
      {file.error && <p className="notice critical">✕ {file.error}</p>}

      {summary && (
        <div className="stats">
          <div className="stat">
            <span className="stat-label">Total area</span>
            <span className="stat-value">
              {hasPolygons ? formatArea(summary.total_area_m2) : "—"}
            </span>
            <span className="stat-sub">
              {hasPolygons ? formatSquareMetres(summary.total_area_m2) : "no polygons"}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Total length</span>
            <span className="stat-value">
              {hasLines ? formatLength(summary.total_length_m) : "—"}
            </span>
            {!hasLines && <span className="stat-sub">no lines</span>}
          </div>
          <div className="stat">
            <span className="stat-label">Measured</span>
            <span className="stat-value">
              {summary.measured_count} / {summary.feature_count}
            </span>
            <span className="stat-sub">features</span>
          </div>
        </div>
      )}

      {file.warnings.length > 0 && (
        <ul className="notices">
          {file.warnings.map((warning) => (
            <li key={warning} className="notice warning">
              ! {warning}
            </li>
          ))}
        </ul>
      )}

      <button type="button" className="link-button danger" disabled={busy} onClick={onDelete}>
        Delete file
      </button>
    </section>
  );
}
