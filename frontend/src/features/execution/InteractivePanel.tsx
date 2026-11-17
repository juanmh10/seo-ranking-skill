import { LoaderCircle, MessageCircle, RotateCcw, Send, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type {
  InteractiveSession,
  ModelEntry,
  SourceDocumentSummary,
  SystemPrompt,
} from "../../types/api";

type ContentMode = "RAW" | "NORMALIZED" | "BOTH";

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function InteractivePanel({
  experimentId,
  documents,
  sampleQuestion,
}: {
  experimentId: string;
  documents: SourceDocumentSummary[];
  sampleQuestion?: string;
}) {
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [prompts, setPrompts] = useState<SystemPrompt[]>([]);
  const [sessions, setSessions] = useState<InteractiveSession[]>([]);
  const [activeSession, setActiveSession] = useState<InteractiveSession | null>(null);
  const [modelId, setModelId] = useState("");
  const [promptId, setPromptId] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [contentMode, setContentMode] = useState<ContentMode>("NORMALIZED");
  const [temperature, setTemperature] = useState(0.7);
  const [topP, setTopP] = useState(0.95);
  const [maxOutputTokens, setMaxOutputTokens] = useState(2048);
  const [message, setMessage] = useState("");
  const [pendingUserContent, setPendingUserContent] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    void Promise.all([
      api.listModels(),
      api.listPrompts(),
      api.listInteractiveSessions(experimentId),
    ]).then(([availableModels, availablePrompts, existingSessions]) => {
      if (!mounted) return;
      setModels(availableModels);
      setPrompts(availablePrompts);
      setSessions(existingSessions);
      setActiveSession(existingSessions[0] ?? null);
      const preferred = availableModels.find(
        (item) => item.model_id === "gemini-3.5-flash-lite" && item.runnable,
      );
      setModelId(preferred?.model_id ?? availableModels.find((item) => item.runnable)?.model_id ?? "");
      setPromptId(availablePrompts[0]?.id ?? "");
    }).catch((caught: unknown) => {
      if (mounted) setError(caught instanceof Error ? caught.message : "Falha ao carregar o modo Interactive.");
    });
    return () => { mounted = false; };
  }, [experimentId]);

  useEffect(() => {
    setSelectedDocumentIds((current) => {
      const currentValid = current.filter((id) => documents.some((document) => document.id === id));
      if (currentValid.length) return currentValid.slice(0, 5);
      return documents
        .filter((document) => document.position !== null)
        .sort((a, b) => (a.position ?? 99) - (b.position ?? 99))
        .slice(0, 5)
        .map((document) => document.id);
    });
  }, [documents]);

  const selectedModel = models.find((model) => model.model_id === modelId);
  const selectedPrompt = prompts.find((prompt) => prompt.id === promptId);
  const canCreate = !!selectedModel?.runnable && !!selectedPrompt && selectedDocumentIds.length > 0 && !busy;
  function toggleSource(documentId: string) {
    setSelectedDocumentIds((current) => {
      if (current.includes(documentId)) return current.filter((id) => id !== documentId);
      if (current.length >= 5) return current;
      return [...current, documentId];
    });
  }

  async function createSession() {
    if (!canCreate || !selectedModel) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createInteractiveSession(experimentId, {
        model_id: modelId,
        system_prompt_id: promptId,
        source_document_ids: selectedDocumentIds,
        content_mode: contentMode,
        max_output_tokens: maxOutputTokens,
        ...(selectedModel.supports_temperature ? { temperature } : {}),
        ...(selectedModel.supports_top_p ? { top_p: topP } : {}),
      });
      setActiveSession(created);
      setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível criar a conversa.");
    } finally {
      setBusy(false);
    }
  }

  async function resetSession() {
    if (!activeSession || busy) return;
    setBusy(true);
    setError(null);
    try {
      const reset = await api.resetInteractiveSession(activeSession.id);
      setActiveSession(reset);
      setSessions((current) => [reset, ...current.filter((item) => item.id !== reset.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível abrir uma conversa nova.");
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeSession || !message.trim() || busy) return;
    const content = message.trim();
    setBusy(true);
    setError(null);
    setMessage("");
    setPendingUserContent(content);
    setStreamingText("");
    try {
      const updated = await api.streamInteractiveMessage(
        activeSession.id,
        content,
        (delta) => setStreamingText((current) => current + delta),
      );
      setActiveSession(updated);
      setSessions((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
      setPendingUserContent("");
      setStreamingText("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "O modelo não concluiu a resposta.");
      const refreshed = await api.getInteractiveSession(activeSession.id).catch(() => null);
      if (refreshed) {
        setActiveSession(refreshed);
        setSessions((current) => [refreshed, ...current.filter((item) => item.id !== refreshed.id)]);
      }
      setPendingUserContent("");
      setStreamingText("");
    } finally {
      setBusy(false);
    }
  }

  async function openSession(sessionId: string) {
    setError(null);
    try {
      const loaded = await api.getInteractiveSession(sessionId);
      setActiveSession(loaded);
      setSessions((current) => [loaded, ...current.filter((item) => item.id !== loaded.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Não foi possível abrir a conversa.");
    }
  }

  return (
    <section className="interactive-layout rounded-[1.35rem] border border-line bg-panel p-4 md:p-5">
      <div className="execution-header flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Interactive session</p>
          <h2 className="mt-2 text-lg font-semibold">Converse com um conjunto de fontes</h2>
          <p className="mt-2 text-xs leading-5 text-muted">
            Esta conversa mantém o próprio histórico. Labels e avaliações do benchmark ficam fora do contexto do modelo.
          </p>
        </div>
        {activeSession ? (
          <button type="button" className="button-secondary" disabled={busy} onClick={() => void resetSession()}>
            <RotateCcw className="size-4" /> Nova conversa
          </button>
        ) : null}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_15rem]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="field-label">Modelo</span>
              <select className="field-input" value={modelId} onChange={(event) => setModelId(event.target.value)}>
                {models.map((model) => (
                  <option key={model.model_id} value={model.model_id} disabled={!model.runnable}>
                    {model.display_name}{model.runnable ? "" : " · indisponível"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="field-label">Prompt de sistema</span>
              <select className="field-input" value={promptId} onChange={(event) => setPromptId(event.target.value)}>
                {prompts.map((prompt) => (
                  <option key={prompt.id} value={prompt.id}>{prompt.name} · v{prompt.version}</option>
                ))}
              </select>
            </label>
          </div>

          {selectedModel?.availability_note ? (
            <p className="rounded-lg border border-line bg-canvas/35 px-3 py-2 text-xs text-muted">
              {selectedModel.availability_note}
            </p>
          ) : null}

          <div className="rounded-xl border border-line bg-canvas/25 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold text-ink">Fontes selecionadas</p>
              <span className="font-mono text-[0.65rem] text-muted">{selectedDocumentIds.length}/5 · ordenação da seleção</span>
            </div>
            {!documents.length ? (
              <p className="mt-3 text-xs text-muted">Adicione fontes ao acervo para iniciar uma conversa.</p>
            ) : (
              <div className="mt-2 max-h-52 space-y-1 overflow-y-auto">
                {documents.map((document) => {
                  const checked = selectedDocumentIds.includes(document.id);
                  const disabled = !checked && selectedDocumentIds.length >= 5;
                  return (
                    <label key={document.id} className={`flex items-center gap-2 rounded-lg px-2 py-2 ${disabled ? "opacity-45" : "hover:bg-panel"}`}>
                      <input
                        type="checkbox"
                        className="size-3.5 accent-[var(--color-accent)]"
                        checked={checked}
                        disabled={disabled || busy}
                        onChange={() => toggleSource(document.id)}
                      />
                      <span className="min-w-0 flex-1 truncate text-xs font-medium">{document.filename}</span>
                      <span className="shrink-0 font-mono text-[0.58rem] text-muted">
                        {document.position ? `slot ${document.position}` : "acervo"} · {document.sha256.slice(0, 8)}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="field-label">Conteúdo enviado</span>
              <select className="field-input" value={contentMode} onChange={(event) => setContentMode(event.target.value as ContentMode)}>
                <option value="NORMALIZED">Normalizado</option>
                <option value="RAW">Original</option>
                <option value="BOTH">Original e normalizado</option>
              </select>
            </label>
            <label>
              <span className="field-label">Máximo de tokens de saída</span>
              <input className="field-input" type="number" min={1} max={65536} value={maxOutputTokens} onChange={(event) => setMaxOutputTokens(Number(event.target.value))} />
            </label>
            {selectedModel?.supports_temperature ? (
              <label>
                <span className="field-label">Temperature</span>
                <input className="field-input" type="number" min={0} max={2} step={0.1} value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} />
              </label>
            ) : null}
            {selectedModel?.supports_top_p ? (
              <label>
                <span className="field-label">Top P</span>
                <input className="field-input" type="number" min={0.01} max={1} step={0.05} value={topP} onChange={(event) => setTopP(Number(event.target.value))} />
              </label>
            ) : null}
          </div>

          {!activeSession ? (
            <div className="rounded-xl border border-dashed border-line bg-canvas/20 p-4">
              <p className="text-xs leading-5 text-muted">
                {sampleQuestion ? `Pergunta sugerida: “${sampleQuestion}” ` : "Escolha de uma a cinco fontes para começar. "}
                {selectedPrompt ? `O prompt ${selectedPrompt.name} será fixado nesta sessão.` : "Escolha um prompt de sistema."}
              </p>
              <button type="button" className="button-primary mt-3" disabled={!canCreate} onClick={() => void createSession()}>
                {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                Iniciar Interactive
              </button>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-line bg-canvas/20">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <MessageCircle className="size-4 text-accent" />
                  <span className="text-xs font-semibold">{activeSession.model_id}</span>
                  <span className="font-mono text-[0.58rem] text-muted">{activeSession.content_mode}</span>
                </div>
                <span className="font-mono text-[0.58rem] text-muted">prompt sha256:{activeSession.system_prompt_sha256.slice(0, 12)}…</span>
              </div>
              <div className="max-h-[26rem] min-h-40 space-y-3 overflow-y-auto p-3" aria-live="polite">
                {!activeSession.messages.length && !pendingUserContent ? (
                  <div className="grid min-h-32 place-items-center text-center">
                    <p className="max-w-sm text-xs leading-5 text-muted">Faça uma pergunta sobre as fontes selecionadas. O histórico continuará disponível nesta sessão.</p>
                  </div>
                ) : null}
                {activeSession.messages.map((item) => (
                  <article key={item.id} className={`max-w-[92%] rounded-xl border p-3 ${item.role === "user" ? "ml-auto border-accent/25 bg-accent/[0.06]" : "mr-auto border-line bg-panel"}`}>
                    <div className="flex items-center justify-between gap-3 text-[0.6rem] text-muted">
                      <span className="font-semibold uppercase tracking-wide">{item.role === "user" ? "Você" : "Modelo"}</span>
                      <time>{formatTime(item.created_at)}</time>
                    </div>
                    <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-ink">{item.content}</p>
                  </article>
                ))}
                {pendingUserContent ? (
                  <article className="ml-auto max-w-[92%] rounded-xl border border-accent/25 bg-accent/[0.06] p-3">
                    <span className="text-[0.6rem] font-semibold uppercase tracking-wide text-muted">Você</span>
                    <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-ink">{pendingUserContent}</p>
                  </article>
                ) : null}
                {busy && activeSession ? (
                  <article className="mr-auto max-w-[92%] rounded-xl border border-line bg-panel p-3">
                    <span className="text-[0.6rem] font-semibold uppercase tracking-wide text-muted">Modelo · transmitindo</span>
                    <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-ink">{streamingText || <LoaderCircle className="inline size-3 animate-spin" />}</p>
                  </article>
                ) : null}
              </div>
              <form className="flex items-end gap-2 border-t border-line p-3" onSubmit={(event) => void sendMessage(event)}>
                <label className="min-w-0 flex-1">
                  <span className="sr-only">Mensagem para o modelo</span>
                  <textarea
                    className="field-input min-h-12 resize-y"
                    maxLength={10000}
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    placeholder="Escreva uma pergunta para o modelo…"
                    disabled={busy || activeSession.status === "running"}
                  />
                </label>
                <button type="submit" className="button-primary h-11 shrink-0" disabled={busy || !message.trim()}>
                  {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Send className="size-4" />}
                  Enviar
                </button>
              </form>
            </div>
          )}
          {error ? <p className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">{error}</p> : null}
        </div>

        <aside className="rounded-xl border border-line bg-canvas/25 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold">Conversas salvas</p>
            <span className="font-mono text-[0.6rem] text-muted">{sessions.length}</span>
          </div>
          {!sessions.length ? (
            <p className="mt-3 text-[0.68rem] leading-5 text-muted">As sessões aparecerão aqui depois de iniciadas.</p>
          ) : (
            <div className="mt-2 space-y-1">
              {sessions.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`w-full rounded-lg border px-2.5 py-2 text-left transition ${activeSession?.id === item.id ? "border-accent/35 bg-accent/[0.06]" : "border-transparent hover:border-line hover:bg-panel"}`}
                  onClick={() => void openSession(item.id)}
                >
                  <span className="block truncate text-[0.68rem] font-semibold">{item.messages.find((entry) => entry.role === "user")?.content ?? "Conversa vazia"}</span>
                  <span className="mt-1 block text-[0.58rem] text-muted">{formatTime(item.created_at)} · {item.source_snapshot_json.length} fontes</span>
                </button>
              ))}
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
