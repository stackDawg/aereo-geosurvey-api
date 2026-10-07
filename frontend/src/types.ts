import type { Geometry } from "geojson";

// Mirrors the API's response models (app/schemas.py).

export type FileStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export type MeasurementStatus =
  | "MEASURED"
  | "NOT_APPLICABLE"
  | "UNSUPPORTED"
  | "NO_GEOMETRY"
  | "FAILED";

export interface Page<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface Layer {
  name: string;
  crs: string | null;
  feature_count: number;
}

export interface GeoFile {
  id: string;
  filename: string;
  file_type: "SHAPEFILE" | "KML" | "KMZ";
  size_bytes: number;
  status: FileStatus;
  crs: string | null;
  source_crs: string | null;
  feature_count: number | null;
  layers: Layer[];
  warnings: string[];
  error: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface Measurement {
  status: MeasurementStatus;
  area_m2: number | null;
  perimeter_m: number | null;
  length_m: number | null;
  measurement_crs: string | null;
  message: string | null;
}

export interface Feature {
  feature_index: number;
  feature_id: string | null;
  layer: string;
  geometry_type: string | null;
  crs: string | null;
  geometry: Geometry | null;
  properties: Record<string, unknown>;
  measurement: Measurement;
}

export interface Summary {
  feature_count: number;
  measured_count: number;
  total_area_m2: number;
  total_length_m: number;
  by_status: Partial<Record<MeasurementStatus, number>>;
  by_geometry_type: Record<string, number>;
}

export interface MeasurementList extends Page<unknown> {
  file_id: string;
  summary: Summary;
}

export interface ApiClient {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
}

export interface ApiKeyCreated extends ApiClient {
  api_key: string;
}
