import { featureName, formatLength, formatSquareMetres } from "../format";
import type { Feature } from "../types";
import { MeasurementBadge } from "./StatusBadge";

function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function FeatureDetails({ feature, onClose }: { feature: Feature; onClose: () => void }) {
  const { measurement } = feature;
  const rows: [string, string][] = [
    ["Layer", feature.layer],
    ["Geometry", feature.geometry_type ?? "—"],
  ];
  if (measurement.area_m2 != null) rows.push(["Area", formatSquareMetres(measurement.area_m2)]);
  if (measurement.perimeter_m != null) rows.push(["Perimeter", formatLength(measurement.perimeter_m)]);
  if (measurement.length_m != null) rows.push(["Length", formatLength(measurement.length_m)]);
  if (measurement.measurement_crs) rows.push(["Measured in", measurement.measurement_crs]);

  const properties = Object.entries(feature.properties).filter(([key]) => key !== "name");

  return (
    <section className="panel feature-details" aria-label="Selected feature">
      <div className="panel-heading">
        <h2>{featureName(feature)}</h2>
        <button type="button" className="link-button" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      <MeasurementBadge status={measurement.status} />
      {measurement.message && <p className="muted">{measurement.message}</p>}
      <dl className="details">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {properties.length > 0 && (
        <>
          <span className="eyebrow">Properties</span>
          <dl className="details">
            {properties.map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{display(value)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}
