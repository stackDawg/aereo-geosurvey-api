import { formatBytes, formatTime } from "../format";
import type { GeoFile } from "../types";
import { FileBadge } from "./StatusBadge";

interface Props {
  files: GeoFile[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function FileList({ files, selectedId, onSelect }: Props) {
  return (
    <section className="panel" aria-label="Your files">
      <h2>Your files</h2>
      {files.length === 0 ? (
        <p className="muted">No files yet.</p>
      ) : (
        <ul className="file-list">
          {files.map((file) => (
            <li key={file.id}>
              <button
                type="button"
                className={`file-item${file.id === selectedId ? " selected" : ""}`}
                aria-pressed={file.id === selectedId}
                onClick={() => onSelect(file.id)}
              >
                <span className="file-name">{file.filename}</span>
                <span className="file-meta">
                  {file.file_type} · {formatBytes(file.size_bytes)} · {formatTime(file.created_at)}
                </span>
                <FileBadge status={file.status} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
