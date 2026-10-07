import type {
  Feature as GeoJSONFeature,
  Geometry,
  MultiLineString,
  MultiPolygon,
  Polygon,
  Position,
} from "geojson";
import maplibregl, {
  type ExpressionSpecification,
  type FilterSpecification,
  type GeoJSONSource,
  type LngLatBoundsLike,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";

import { featureName, primaryMeasure } from "../format";
import {
  AREA_OUTLINE,
  AREA_RAMP,
  HALO_COLOR,
  LINE_COLOR,
  NOT_MEASURED_COLOR,
  POINT_COLOR,
  SELECTED_COLOR,
} from "../theme";
import type { Feature } from "../types";
import { Legend } from "./Legend";

// "outline" is a polygon's rings drawn as lines (see toMapFeatures).
type Kind = "polygon" | "outline" | "line" | "point";

// MapLibre needs flat properties; the full feature is looked up by index when needed.
interface MapProperties {
  feature_index: number;
  kind: Kind;
  measured: boolean;
  area_m2?: number;
}

export interface FocusRequest {
  index: number;
  nonce: number;
}

interface Props {
  features: Feature[];
  selected: number | null;
  focus: FocusRequest | null;
  onSelect: (index: number | null) => void;
  emptyMessage: string | null;
}

const SOURCE = "features";
const INTERACTIVE_LAYERS = ["points", "lines", "area-outline", "area-fill"];
const HIT_RADIUS = 6; // px: hit targets are larger than thin lines and small points

function kindOf(type: Geometry["type"]): Kind | null {
  switch (type) {
    case "Polygon":
    case "MultiPolygon":
      return "polygon";
    case "LineString":
    case "MultiLineString":
      return "line";
    case "Point":
    case "MultiPoint":
      return "point";
    default:
      return null;
  }
}

function ringsAsLines(geometry: Polygon | MultiPolygon): MultiLineString {
  const rings = geometry.type === "Polygon" ? geometry.coordinates : geometry.coordinates.flat();
  return { type: "MultiLineString", coordinates: rings };
}

/** Map features for one API feature. GeometryCollections are split into their parts. */
function toMapFeatures(feature: Feature): GeoJSONFeature<Geometry, MapProperties>[] {
  // Only features the API could reproject to WGS 84 can be drawn.
  if (!feature.geometry || feature.crs !== "EPSG:4326") return [];
  const parts =
    feature.geometry.type === "GeometryCollection" ? feature.geometry.geometries : [feature.geometry];
  return parts.flatMap((geometry): GeoJSONFeature<Geometry, MapProperties>[] => {
    const kind = kindOf(geometry.type);
    if (!kind) return [];
    const { status, area_m2 } = feature.measurement;
    const properties: MapProperties = {
      feature_index: feature.feature_index,
      kind,
      measured: status === "MEASURED",
    };
    if (area_m2 != null) properties.area_m2 = area_m2;
    const mapFeature = { type: "Feature" as const, id: feature.feature_index, geometry, properties };
    if (geometry.type !== "Polygon" && geometry.type !== "MultiPolygon") return [mapFeature];
    // MapLibre fills self-intersecting rings (e.g. a "bow tie") unreliably: not at all at some
    // zoom levels, as a fragment at others. Drawing the rings as lines keeps such shapes visible.
    const outline = { ...mapFeature, geometry: ringsAsLines(geometry) };
    return [mapFeature, { ...outline, properties: { ...properties, kind: "outline" } }];
  });
}

function positions(geometry: Geometry): Position[] {
  switch (geometry.type) {
    case "Point":
      return [geometry.coordinates];
    case "MultiPoint":
    case "LineString":
      return geometry.coordinates;
    case "MultiLineString":
    case "Polygon":
      return geometry.coordinates.flat();
    case "MultiPolygon":
      return geometry.coordinates.flat(2);
    case "GeometryCollection":
      return geometry.geometries.flatMap(positions);
  }
}

function boundsOf(geometries: Geometry[]): LngLatBoundsLike | null {
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of geometries.flatMap(positions)) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return Number.isFinite(minX) ? [[minX, minY], [maxX, maxY]] : null;
}

