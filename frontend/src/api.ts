import type {
  ApiClient,
  ApiKeyCreated,
  Feature,
  GeoFile,
  MeasurementList,
  Page,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// Features are drawn on a web map, so ask the API to reproject them to WGS 84.
const MAP_CRS = "EPSG:4326";
export const MAX_FEATURES = 10_000;

async function request<T>(path: string, apiKey: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (apiKey) headers.set("X-API-Key", apiKey);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const api = {
  createKey: (name: string) =>
    request<ApiKeyCreated>("/api/auth/keys/", null, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  me: (apiKey: string) => request<ApiClient>("/api/auth/me/", apiKey),

  listFiles: (apiKey: string) => request<Page<GeoFile>>("/api/files/?limit=50", apiKey),

  upload: (apiKey: string, file: File, sourceCrs: string) => {
    const form = new FormData();
    form.append("file", file);
    if (sourceCrs.trim()) form.append("source_crs", sourceCrs.trim());
    return request<GeoFile>("/api/files/", apiKey, { method: "POST", body: form });
  },

  features: (apiKey: string, fileId: string) =>
    request<Page<Feature>>(
      `/api/files/${fileId}/features/?crs=${MAP_CRS}&limit=${MAX_FEATURES}`,
      apiKey,
    ),

  // Only the summary is needed: per-feature measurements come with the features.
  summary: (apiKey: string, fileId: string) =>
    request<MeasurementList>(`/api/files/${fileId}/measurements/?limit=1`, apiKey),

  deleteFile: (apiKey: string, fileId: string) =>
    request<void>(`/api/files/${fileId}/`, apiKey, { method: "DELETE" }),
};
