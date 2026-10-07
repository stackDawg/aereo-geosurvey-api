import type { Feature } from "./types";

const number = (fractionDigits: number) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: fractionDigits });

export function formatArea(m2: number | null | undefined): string {
  if (m2 == null) return "—";
  if (m2 >= 1_000_000) return `${number(2).format(m2 / 1_000_000)} km²`;
  if (m2 >= 10_000) return `${number(2).format(m2 / 10_000)} ha`;
  return `${number(0).format(m2)} m²`;
}

export function formatSquareMetres(m2: number | null | undefined): string {
  return m2 == null ? "—" : `${number(1).format(m2)} m²`;
}

export function formatLength(m: number | null | undefined): string {
  if (m == null) return "—";
  if (m >= 1000) return `${number(2).format(m / 1000)} km`;
  return `${number(1).format(m)} m`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${number(1).format(bytes / 1024)} KB`;
  return `${number(1).format(bytes / 1024 / 1024)} MB`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function featureName(feature: Feature): string {
  const name = feature.properties.name;
  if (typeof name === "string" && name.trim()) return name;
  // KML ids are usually meaningful ("plot-101"); Shapefile ids are just record numbers.
  const id = feature.feature_id;
  if (id && !/^\d+$/.test(id)) return id;
  return `${feature.layer} #${id ?? feature.feature_index}`;
}

/** The headline measurement of a feature: area for polygons, length for lines. */
export function primaryMeasure(feature: Feature): string {
  const { area_m2, length_m } = feature.measurement;
  if (area_m2 != null) return formatArea(area_m2);
  if (length_m != null) return formatLength(length_m);
  return "—";
}
