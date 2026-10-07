import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "./api";
import { FeatureDetails } from "./components/FeatureDetails";
import { FeatureTable } from "./components/FeatureTable";
import { FileList } from "./components/FileList";
import { FileSummary } from "./components/FileSummary";
import { KeyPanel } from "./components/KeyPanel";
import { type FocusRequest, MapView } from "./components/MapView";
import { UploadPanel } from "./components/UploadPanel";
import type { ApiClient, Feature, GeoFile, Summary } from "./types";

const KEY_STORAGE = "geo-measure.api-key";
const POLL_MS = 1500;

function storedKey(): string | null {
  try {
    return localStorage.getItem(KEY_STORAGE);
  } catch {
    return null;
  }
}

function storeKey(key: string | null) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    // storage unavailable (private mode): the key lasts for this page view only
  }
}

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

export default function App() {
  const [apiKey, setApiKey] = useState<string | null>(storedKey);
  const [client, setClient] = useState<ApiClient | null>(null);
  const [keyRequired, setKeyRequired] = useState(false);
  const [files, setFiles] = useState<GeoFile[]>([]);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [selectedFeature, setSelectedFeature] = useState<number | null>(null);
  const [focus, setFocus] = useState<FocusRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const switchKey = useCallback((key: string | null) => {
    storeKey(key);
    setApiKey(key);
    setClient(null);
    setFiles([]);
    setSelectedFileId(null);
  }, []);

  // Make sure we hold a valid key. A stored key can go stale (e.g. the demo database was
  // reset), in which case a new one is created automatically.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (apiKey) {
        try {
          const me = await api.me(apiKey);
          if (!cancelled) setClient(me);
          return;
        } catch (err) {
          if (!(err instanceof ApiError && err.status === 401)) {
            if (!cancelled) setError(message(err));
            return;
          }
        }
      }
      try {
        const created = await api.createKey("Map viewer");
        if (cancelled) return;
        storeKey(created.api_key);
        setApiKey(created.api_key);
        setClient(created);
      } catch (err) {
        // Self-service keys are disabled on this server: ask for one.
        if (!cancelled) setKeyRequired(err instanceof ApiError && err.status === 403);
        if (!cancelled && !(err instanceof ApiError && err.status === 403)) setError(message(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiKey]);

  const refreshFiles = useCallback(async () => {
    if (!apiKey || !client) return;
    try {
      setFiles((await api.listFiles(apiKey)).items);
    } catch (err) {
      setError(message(err));
    }
  }, [apiKey, client]);

  useEffect(() => {
    refreshFiles();
  }, [refreshFiles]);

  // Poll while any file is still being processed.
  const inFlight = files.some((f) => f.status === "PENDING" || f.status === "PROCESSING");
  useEffect(() => {
    if (!inFlight) return;
    const timer = setInterval(refreshFiles, POLL_MS);
    return () => clearInterval(timer);
  }, [inFlight, refreshFiles]);

  const selectedFile = files.find((f) => f.id === selectedFileId) ?? null;
  const selectedStatus = selectedFile?.status;

  // Load features and totals once the selected file has been processed.
  useEffect(() => {
    setFeatures([]);
    setSummary(null);
    setSelectedFeature(null);
    if (!apiKey || !selectedFileId || selectedStatus !== "COMPLETED") return;
    let cancelled = false;
    Promise.all([api.features(apiKey, selectedFileId), api.summary(apiKey, selectedFileId)])
      .then(([page, measurements]) => {
        if (cancelled) return;
        setFeatures(page.items);
        setSummary(measurements.summary);
      })
      .catch((err) => !cancelled && setError(message(err)));
    return () => {
      cancelled = true;
    };
  }, [apiKey, selectedFileId, selectedStatus]);

  const upload = async (file: File, sourceCrs: string) => {
    if (!apiKey) return;
    setUploading(true);
    setError(null);
    try {
      const created = await api.upload(apiKey, file, sourceCrs);
      setFiles((current) => [created, ...current]);
      setSelectedFileId(created.id);
    } catch (err) {
      setError(message(err));
    } finally {
      setUploading(false);
    }
  };

  const deleteSelected = async () => {
    if (!apiKey || !selectedFileId) return;
    try {
      await api.deleteFile(apiKey, selectedFileId);
      setSelectedFileId(null);
      await refreshFiles();
    } catch (err) {
      setError(message(err));
    }
  };

  const selectFromTable = (index: number) => {
    setSelectedFeature(index);
    setFocus({ index, nonce: Date.now() });
  };

  const feature = features.find((f) => f.feature_index === selectedFeature) ?? null;

  let emptyMessage: string | null = null;
  if (!selectedFile) emptyMessage = "Upload a file or try a sample to see its features here.";
  else if (selectedFile.status === "PENDING" || selectedFile.status === "PROCESSING")
    emptyMessage = "Processing…";
  else if (selectedFile.status === "FAILED") emptyMessage = "This file could not be processed.";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true" />
          <div>
            <h1>Geo Measure</h1>
            <p>Area and length of every feature in a Shapefile or KML</p>
          </div>
        </div>
        <nav>
          <a href="/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
        </nav>
      </header>

      <aside className="sidebar">
        {error && (
          <div className="notice critical" role="alert">
            ✕ {error}
            <button type="button" className="link-button" onClick={() => setError(null)}>
              Dismiss
            </button>
          </div>
        )}
        {(client || keyRequired) && (
          <KeyPanel
            client={client}
            apiKey={apiKey}
            onUseKey={switchKey}
            onNewKey={() => switchKey(null)}
          />
        )}
        <UploadPanel disabled={!client || uploading} onUpload={upload} />
        <FileList files={files} selectedId={selectedFileId} onSelect={setSelectedFileId} />
        {selectedFile && (
          <FileSummary file={selectedFile} summary={summary} onDelete={deleteSelected} />
        )}
        {feature && <FeatureDetails feature={feature} onClose={() => setSelectedFeature(null)} />}
        {features.length > 0 && (
          <FeatureTable
            features={features}
            total={selectedFile?.feature_count ?? features.length}
            selected={selectedFeature}
            onSelect={selectFromTable}
          />
        )}
      </aside>

      <main className="map-area">
        <MapView
          features={features}
          selected={selectedFeature}
          focus={focus}
          onSelect={setSelectedFeature}
          emptyMessage={emptyMessage}
        />
      </main>
    </div>
  );
}
