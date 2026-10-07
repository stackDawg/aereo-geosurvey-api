import type { Feature as GeoJSONFeature, Geometry } from "geojson";

import { formatArea } from "../format";
import { AREA_RAMP, LINE_COLOR, NOT_MEASURED_COLOR, POINT_COLOR } from "../theme";
import type { MapProperties } from "./MapView";

interface Props {
  areaRange: { min: number; max: number } | null;
  mapFeatures: GeoJSONFeature<Geometry, MapProperties>[];
}

export function Legend({ areaRange, mapFeatures }: Props) {
  const has = (test: (p: MapProperties) => boolean) => mapFeatures.some((f) => test(f.properties));
  const gradient = `linear-gradient(to right, ${AREA_RAMP.join(", ")})`;

  return (
    <div className="legend" role="group" aria-label="Map legend">
      {areaRange && (
        <div className="legend-ramp">
          <span className="legend-title">Polygon area</span>
          <span className="legend-bar" style={{ background: gradient }} />
          <span className="legend-scale">
            <span>{formatArea(areaRange.min)}</span>
            <span>{formatArea(areaRange.max)}</span>
          </span>
        </div>
      )}
      {has((p) => p.kind === "line" && p.measured) && (
        <span className="legend-item">
          <span className="swatch swatch-line" style={{ background: LINE_COLOR }} />
          Line (length)
        </span>
      )}
      {has((p) => p.kind === "point") && (
        <span className="legend-item">
          <span className="swatch swatch-point" style={{ background: POINT_COLOR }} />
          Point (not measured)
        </span>
      )}
      {has((p) => p.kind !== "point" && !p.measured) && (
        <span className="legend-item">
          <span className="swatch" style={{ background: NOT_MEASURED_COLOR }} />
          Measurement failed
        </span>
      )}
    </div>
  );
}
