import type {
  Experiment,
  ExperimentCreate,
  ExperimentList,
  HealthResponse,
  DocumentLabel,
  SourceDocument,
  SourceDocumentList,
  ModelEntry,
  SystemPrompt,
  RunCreate,
  RunConfig,
  RunAccepted,
  RunEvent,
  ExperimentMetrics,
  EvalResult,
  AnalysisSession,
  SamplePack,
  SamplePackImport,
  InteractiveSession,
} from "../types/api";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | { msg?: string }[];
    } | null;
    const detail = payload?.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item.msg ?? "Campo inválido").join("; ")
        : "Não foi possível concluir a operação.";
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

const runEventTypes = [
  "run_config_queued",
  "run_config_started",
  "run_started",
  "run_output_delta",
  "run_output_persisted",
  "run_evaluated",
  "llm_evaluation_started",
  "llm_evaluation_completed",
  "run_eval_failed",
  "run_failed",
  "run_completed",
  "run_config_finished",
  "eval_recompute_started",
  "eval_recompute_completed",
  "eval_recompute_failed",
];

function subscribeRunEventStream(
  path: string,
  onEvent: (event: RunEvent) => void,
) {
  if (typeof EventSource === "undefined") return null;
  const stream = new EventSource(`${API_ROOT}${path}`);
  for (const eventType of runEventTypes) {
    stream.addEventListener(eventType, (event) => {
      const message = event as MessageEvent<string>;
      try {
        onEvent(JSON.parse(message.data) as RunEvent);
      } catch {
        // Ignore malformed events; the persisted event list remains the source of truth.
      }
    });
  }
  stream.addEventListener("stream_end", () => stream.close());
  return () => stream.close();
}

