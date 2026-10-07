import { useEffect, useRef } from "react";

import { featureName, primaryMeasure } from "../format";
import type { Feature } from "../types";
import { MeasurementBadge } from "./StatusBadge";

interface Props {
  features: Feature[];
  total: number;
  selected: number | null;
  onSelect: (index: number) => void;
}

export function FeatureTable({ features, total, selected, onSelect }: Props) {
  const selectedRow = useRef<HTMLTableRowElement>(null);

  useEffect(() => {
    selectedRow.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  return (
    <section className="panel" aria-label="Features">
      <h2>Features</h2>
      {total > features.length && (
        <p className="muted">
          Showing the first {features.length} of {total} features.
        </p>
      )}
      <div className="table-scroll">
        <table className="feature-table">
          <thead>
            <tr>
              <th scope="col">Feature</th>
              <th scope="col">Status</th>
              <th scope="col" className="numeric">
                Area / length
              </th>
            </tr>
          </thead>
          <tbody>
            {features.map((feature) => {
              const isSelected = feature.feature_index === selected;
              return (
                <tr
                  key={feature.feature_index}
                  ref={isSelected ? selectedRow : undefined}
                  className={isSelected ? "selected" : undefined}
                  tabIndex={0}
                  onClick={() => onSelect(feature.feature_index)}
                  onKeyDown={(event) => event.key === "Enter" && onSelect(feature.feature_index)}
                >
                  <td>
                    <span className="cell-main">{featureName(feature)}</span>
                    <span className="cell-sub">
                      #{feature.feature_index} · {feature.geometry_type ?? "no geometry"}
                    </span>
                  </td>
                  <td>
                    <MeasurementBadge status={feature.measurement.status} />
                  </td>
                  <td className="numeric">{primaryMeasure(feature)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
