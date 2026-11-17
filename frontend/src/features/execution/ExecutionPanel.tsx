import { ArrowDownToLine, ArrowUpRight, LoaderCircle, Play, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { EvalResult, ExperimentMetrics, ModelEntry, Run, RunConfig, RunCreate, RunEvent, SourceDocumentSummary, SystemPrompt } from "../../types/api";

const terminalStatuses = new Set(["completed", "completed_with_eval_errors", "failed", "interrupted"]);
const metricNames: Record<string, string> = {
  injection_compliance: "Injection compliance",
  claim_adoption: "Claim adoption",
  citation_adoption: "Citation adoption",
  competitor_suppression: "Competitor suppression",
  fabricated_authority_adoption: "Fabricated authority",
  source_grounding: "Source grounding",
  unsupported_claim_rate: "Unsupported claim rate",
  injection_awareness: "Injection awareness",
};

function formatEvalScore(result: EvalResult): string {
  if (result.score === null) return result.label ?? "sem score";
  if (result.definition.metric_name === "target_rank") {
    return `#${Number.isInteger(result.score) ? result.score : result.score.toFixed(1)}`;
  }
  return `${Math.round(result.score * 100)}%`;
}

function describeEvent(event: RunEvent): string {
  const runNumber = event.payload_json.run_number;
  const labels: Record<string, string> = {
    run_config_queued: "Benchmark entrou na fila",
    run_config_started: "Benchmark iniciado",
    run_started: `Run ${typeof runNumber === "number" ? runNumber : ""} iniciado`.trim(),
    run_output_persisted: "Resposta do modelo persistida",
    run_evaluated: "Avaliação determinística concluída",
    llm_evaluation_started: "Avaliação LLM iniciada",
    llm_evaluation_completed: "Avaliação LLM concluída",
    run_eval_failed: "Uma etapa de avaliação falhou",
    run_failed: "Run falhou",
    run_completed: "Run concluído",
    run_config_finished: "Benchmark finalizado",
    eval_recompute_started: "Reavaliação iniciada",
    eval_recompute_completed: "Reavaliação concluída",
    eval_recompute_failed: "Reavaliação falhou; scores anteriores preservados",
  };
  return labels[event.event_type] ?? event.event_type.replaceAll("_", " ");
}

export function ExecutionPanel({
  experimentId,
  documents,
  activeCount,
  targetCount,
  sampleQuestion,
  onPromoted,
}: {
  experimentId: string;
  documents: SourceDocumentSummary[];
  activeCount: number;
  targetCount: number;
  sampleQuestion?: string;
  onPromoted: () => Promise<void>;
}) {
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [prompts, setPrompts] = useState<SystemPrompt[]>([]);
  const [configs, setConfigs] = useState<RunConfig[]>([]);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [metrics, setMetrics] = useState<ExperimentMetrics | null>(null);
  const [selectedConfigId, setSelectedConfigId] = useState<string | null>(null);
  const [modelId, setModelId] = useState("");
  const [evaluatorModelId, setEvaluatorModelId] = useState("");
  const [promptId, setPromptId] = useState("");
  const [question, setQuestion] = useState("");
  const [contentMode, setContentMode] = useState<RunCreate["content_mode"]>("NORMALIZED");
  const [order, setOrder] = useState<RunCreate["ordering_strategy"]>("fixed");
  const [repetitions, setRepetitions] = useState(1);
  const [temperature, setTemperature] = useState(0.7);
  const [topP, setTopP] = useState(0.95);
  const [maxOutputTokens, setMaxOutputTokens] = useState(2048);
  const [counterfactualDocumentIds, setCounterfactualDocumentIds] = useState<string[]>([]);
  const [creatingPrompt, setCreatingPrompt] = useState(false);
  const [newPromptName, setNewPromptName] = useState("");
  const [newPromptContent, setNewPromptContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [promotingId, setPromotingId] = useState<string | null>(null);
  const [recomputingRunId, setRecomputingRunId] = useState<string | null>(null);
  const [exportingManifest, setExportingManifest] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (sampleQuestion) setQuestion(sampleQuestion);
  }, [sampleQuestion]);
  const selectedConfig = configs.find((config) => config.id === selectedConfigId);
  const selectedStatus = selectedConfig?.status;
  const activeTarget = documents.find((document) => document.position !== null && document.label.expected_target);
  const activeGroupKey = activeTarget?.counterfactual_group_key?.trim() ?? "";
  const normalizeIdentity = (value: string | null) => (value ?? "").trim().replace(/\s+/g, " ").toLocaleLowerCase();
  const counterfactualCandidates = activeTarget && activeGroupKey && activeTarget.entity_key && activeTarget.entity_name
    ? documents.filter((document) =>
      document.position === null
      && document.id !== activeTarget.id
      && document.label.expected_target
      && document.counterfactual_group_key?.trim() === activeGroupKey
      && document.entity_key === activeTarget.entity_key
      && normalizeIdentity(document.entity_name) === normalizeIdentity(activeTarget.entity_name)
      && document.mime_type === activeTarget.mime_type
      && document.source_representation === activeTarget.source_representation)
    : [];
  const selectedCounterfactualCandidates = counterfactualCandidates.filter((document) => counterfactualDocumentIds.includes(document.id));
  const counterfactualLabels = [activeTarget, ...selectedCounterfactualCandidates]
    .filter((document): document is SourceDocumentSummary => !!document)
    .map((document) => `${document.label.severity}:${document.label.technique}`);
  const hasOneControl = counterfactualLabels.filter((condition) => condition === "neutral:none").length === 1;
  const hasUniqueConditions = new Set(counterfactualLabels).size === counterfactualLabels.length;
  const hasManipulatedCondition = counterfactualLabels.some((condition) => condition !== "neutral:none");
  const counterfactualSelectionValid = counterfactualDocumentIds.length === 0 || (
    selectedCounterfactualCandidates.length === counterfactualDocumentIds.length
    && !!activeGroupKey
    && hasOneControl
    && hasUniqueConditions
    && hasManipulatedCondition
  );

  useEffect(() => {
    let active = true;
    void Promise.all([
      api.listModels(),
      api.listPrompts(),
      api.listRunConfigs(experimentId),
      api.getExperimentMetrics(experimentId),
    ])
      .then(([availableModels, availablePrompts, recentConfigs, currentMetrics]) => {
        if (!active) return;
        setModels(availableModels);
        setPrompts(availablePrompts);
        setConfigs(recentConfigs);
        setMetrics(currentMetrics);
        const preferredModel = availableModels.find(
          (model) => model.model_id === "gemini-3.5-flash-lite" && model.runnable,
        );
        setModelId((current) => current || preferredModel?.model_id || availableModels.find((model) => model.runnable)?.model_id || "");
        setPromptId((current) => current || availablePrompts[0]?.id || "");
        setSelectedConfigId((current) => current || recentConfigs[0]?.id || null);
        setQuestion((current) => current || recentConfigs[0]?.user_prompt || "");
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "Falha ao carregar execução.");
      });
    return () => { active = false; };
  }, [experimentId]);

  useEffect(() => {
    if (!selectedConfigId || (selectedStatus && terminalStatuses.has(selectedStatus))) return;
    let active = true;
    const refresh = () => {
      void api.getRunConfig(selectedConfigId).then((updated) => {
        if (!active) return;
        setConfigs((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
        if (terminalStatuses.has(updated.status)) {
          void api.getExperimentMetrics(experimentId).then(setMetrics).catch(() => undefined);
        }
      }).catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "Falha ao atualizar run.");
      });
    };
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [experimentId, selectedConfigId, selectedStatus]);

  useEffect(() => {
    if (!selectedConfigId) {
      setEvents([]);
      return;
    }
    let active = true;
    void api.listRunEvents(selectedConfigId).then((updated) => {
      if (!active) return;
      setEvents((current) => {
        const byId = new Map([...current, ...updated].map((event) => [event.id, event]));
        return [...byId.values()].sort((left, right) => left.id - right.id);
      });
    }).catch((caught: unknown) => {
      if (active) setError(caught instanceof Error ? caught.message : "Falha ao carregar eventos.");
    });
    const closeStream = api.subscribeRunEvents(selectedConfigId, (event) => {
      if (!active) return;
      setEvents((current) => current.some((item) => item.id === event.id)
        ? current
        : [...current, event].sort((left, right) => left.id - right.id));
    });
    if (!closeStream && selectedStatus && !terminalStatuses.has(selectedStatus)) {
      const timer = window.setInterval(() => {
        void api.listRunEvents(selectedConfigId).then((updated) => {
          if (active) setEvents(updated);
        }).catch(() => undefined);
      }, 1500);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }
    return () => {
      active = false;
      closeStream?.();
    };
  }, [selectedConfigId, selectedStatus]);

  const selectedModel = models.find((model) => model.model_id === modelId);
  const visibleEvents = events.filter((event) => event.event_type !== "run_output_delta");
  const canRun = activeCount === 5 && targetCount === 1 && !!selectedModel?.runnable && !!promptId && !!question.trim() && counterfactualSelectionValid;

  async function savePrompt() {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createPrompt(newPromptName, newPromptContent);
      setPrompts((current) => [created, ...current]);
      setPromptId(created.id);
      setCreatingPrompt(false);
      setNewPromptName("");
      setNewPromptContent("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao salvar prompt.");
    } finally {
      setBusy(false);
    }
  }

  async function startRun() {
    if (!canRun || !selectedModel) return;
    setBusy(true);
    setError(null);
    try {
      const payload: RunCreate = {
        model_id: modelId,
        system_prompt_id: promptId,
        user_prompt: question.trim(),
        content_mode: contentMode,
        ordering_strategy: order,
        repetitions,
        max_output_tokens: maxOutputTokens,
        ...(counterfactualDocumentIds.length ? { counterfactual_document_ids: counterfactualDocumentIds } : {}),
        ...(evaluatorModelId ? { evaluator_model_id: evaluatorModelId } : {}),
        ...(selectedModel.supports_temperature ? { temperature } : {}),
        ...(selectedModel.supports_top_p ? { top_p: topP } : {}),
      };
      const accepted = await api.createRun(experimentId, payload);
      const created = await api.getRunConfig(accepted.run_config_id);
      setConfigs((current) => [created, ...current]);
      setSelectedConfigId(created.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao iniciar run.");
    } finally {
      setBusy(false);
    }
  }

  async function promote(run: Run) {
    setPromotingId(run.id);
    setError(null);
    try {
      await api.promoteRunOutput(run.id);
      await onPromoted();
      if (selectedConfigId) {
        const updated = await api.getRunConfig(selectedConfigId);
        setConfigs((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao adicionar output ao acervo.");
    } finally {
      setPromotingId(null);
    }
  }

  async function recomputeEvaluations(run: Run) {
    setRecomputingRunId(run.id);
    setError(null);
    try {
      await api.recomputeRunEvals(run.id, evaluatorModelId || undefined);
      if (selectedConfigId) {
        const [updatedConfig, updatedMetrics] = await Promise.all([
          api.getRunConfig(selectedConfigId),
          api.getExperimentMetrics(experimentId),
        ]);
        setConfigs((current) => [updatedConfig, ...current.filter((item) => item.id !== updatedConfig.id)]);
        setMetrics(updatedMetrics);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao recalcular avaliações.");
    } finally {
      setRecomputingRunId(null);
    }
  }

  async function exportManifest() {
    setExportingManifest(true);
    setError(null);
    try {
      const manifest = await api.getExperimentManifest(experimentId);
      const blob = new Blob([JSON.stringify(manifest, null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `experiment-${experimentId}-manifest.json`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao exportar manifest.");
    } finally {
      setExportingManifest(false);
    }
  }

  return (
    <section className="execution-layout rounded-[1.35rem] border border-line bg-panel p-4 md:p-5">
      <div className="execution-header flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Benchmark execution</p>
          <h2 className="mt-2 text-lg font-semibold">Rodar modelo com as cinco fontes</h2>
          <p className="mt-2 text-xs leading-5 text-muted">
            Cada repetição usa uma sessão nova. O output pode ser adicionado ao acervo para a próxima iteração.
          </p>
        </div>
        <button
          type="button"
          className="button-secondary"
          disabled={exportingManifest}
          onClick={() => void exportManifest()}
        >
          {exportingManifest ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowDownToLine className="size-4" />}
          Baixar manifest
        </button>
      </div>

      {error ? <p className="mt-4 rounded-xl border border-danger/30 bg-danger/5 p-3 text-sm text-danger">{error}</p> : null}
      <div className="execution-settings">
      {!models.length ? (
        <p className="mt-3 rounded-xl border border-line bg-canvas/35 p-3 text-xs leading-5 text-muted">
          Nenhum modelo configurado. Defina APP_GCP_PROJECT e APP_MODEL_REGISTRY no backend para habilitar a execução.
        </p>
      ) : null}
      {selectedModel?.availability_note ? (
        <p className="mt-3 text-[0.68rem] leading-4 text-muted">{selectedModel.availability_note}</p>
      ) : selectedModel && !selectedModel.last_verified_at ? (
        <p className="mt-3 text-[0.68rem] leading-4 text-muted">
          Modelo cadastrado localmente; a disponibilidade no Vertex ainda não foi verificada pelo aplicativo.
        </p>
      ) : null}

      <div className="mt-4 grid gap-3">
        <label>
          <span className="field-label">Modelo</span>
          <select className="field-input" value={modelId} onChange={(event) => setModelId(event.target.value)}>
            {models.map((model) => <option key={model.model_id} value={model.model_id} disabled={!model.runnable}>
              {model.display_name} · {model.location}{model.runnable ? "" : " · indisponível"}
            </option>)}
          </select>
        </label>
        <label>
          <span className="field-label">System prompt versionado</span>
          <select className="field-input" value={promptId} onChange={(event) => setPromptId(event.target.value)}>
            {prompts.map((prompt) => <option key={prompt.id} value={prompt.id}>{prompt.name} · v{prompt.version}</option>)}
          </select>
        </label>
        <label>
          <span className="field-label">Avaliador LLM (opcional)</span>
          <select className="field-input" value={evaluatorModelId} onChange={(event) => setEvaluatorModelId(event.target.value)}>
            <option value="">Somente avaliação determinística</option>
            {models.filter((model) => model.runnable && model.supports_structured_output).map((model) => (
              <option key={model.model_id} value={model.model_id}>{model.display_name} · {model.location}</option>
            ))}
          </select>
          <span className="mt-1 block text-[0.68rem] leading-4 text-muted">
            Se selecionado, cada repetição faz uma chamada extra para os oito critérios: compliance de prompt, adoção de claims e citações, supressão de concorrentes, autoridade fabricada, grounding, claims sem suporte e awareness. Pode gerar custo Vertex.
          </span>
        </label>
      </div>

      <button type="button" className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-accent" onClick={() => setCreatingPrompt(!creatingPrompt)}>
        <Plus className="size-3.5" /> Nova versão de prompt
      </button>
      {creatingPrompt ? (
        <div className="mt-3 grid gap-3 rounded-xl border border-line bg-canvas/35 p-4">
          <input className="field-input" aria-label="Nome do prompt" placeholder="Nome do prompt" value={newPromptName} onChange={(event) => setNewPromptName(event.target.value)} />
          <textarea className="field-input min-h-28" aria-label="Conteúdo do prompt" placeholder="Instrução de sistema" value={newPromptContent} onChange={(event) => setNewPromptContent(event.target.value)} />
          <button type="button" className="button-secondary justify-self-start" disabled={busy || !newPromptName.trim() || !newPromptContent.trim()} onClick={() => void savePrompt()}>Salvar prompt</button>
        </div>
      ) : null}

      <div className="mt-5 grid gap-3">
        <label><span className="field-label">Conteúdo enviado</span>
          <select className="field-input" value={contentMode} onChange={(event) => setContentMode(event.target.value as RunCreate["content_mode"])}>
            <option>RAW</option><option>NORMALIZED</option><option>BOTH</option>
          </select>
        </label>
        <label><span className="field-label">Ordem das fontes</span>
          <select className="field-input" value={order} onChange={(event) => setOrder(event.target.value as RunCreate["ordering_strategy"])}>
            <option value="fixed">Fixa</option><option value="randomized">Aleatória</option><option value="counterbalanced">Contrabalanceada</option>
          </select>
        </label>
        <label><span className="field-label">Repetições por condição</span>
          <input className="field-input" type="number" min={1} max={100} value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))} />
        </label>
        <label><span className="field-label">Máx. tokens de saída</span>
          <input className="field-input" type="number" min={1} max={65536} value={maxOutputTokens} onChange={(event) => setMaxOutputTokens(Number(event.target.value))} />
        </label>
        {selectedModel?.supports_temperature ? <label><span className="field-label">Temperature</span><input className="field-input" type="number" min={0} max={2} step={0.1} value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /></label> : null}
        {selectedModel?.supports_top_p ? <label><span className="field-label">Top-p</span><input className="field-input" type="number" min={0.01} max={1} step={0.01} value={topP} onChange={(event) => setTopP(Number(event.target.value))} /></label> : null}
      </div>
      </div>

      <div className="execution-main">

      <label className="mt-5 block">
        <span className="field-label">Pergunta ao modelo</span>
        <textarea className="field-input min-h-24" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ex.: Qual das cinco clínicas você recomendaria e por quê?" />
      </label>

      <fieldset className="mt-4 rounded-xl border border-line bg-canvas/35 p-4">
        <legend className="px-1 text-xs font-semibold text-ink">Variantes contrafactuais (opcional)</legend>
        <p className="mb-3 text-[0.7rem] leading-5 text-muted">
          Selecione versões alternativas do mesmo alvo, fora dos cinco slots. Para comparar, inclua exatamente um controle neutral/none e ao menos uma condição manipulada; cada repetição executará todas as condições com a mesma ordem de fontes.
        </p>
        {counterfactualCandidates.length ? (
          <div className="space-y-2">
            {counterfactualCandidates.map((document) => (
              <label key={document.id} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line px-3 py-2">
                <input
                  className="mt-0.5 accent-[var(--accent)]"
                  type="checkbox"
                  checked={counterfactualDocumentIds.includes(document.id)}
                  onChange={(event) => setCounterfactualDocumentIds((current) => event.target.checked
                    ? [...current, document.id]
                    : current.filter((id) => id !== document.id))}
                />
                <span className="min-w-0">
                  <span className="block truncate text-xs font-medium">{document.filename}</span>
                  <span className="mt-0.5 block text-[0.65rem] text-muted">{document.label.severity} · {document.label.technique}</span>
                </span>
              </label>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted">Nenhuma variante elegível. No inspector da fonte, configure a mesma chave de entidade, nome e grupo contrafactual; depois marque a versão alternativa como expected_target.</p>
        )}
        {counterfactualDocumentIds.length > 0 && !counterfactualSelectionValid ? (
          <p className="mt-3 text-xs text-danger">A seleção precisa ter um único controle neutral/none, condições severity/technique distintas e variantes ainda compatíveis com o alvo ativo.</p>
        ) : null}
        {counterfactualDocumentIds.length > 0 ? (
          <p className="mt-3 text-[0.68rem] text-muted">{counterfactualDocumentIds.length + 1} condições · {repetitions * (counterfactualDocumentIds.length + 1)} runs planejados</p>
        ) : null}
      </fieldset>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button type="button" className="button-primary" disabled={!canRun || busy} onClick={() => void startRun()}>
          {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />}
          Iniciar benchmark
        </button>
        {!canRun ? <span className="text-xs text-muted">Requer 5 fontes, 1 target, modelo, prompt e pergunta.</span> : null}
      </div>

      {configs.length ? (
        <div className="mt-8 border-t border-line pt-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">Runs registrados</h3>
            <select className="field-input w-auto min-w-44" aria-label="Selecionar configuração de run" value={selectedConfigId ?? ""} onChange={(event) => setSelectedConfigId(event.target.value)}>
              {configs.map((config) => <option key={config.id} value={config.id}>{new Date(config.created_at).toLocaleString()} · {config.status}</option>)}
            </select>
          </div>
          {selectedConfig ? (
            <div className="mt-4 space-y-3">
              <p className="text-xs text-muted">Status: {selectedConfig.status} · {selectedConfig.repetitions} repetição(ões) por condição · {selectedConfig.runs.length} runs{selectedConfig.random_seed !== null ? ` · seed ${selectedConfig.random_seed}` : ""}</p>
              {[...selectedConfig.runs].sort((a, b) => a.run_number - b.run_number).map((run) => (
                <article key={run.id} className="rounded-xl border border-line bg-canvas/35 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold">Run {run.run_number} · {run.status}</p>
                    <span className="font-mono text-[0.65rem] text-muted">{run.duration_ms !== null ? `${run.duration_ms} ms` : ""}{run.total_tokens !== null ? ` · ${run.total_tokens} tokens` : ""}</span>
                  </div>
                  {(() => {
                    const streamedText = events
                      .filter((event) => event.run_id === run.id && event.event_type === "run_output_delta")
                      .map((event) => event.payload_json.text_delta)
                      .filter((delta): delta is string => typeof delta === "string")
                      .join("");
                    const outputText = run.response_text ?? streamedText;
                    return outputText ? (
                      <div className="mt-3">
                        {!run.response_text && run.status === "running" ? <p className="mb-1 text-[0.65rem] text-muted">Resposta em streaming</p> : null}
                        <pre className="source-code max-h-72">{outputText}</pre>
                      </div>
                    ) : null;
                  })()}
                  {run.error_message ? <p className="mt-3 text-xs text-danger">{run.error_message}</p> : null}
                  {run.evaluation_error ? <p className="mt-3 text-xs text-danger">Avaliação: {run.evaluation_error}</p> : null}
                  {run.eval_results.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {run.eval_results.map((result) => (
                        <span key={result.id} className="source-badge" title={`${result.reasoning ?? ""} · evaluator ${result.evaluator_version}`}>
                          {result.definition.metric_name} v{result.definition.version}: {formatEvalScore(result)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {run.status === "completed" && run.response_text ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button type="button" className="button-secondary" disabled={promotingId === run.id || !!run.output_document_id} onClick={() => void promote(run)}>
                        <ArrowUpRight className="size-3.5" /> {run.output_document_id ? "Já está no acervo" : promotingId === run.id ? "Adicionando…" : "Adicionar output ao acervo"}
                      </button>
                      <button type="button" className="button-secondary" disabled={recomputingRunId === run.id} onClick={() => void recomputeEvaluations(run)}>
                        {recomputingRunId === run.id ? <LoaderCircle className="size-3.5 animate-spin" /> : <ArrowDownToLine className="size-3.5" />}
                        {recomputingRunId === run.id ? "Recalculando avaliações…" : "Recomputar avaliações"}
                      </button>
                    </div>
                  ) : null}
                </article>
              ))}
              {terminalStatuses.has(selectedConfig.status) && selectedConfig.status !== "completed_with_eval_errors" ? <p className="text-xs text-muted">Scores determinísticos usam nomes e aliases explícitos; respostas sem sinal de recomendação ficam sem score.</p> : null}
            </div>
          ) : null}
          {selectedConfig ? (
            <section className="mt-6 rounded-xl border border-line bg-canvas/25 p-4" aria-label="Eventos do benchmark">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">Eventos e rastreabilidade</h3>
                <span className="font-mono text-[0.62rem] text-muted">{visibleEvents.length} eventos</span>
              </div>
              {visibleEvents.length ? (
                <ol className="mt-3 space-y-2">
                  {visibleEvents.map((event) => (
                    <li key={event.id} className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 rounded-lg border border-line/70 bg-panel/55 px-3 py-2">
                      <time className="pt-0.5 font-mono text-[0.6rem] text-muted" dateTime={event.created_at}>
                        {new Date(event.created_at).toLocaleTimeString()}
                      </time>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-ink">{describeEvent(event)}</p>
                        <details className="mt-1">
                          <summary className="cursor-pointer text-[0.65rem] text-muted">Detalhes · evento #{event.id}</summary>
                          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-canvas/60 p-2 font-mono text-[0.62rem] text-muted">{JSON.stringify(event.payload_json, null, 2)}</pre>
                        </details>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="mt-3 text-xs text-muted">Os eventos persistidos aparecerão aqui quando a execução iniciar.</p>
              )}
            </section>
          ) : null}
          {metrics?.conditions.length ? (
            <div className="mt-6 overflow-x-auto rounded-xl border border-line">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead className="bg-canvas/45 text-muted">
                  <tr>
                    <th className="px-3 py-2">Condição do alvo</th><th className="px-3 py-2">Posição</th><th className="px-3 py-2">Runs</th><th className="px-3 py-2">Seleção explícita</th><th className="px-3 py-2">Menção média do alvo</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.conditions.map((condition, index) => (
                    <tr key={`${condition.dataset_id}-${condition.target_position}-${index}`} className="border-t border-line">
                      <td className="px-3 py-2">{condition.target_severity} · {condition.target_technique} · {condition.model_id}</td>
                      <td className="px-3 py-2">{condition.target_position}</td>
                      <td className="px-3 py-2">{condition.run_count}</td>
                      <td className="px-3 py-2">{condition.target_selection_rate === null ? "sem amostra explícita" : `${Math.round(condition.target_selection_rate * 100)}% (${condition.selection_sample_count})`}</td>
                      <td className="px-3 py-2">{condition.mean_target_rank === null ? "—" : condition.mean_target_rank.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!metrics.manipulation_lift.calculable && metrics.manipulation_lift.reason ? <p className="border-t border-line px-3 py-2 text-xs text-muted">Manipulation Lift: {metrics.manipulation_lift.reason}</p> : null}
              <details className="border-t border-line px-3 py-2">
                <summary className="cursor-pointer text-xs font-semibold text-ink">Escores agregados da eval suite</summary>
                <div className="mt-3 space-y-3">
                  {metrics.conditions.map((condition, index) => (
                    <div key={`${condition.dataset_id}-${condition.target_position}-${index}`} className="rounded-lg border border-line bg-panel/55 p-3">
                      <p className="text-[0.68rem] font-semibold">{condition.target_severity} · {condition.target_technique} · posição {condition.target_position} · {condition.model_id}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(condition.metric_means)
                          .filter(([name]) => !["target_selection_rate", "target_rank"].includes(name))
                          .map(([name, mean]) => (
                            <span key={name} className="rounded-md border border-line bg-canvas/35 px-2 py-1 text-[0.6rem] text-muted" title={`${condition.metric_sample_counts[name] ?? 0} amostras`}>
                              {metricNames[name] ?? name.replaceAll("_", " ")}: {Math.round(mean * 100)}% · n={condition.metric_sample_counts[name] ?? 0}
                            </span>
                          ))}
                        {!Object.keys(condition.metric_means).some((name) => !["target_selection_rate", "target_rank"].includes(name)) ? (
                          <span className="text-[0.65rem] text-muted">Sem scores de LLM judge para esta condição.</span>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            </div>
          ) : null}
          {metrics?.manipulation_lift.calculable ? (
            <div className="mt-6 overflow-x-auto rounded-xl border border-line">
              <div className="border-b border-line px-3 py-3">
                <h3 className="text-sm font-semibold">Manipulation Lift</h3>
                <p className="mt-1 text-[0.68rem] text-muted">Lift é a taxa de seleção manipulada menos controle. Δ rank é a posição do controle menos a posição manipulada; valor positivo indica que o alvo subiu. Usamos pares na mesma posição e com as mesmas outras quatro fontes.</p>
              </div>
              <table className="w-full min-w-[820px] text-left text-xs">
                <thead className="bg-canvas/45 text-muted">
                  <tr><th className="px-3 py-2">Comparação</th><th className="px-3 py-2">Controle</th><th className="px-3 py-2">Manipulada</th><th className="px-3 py-2">Lift</th><th className="px-3 py-2">Δ rank médio</th><th className="px-3 py-2">Pares</th><th className="px-3 py-2">Posições</th></tr>
                </thead>
                <tbody>
                  {metrics.manipulation_lift.comparisons.map((comparison) => (
                    <tr key={`${comparison.run_config_id}-${comparison.injected.severity}-${comparison.injected.technique}`} className="border-t border-line">
                      <td className="px-3 py-2">{comparison.model_id}<br /><span className="text-[0.62rem] text-muted">{comparison.counterfactual_group_key}</span></td>
                      <td className="px-3 py-2">{comparison.control.severity} · {comparison.control.technique}: {Math.round(comparison.control_selection_rate * 100)}%</td>
                      <td className="px-3 py-2">{comparison.injected.severity} · {comparison.injected.technique}: {Math.round(comparison.injected_selection_rate * 100)}%</td>
                      <td className="px-3 py-2">{comparison.lift_percentage_points > 0 ? "+" : ""}{comparison.lift_percentage_points.toFixed(1)} pp</td>
                      <td className="px-3 py-2">{comparison.rank_delta === null ? "n/d" : `${comparison.rank_delta > 0 ? "+" : ""}${comparison.rank_delta.toFixed(1)} · n=${comparison.rank_delta_sample_count}`}</td>
                      <td className="px-3 py-2">{comparison.matched_pair_count}</td>
                      <td className="px-3 py-2">{Object.entries(comparison.position_distribution).map(([position, count]) => `${position}: ${count}`).join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
      </div>
    </section>
  );
}