export const api = {
  health: () => request<HealthResponse>("/readiness"),
  listExperiments: () => request<ExperimentList>("/experiments"),
  getExperiment: (id: string) => request<Experiment>(`/experiments/${id}`),
  createExperiment: (payload: ExperimentCreate) =>
    request<Experiment>("/experiments", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  archiveExperiment: (id: string) =>
    request<Experiment>(`/experiments/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "archived" }),
    }),
  listDocuments: (experimentId: string) =>
    request<SourceDocumentList>(`/experiments/${experimentId}/documents`),
  listSamplePacks: () => request<SamplePack[]>("/sample-packs"),
  importSamplePack: (experimentId: string, samplePackId: string) =>
    request<SamplePackImport>(`/experiments/${experimentId}/sample-packs/${samplePackId}`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  getDocument: (id: string) => request<SourceDocument>(`/documents/${id}`),
  uploadDocument: (experimentId: string, file: File, position?: number) => {
    const form = new FormData();
    form.append("file", file);
    if (position === undefined) form.append("library_only", "true");
    else form.append("position", position.toString());
    return request<SourceDocument>(`/experiments/${experimentId}/documents`, {
      method: "POST",
      body: form,
    });
  },
  updateDocument: (
    id: string,
    payload: {
      position?: number | null;
      entity_name?: string | null;
      entity_key?: string | null;
      aliases?: string[];
      counterfactual_group_key?: string | null;
    },
  ) =>
    request<SourceDocument>(`/documents/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  updateDocumentLabel: (id: string, payload: Partial<DocumentLabel>) =>
    request<SourceDocument>(`/documents/${id}/label`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  listModels: () => request<ModelEntry[]>("/models"),
  listPrompts: () => request<SystemPrompt[]>("/prompts"),
  createPrompt: (name: string, content: string) =>
    request<SystemPrompt>("/prompts", {
      method: "POST",
      body: JSON.stringify({ name, content }),
    }),
  listRunConfigs: (experimentId: string) =>
    request<RunConfig[]>(`/experiments/${experimentId}/run-configs`),
  createRun: (experimentId: string, payload: RunCreate) =>
    request<RunAccepted>(`/experiments/${experimentId}/runs`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  getRunConfig: (id: string) => request<RunConfig>(`/run-configs/${id}`),
  listRunEvents: (id: string) => request<RunEvent[]>(`/run-configs/${id}/events`),
  subscribeRunEvents: (id: string, onEvent: (event: RunEvent) => void) =>
    subscribeRunEventStream(`/run-configs/${id}/stream`, onEvent),
  listIndividualRunEvents: (id: string) => request<RunEvent[]>(`/runs/${id}/events`),
  subscribeIndividualRunEvents: (id: string, onEvent: (event: RunEvent) => void) =>
    subscribeRunEventStream(`/runs/${id}/stream`, onEvent),
  getExperimentMetrics: (experimentId: string) =>
    request<ExperimentMetrics>(`/experiments/${experimentId}/metrics`),
  recomputeRunEvals: (runId: string, evaluatorModelId?: string) =>
    request<EvalResult[]>(`/runs/${runId}/evals/recompute`, {
      method: "POST",
      body: JSON.stringify(evaluatorModelId ? { evaluator_model_id: evaluatorModelId } : {}),
    }),
  getExperimentManifest: (experimentId: string) =>
    request<Record<string, unknown>>(`/experiments/${experimentId}/manifest`),
  promoteRunOutput: (runId: string) =>
    request<SourceDocument>(`/runs/${runId}/source`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  listAnalysisSessions: (experimentId: string) =>
    request<AnalysisSession[]>(`/experiments/${experimentId}/analysis/sessions`),
  createAnalysisSession: (experimentId: string, runIds: string[]) =>
    request<AnalysisSession>(`/experiments/${experimentId}/analysis/sessions`, {
      method: "POST",
      body: JSON.stringify({ run_ids: runIds }),
    }),
  getAnalysisSession: (sessionId: string) =>
    request<AnalysisSession>(`/analysis/sessions/${sessionId}`),
  addAnalysisMessage: (sessionId: string, content: string) =>
    request<AnalysisSession>(`/analysis/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  listInteractiveSessions: (experimentId: string) =>
    request<InteractiveSession[]>(`/experiments/${experimentId}/interactive/sessions`),
  createInteractiveSession: (
    experimentId: string,
    payload: {
      model_id: string;
      system_prompt_id: string;
      source_document_ids: string[];
      content_mode: "RAW" | "NORMALIZED" | "BOTH";
      temperature?: number;
      top_p?: number;
      seed?: number;
      max_output_tokens: number;
    },
  ) =>
    request<InteractiveSession>(`/experiments/${experimentId}/interactive/sessions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getInteractiveSession: (sessionId: string) =>
    request<InteractiveSession>(`/interactive/sessions/${sessionId}`),
  resetInteractiveSession: (sessionId: string) =>
    request<InteractiveSession>(`/interactive/sessions/${sessionId}/reset`, {
      method: "POST",
    }),
  streamInteractiveMessage: async (
    sessionId: string,
    content: string,
    onDelta: (text: string) => void,
  ): Promise<InteractiveSession> => {
    const response = await fetch(`${API_ROOT}/interactive/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new ApiError(payload?.detail ?? "Não foi possível enviar a mensagem.", response.status);
    }
    if (!response.body) throw new Error("O navegador não conseguiu abrir o stream de resposta.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completedSession: InteractiveSession | null = null;
    let streamError: string | null = null;

    function readEvent(block: string) {
      const lines = block.split("\n");
      const eventName = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
      if (!eventName || !data) return;
      const payload = JSON.parse(data) as { text?: string; session?: InteractiveSession; detail?: string };
      if (eventName === "delta" && typeof payload.text === "string") onDelta(payload.text);
      if (eventName === "done" && payload.session) completedSession = payload.session;
      if (eventName === "error") streamError = payload.detail ?? "O modelo não concluiu a resposta.";
    }

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
      let separator = buffer.indexOf("\n\n");
      while (separator >= 0) {
        readEvent(buffer.slice(0, separator));
        buffer = buffer.slice(separator + 2);
        separator = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    if (buffer.trim()) readEvent(buffer);
    if (streamError) throw new Error(streamError);
    if (!completedSession) throw new Error("O stream terminou sem confirmar a resposta persistida.");
    return completedSession;
  },
  streamAnalysisMessage: async (
    sessionId: string,
    content: string,
    onDelta: (text: string) => void,
  ): Promise<AnalysisSession> => {
    const response = await fetch(`${API_ROOT}/analysis/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new ApiError(payload?.detail ?? "Não foi possível enviar a pergunta para Analysis.", response.status);
    }
    if (!response.body) throw new Error("O navegador não conseguiu abrir o stream da análise.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completedSession: AnalysisSession | null = null;
    let streamError: string | null = null;

    function readEvent(block: string) {
      const lines = block.split("\n");
      const eventName = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
      if (!eventName || !data) return;
      const payload = JSON.parse(data) as { text?: string; session?: AnalysisSession; detail?: string };
      if (eventName === "delta" && typeof payload.text === "string") onDelta(payload.text);
      if (eventName === "done" && payload.session) completedSession = payload.session;
      if (eventName === "error") streamError = payload.detail ?? "O modelo de análise não concluiu a resposta.";
    }

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
      let separator = buffer.indexOf("\n\n");
      while (separator >= 0) {
        readEvent(buffer.slice(0, separator));
        buffer = buffer.slice(separator + 2);
        separator = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    if (buffer.trim()) readEvent(buffer);
    if (streamError) throw new Error(streamError);
    if (!completedSession) throw new Error("O stream terminou sem confirmar a análise persistida.");
    return completedSession;
  },
};
