import { useRef, useState } from "react";

import { SAMPLES, loadSample, type Sample } from "../samples";

interface Props {
  disabled: boolean;
  onUpload: (file: File, sourceCrs: string) => Promise<void>;
}

const ACCEPT = ".zip,.kml,.kmz";

export function UploadPanel({ disabled, onUpload }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceCrs, setSourceCrs] = useState("");
  const [dragging, setDragging] = useState(false);

  const submit = async (chosen: File | null) => {
    if (!chosen) return;
    await onUpload(chosen, sourceCrs);
    setFile(null);
    if (input.current) input.current.value = "";
  };

  const trySample = async (sample: Sample) => onUpload(await loadSample(sample), "");

  return (
    <section className="panel" aria-label="Upload">
      <h2>Upload a file</h2>
      <label
        className={`dropzone${dragging ? " dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          setFile(event.dataTransfer.files[0] ?? null);
        }}
      >
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span>{file ? file.name : "Drop a .zip Shapefile, .kml or .kmz here, or click to browse"}</span>
      </label>
      <div className="upload-row">
        <input
          aria-label="Source CRS (optional)"
          placeholder="Source CRS, only if the file has none (e.g. EPSG:32643)"
          value={sourceCrs}
          onChange={(event) => setSourceCrs(event.target.value)}
        />
        <button type="button" disabled={disabled || !file} onClick={() => submit(file)}>
          Upload
        </button>
      </div>
      <div className="samples">
        <span className="eyebrow">Or try a sample</span>
        <div className="sample-buttons">
          {SAMPLES.map((sample) => (
            <button
              key={sample.filename}
              type="button"
              className="sample"
              disabled={disabled}
              onClick={() => trySample(sample)}
            >
              <strong>{sample.label}</strong>
              <span>{sample.detail}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