/** Sequential fill by area; polygons without an area (not measured) are grey. */
function areaColor(min: number, max: number): ExpressionSpecification {
  const stops = AREA_RAMP.flatMap((color, i) => [
    min + ((max - min) * i) / (AREA_RAMP.length - 1),
    color,
  ]);
  const ramp =
    max > min
      ? (["interpolate", ["linear"], ["get", "area_m2"], ...stops] as ExpressionSpecification)
      : AREA_RAMP[3];
  // area_m2 is only set on features that have an area.
  return ["case", ["has", "area_m2"], ramp, NOT_MEASURED_COLOR];
}

const hovered = (whenHovered: number, otherwise: number): ExpressionSpecification => [
  "case",
  ["boolean", ["feature-state", "hover"], false],
  whenHovered,
  otherwise,
];

/** The whole map style, inline: an OpenStreetMap basemap plus the feature layers. Declaring the
 * feature layers up front (rather than on "load") means features can be drawn before every
 * basemap tile has arrived. */
function buildStyle(): StyleSpecification {
  const kind = (k: Kind): FilterSpecification => ["==", ["get", "kind"], k];
  const none: FilterSpecification = ["==", ["get", "feature_index"], -1];
  const measuredOr = (color: string): ExpressionSpecification => [
    "case",
    ["get", "measured"],
    color,
    NOT_MEASURED_COLOR,
  ];

  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
      [SOURCE]: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
    },
    layers: [
      { id: "osm", type: "raster", source: "osm" },
      {
        id: "area-fill",
        type: "fill",
        source: SOURCE,
        filter: kind("polygon"),
        paint: { "fill-color": NOT_MEASURED_COLOR, "fill-opacity": hovered(0.85, 0.6) },
      },
      {
        id: "area-outline",
        type: "line",
        source: SOURCE,
        filter: kind("outline"),
        paint: { "line-color": AREA_OUTLINE, "line-width": 1.5 },
      },
      {
        id: "lines",
        type: "line",
        source: SOURCE,
        filter: kind("line"),
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": measuredOr(LINE_COLOR), "line-width": hovered(5, 3) },
      },
      {
        id: "points",
        type: "circle",
        source: SOURCE,
        filter: kind("point"),
        paint: {
          "circle-radius": hovered(8, 6),
          "circle-color": POINT_COLOR,
          "circle-stroke-width": 2,
          "circle-stroke-color": HALO_COLOR,
        },
      },
      {
        id: "selected-halo",
        type: "line",
        source: SOURCE,
        filter: none,
        paint: { "line-color": HALO_COLOR, "line-width": 6 },
      },
      {
        id: "selected-line",
        type: "line",
        source: SOURCE,
        filter: none,
        paint: { "line-color": SELECTED_COLOR, "line-width": 2.5 },
      },
      {
        id: "selected-point",
        type: "circle",
        source: SOURCE,
        filter: none,
        paint: {
          "circle-radius": 10,
          "circle-opacity": 0,
          "circle-stroke-width": 3,
          "circle-stroke-color": SELECTED_COLOR,
        },
      },
    ],
  };
}

