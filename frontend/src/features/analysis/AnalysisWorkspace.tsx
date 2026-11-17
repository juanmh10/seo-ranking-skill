import { ArrowLeft, LoaderCircle, Plus, Send, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type { AnalysisSession, Experiment, RunConfig } from "../../types/api";

export function AnalysisWorkspace({
  experiments,
  onBack,
}: {
  experiments: Experiment[];
  onBack: () => void;
}) {
  const [experimentId, setExperimentId] = useState(experiments[0]?.id ?? "");
  const [configs, setConfigs] = useState<RunConfig[]>([]);
  const [sessions, setSessions] = useState<AnalysisSession[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [currentSession, setCurrentSession] = useState<AnalysisSession | null>(null);
  const [message, setMessage] = useState("");
  const [pendingUserContent, setPendingUserContent] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!experimentId) return;
    let active = true;
    setLoading(true);
    setError(null);
    void Promise.all([
      api.listRunConfigs(experimentId),
      api.listAnalysisSessions(experimentId),
    ]).then(([recentConfigs, recentSessions]) => {
      if (!active) return;
      setConfigs(recentConfigs);
      setSessions(recentSessions);
      setSelectedRunIds([]);
      setCurrentSession(recentSessions[0] ?? null);
    }).catch((caught: unknown) => {
      if (active) setError(caught instanceof Error ? caught.message : "Falha ao carregar Analysis.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [experimentId]);

  const runChoices = useMemo(() => configs
    .flatMap((config) => config.runs.map((run) => ({
      id: run.id,
      number: run.run_number,
      status: run.status,
      model: run.model_id_actual ?? "modelo sem resposta",
      question: config.user_prompt,
      createdAt: config.created_at,
    })))
    .filter((run) => ["completed", "completed_with_eval_errors", "failed", "interrupted"].includes(run.status))
    .slice(0, 100), [configs]);

  async function createSession() {
    if (!experimentId || !selectedRunIds.length) return;
    setWorking(true);
    setError(null);
    try {
      const created = await api.createAnalysisSession(experimentId, selectedRunIds);
      setCurrentSession(created);
      setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao criar sessão de Analysis.");
    } finally {
      setWorking(false);
    }
  }

  async function sendMessage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!currentSession || !message.trim() || working) return;
    const userMessage = message.trim();
    setMessage("");
    setPendingUserContent(userMessage);
    setStreamingText("");
    setWorking(true);
    setError(null);
    try {
      const updated = await api.streamAnalysisMessage(
        currentSession.id,
        userMessage,
        (delta) => setStreamingText((current) => current + delta),
      );
      setCurrentSession(updated);
      setSessions((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
    } catch (caught) {
      setMessage(userMessage);
      setError(caught instanceof Error ? caught.message : "Falha ao enviar mensagem para Analysis.");
      const refreshed = await api.getAnalysisSession(currentSession.id).catch(() => null);
      if (refreshed) {
        setCurrentSession(refreshed);
        setSessions((current) => [refreshed, ...current.filter((item) => item.id !== refreshed.id)]);
      }
    } finally {
      setPendingUserContent("");
      setStreamingText("");
      setWorking(false);
    }
  }

  return (
    <section className="min-w-0">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <button type="button" className="inline-flex items-center gap-2 text-xs font-semibold text-muted hover:text-accent" onClick={onBack}>
          <ArrowLeft className="size-4" /> Voltar aos experimentos
        </button>
        {experiments.length ? (
          <label className="flex items-center gap-2 text-xs text-muted">
            Experimento
            <select
              className="field-input min-w-56"
              aria-label="Experimento para análise"
              value={experimentId}
              onChange={(event) => {
                setExperimentId(event.target.value);
                setCurrentSession(null);
              }}
            >
              {experiments.map((experiment) => (
                <option key={experiment.id} value={experiment.id}>{experiment.name}</option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      <header className="rounded-[1.5rem] border border-line bg-panel p-6">
        <p className="eyebrow">Read-only analysis</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-[-0.025em]">Análise de resultados persistidos</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
          Escolha runs concluídos e converse com o agente sobre respostas, labels, avaliações e métricas salvas. A análise não altera os scores oficiais nem o dataset.
        </p>
      </header>

      {error ? <p className="mt-4 rounded-xl border border-danger/30 bg-danger/5 p-3 text-sm text-danger">{error}</p> : null}

      {!experiments.length ? (
        <div className="mt-6 rounded-xl border border-dashed border-line bg-panel/45 p-6 text-sm text-muted">
          Crie um experimento e execute pelo menos um run antes de iniciar Analysis.
        </div>
      ) : (
        <div className="analysis-layout mt-6">
          <aside className="space-y-4">
            <section className="rounded-[1.25rem] border border-line bg-panel p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">Runs disponíveis</h2>
                <span className="font-mono text-[0.62rem] text-muted">{selectedRunIds.length} selecionados</span>
              </div>
              {loading ? <p className="mt-4 text-xs text-muted">Carregando runs…</p> : null}
              {!loading && !runChoices.length ? (
                <p className="mt-4 text-xs leading-5 text-muted">Este experimento ainda não tem runs persistidos para análise.</p>
              ) : null}
              <div className="mt-3 max-h-[28rem] space-y-2 overflow-y-auto">
                {runChoices.map((run) => (
                  <label key={run.id} className="flex cursor-pointer gap-2 rounded-lg border border-line bg-canvas/25 p-3">
                    <input
                      className="mt-0.5 accent-[var(--color-accent)]"
                      type="checkbox"
                      checked={selectedRunIds.includes(run.id)}
                      onChange={(event) => setSelectedRunIds((current) => event.target.checked
                        ? [...current, run.id]
                        : current.filter((id) => id !== run.id))}
                    />
                    <span className="min-w-0">
                      <span className="block text-xs font-semibold">Run {run.number} · {run.status}</span>
                      <span className="mt-1 block truncate text-[0.66rem] text-muted">{run.model}</span>
                      <span className="mt-1 block line-clamp-2 text-[0.66rem] leading-4 text-muted">{run.question}</span>
                      <time className="mt-1 block font-mono text-[0.58rem] text-muted">{new Date(run.createdAt).toLocaleString()}</time>
                    </span>
                  </label>
                ))}
              </div>
              <button
                type="button"
                className="button-primary mt-4 w-full justify-center"
                disabled={working || !selectedRunIds.length}
                onClick={() => void createSession()}
              >
                {working && !currentSession ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
                Nova sessão de Analysis
              </button>
            </section>

            <section className="rounded-[1.25rem] border border-line bg-panel p-4">
              <h2 className="text-sm font-semibold">Sessões salvas</h2>
              {!sessions.length ? <p className="mt-3 text-xs text-muted">As conversas aparecem aqui após a primeira análise.</p> : null}
              <div className="mt-3 space-y-2">
                {sessions.map((analysisSession) => (
                  <button
                    key={analysisSession.id}
                    type="button"
                    className={`w-full rounded-lg border p-3 text-left ${currentSession?.id === analysisSession.id ? "border-accent/45 bg-accent/[0.05]" : "border-line bg-canvas/25"}`}
                    onClick={() => setCurrentSession(analysisSession)}
                  >
                    <span className="block text-xs font-semibold">{analysisSession.selected_run_ids_json.length} runs · {analysisSession.status}</span>
                    <span className="mt-1 block font-mono text-[0.6rem] text-muted">{new Date(analysisSession.created_at).toLocaleString()}</span>
                  </button>
                ))}
              </div>
            </section>
          </aside>

          <section className="flex min-h-[42rem] min-w-0 flex-col rounded-[1.25rem] border border-line bg-panel p-4 md:p-5">
            <div className="flex items-start justify-between gap-3 border-b border-line pb-4">
              <div>
                <p className="eyebrow">Analysis agent</p>
                <h2 className="mt-2 text-base font-semibold">Conversa baseada no banco de resultados</h2>
              </div>
              {currentSession ? (
                <span className="rounded-full border border-line bg-canvas/35 px-2.5 py-1 font-mono text-[0.6rem] text-muted">{currentSession.analysis_model_id}</span>
              ) : null}
            </div>

            {!currentSession ? (
              <div className="grid flex-1 place-items-center p-8 text-center">
                <div>
                  <Sparkles className="mx-auto size-6 text-accent" />
                  <p className="mt-3 text-sm font-semibold">Selecione runs e crie uma sessão</p>
                  <p className="mt-2 max-w-sm text-xs leading-5 text-muted">O agente receberá somente resultados persistidos e métricas agregadas do experimento.</p>
                </div>
              </div>
            ) : (
              <>
                <div className="flex-1 space-y-3 overflow-y-auto py-4" aria-live="polite">
                  {currentSession.messages.map((item) => (
                    <article key={item.id} className={`max-w-[92%] rounded-xl border p-3 ${item.role === "user" ? "ml-auto border-accent/30 bg-accent/[0.05]" : "border-line bg-canvas/30"}`}>
                      <p className="font-mono text-[0.6rem] uppercase tracking-[0.12em] text-muted">{item.role === "user" ? "Você" : "Analysis · read-only"}</p>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{item.content}</p>
                      {item.metadata_json.status === "failed" ? <p className="mt-2 text-[0.65rem] text-danger">Esta tentativa falhou; envie uma nova mensagem para tentar novamente.</p> : null}
                    </article>
                  ))}
                  {pendingUserContent ? (
                    <article className="ml-auto max-w-[92%] rounded-xl border border-accent/30 bg-accent/[0.05] p-3">
                      <p className="font-mono text-[0.6rem] uppercase tracking-[0.12em] text-muted">Você</p>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{pendingUserContent}</p>
                    </article>
                  ) : null}
                  {working ? (
                    <article className="max-w-[92%] rounded-xl border border-line bg-canvas/30 p-3">
                      <p className="font-mono text-[0.6rem] uppercase tracking-[0.12em] text-muted">Analysis · transmitindo</p>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{streamingText || <LoaderCircle className="inline size-3.5 animate-spin" />}</p>
                    </article>
                  ) : null}
                </div>
                <form className="border-t border-line pt-4" onSubmit={(event) => void sendMessage(event)}>
                  <label className="block">
                    <span className="field-label">Pergunta sobre os resultados</span>
                    <textarea
                      className="field-input min-h-24 resize-y"
                      value={message}
                      onChange={(event) => setMessage(event.target.value)}
                      placeholder="Ex.: Compare os scores de grounding e explique o que os runs permitem concluir."
                    />
                  </label>
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <p className="text-[0.65rem] text-muted">A conversa fica salva e pode ser retomada depois.</p>
                    <button type="submit" className="button-primary" disabled={working || !message.trim()}>
                      {working ? <LoaderCircle className="size-4 animate-spin" /> : <Send className="size-4" />}
                      Enviar
                    </button>
                  </div>
                </form>
              </>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
