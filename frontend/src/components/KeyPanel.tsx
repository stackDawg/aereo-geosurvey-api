import { useState } from "react";

import type { ApiClient } from "../types";

interface Props {
  client: ApiClient | null;
  apiKey: string | null;
  onUseKey: (key: string) => void;
  onNewKey: () => void;
}

export function KeyPanel({ client, apiKey, onUseKey, onNewKey }: Props) {
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!apiKey) return;
    try {
      await navigator.clipboard.writeText(apiKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (e.g. insecure context): the key is still visible on hover
    }
  };

  if (client && apiKey) {
    return (
      <section className="panel key-panel" aria-label="API key">
        <div>
          <span className="eyebrow">API key</span>
          <code title={apiKey}>{client.key_prefix}…</code>
          <span className="muted"> · {client.name}</span>
        </div>
        <div className="key-actions">
          <button type="button" className="link-button" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button type="button" className="link-button" onClick={onNewKey}>
            New key
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="panel" aria-label="API key">
      <span className="eyebrow">API key</span>
      <p className="muted">Paste an API key to see your files.</p>
      <form
        className="key-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim()) onUseKey(draft.trim());
        }}
      >
        <input
          aria-label="API key"
          placeholder="gm_…"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit">Use key</button>
      </form>
    </section>
  );
}