export function MapView({ features, selected, focus, onSelect, emptyMessage }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; index: number } | null>(null);

  const byIndex = useMemo(() => new Map(features.map((f) => [f.feature_index, f])), [features]);
  const mapFeatures = useMemo(() => features.flatMap(toMapFeatures), [features]);
  const areas = mapFeatures.flatMap((f) => (f.properties.area_m2 != null ? [f.properties.area_m2] : []));
  const areaRange = areas.length ? { min: Math.min(...areas), max: Math.max(...areas) } : null;

  // Event handlers are registered once, so they read the latest callback through a ref.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const map = new maplibregl.Map({
      container: container.current!,
      style: buildStyle(),
      center: [78.9, 21.5],
      zoom: 3.6,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    // The style is inline, so it is usable as soon as it is parsed - no need to wait for tiles.
    map.once("styledata", () => setReady(true));

    let hoveredId: number | null = null;
    const setHovered = (id: number | null) => {
      if (hoveredId === id) return;
      if (hoveredId !== null) map.setFeatureState({ source: SOURCE, id: hoveredId }, { hover: false });
      if (id !== null) map.setFeatureState({ source: SOURCE, id }, { hover: true });
      hoveredId = id;
    };
    const hitAt = (point: maplibregl.Point) => {
      if (!map.getLayer("points")) return null;
      const box: [maplibregl.PointLike, maplibregl.PointLike] = [
        [point.x - HIT_RADIUS, point.y - HIT_RADIUS],
        [point.x + HIT_RADIUS, point.y + HIT_RADIUS],
      ];
      // Topmost layer first: points, then lines, then polygons.
      const hit = map.queryRenderedFeatures(box, { layers: INTERACTIVE_LAYERS })[0];
      return hit ? Number(hit.id) : null;
    };

    map.on("mousemove", (event) => {
      const index = hitAt(event.point);
      setHovered(index);
      map.getCanvas().style.cursor = index === null ? "" : "pointer";
      setTooltip(index === null ? null : { x: event.point.x, y: event.point.y, index });
    });
    map.on("mouseout", () => {
      setHovered(null);
      setTooltip(null);
    });
    map.on("click", (event) => onSelectRef.current(hitAt(event.point)));

    mapRef.current = map;
    return () => map.remove();
  }, []);

  // New data: replace the source, rescale the area ramp and zoom to the features.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource(SOURCE) as GeoJSONSource).setData({ type: "FeatureCollection", features: mapFeatures });
    map.setPaintProperty(
      "area-fill",
      "fill-color",
      areaColor(areaRange?.min ?? 0, areaRange?.max ?? 0),
    );
    const bounds = boundsOf(mapFeatures.map((f) => f.geometry));
    if (bounds) map.fitBounds(bounds, { padding: 60, maxZoom: 17, duration: 800 });
  }, [mapFeatures, ready]); // areaRange is derived from mapFeatures

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const isSelected: FilterSpecification = ["==", ["get", "feature_index"], selected ?? -1];
    const isPoint: FilterSpecification = ["==", ["get", "kind"], "point"];
    // A circle layer would also draw a circle on every vertex of a polygon or line.
    map.setFilter("selected-point", ["all", isSelected, isPoint]);
    map.setFilter("selected-halo", ["all", isSelected, ["!", isPoint]]);
    map.setFilter("selected-line", ["all", isSelected, ["!", isPoint]]);
  }, [selected, ready]);

  // Zoom to a feature picked from the table (not to ones clicked on the map).
  useEffect(() => {
    const map = mapRef.current;
    const geometry = focus ? byIndex.get(focus.index)?.geometry : null;
    if (!map || !ready || !geometry) return;
    const bounds = boundsOf([geometry]);
    if (bounds) map.fitBounds(bounds, { padding: 120, maxZoom: 18, duration: 600 });
  }, [focus, byIndex, ready]);

  const tooltipFeature = tooltip ? byIndex.get(tooltip.index) : undefined;

  return (
    <div className="map-shell">
      <div ref={container} className="map" aria-label="Map of the selected file's features" />
      {tooltip && tooltipFeature && (
        <div className="map-tooltip" style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}>
          <strong>{featureName(tooltipFeature)}</strong>
          <span>
            {tooltipFeature.geometry_type} · {primaryMeasure(tooltipFeature)}
          </span>
        </div>
      )}
      {mapFeatures.length > 0 && <Legend areaRange={areaRange} mapFeatures={mapFeatures} />}
      {emptyMessage && <div className="map-empty">{emptyMessage}</div>}
    </div>
  );
}

export type { MapProperties };
