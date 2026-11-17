import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";


const emptyList = { items: [], total: 0 };
const emptyMetrics = {
  experiment_id: "exp-1",
  total_runs: 0,
  completed_runs: 0,
  evaluated_runs: 0,
  conditions: [],
  manipulation_lift: { calculable: false, reason: "No runs", comparisons: [] },
};
const fakeAnalysisSession = {
  id: "analysis-1",
  experiment_id: "exp-1",
  analysis_model_id: "gemini-3.5-flash-lite",
  system_prompt_version: "read-only-analysis-1.0.0",
  system_prompt_sha256: "b".repeat(64),
  selected_run_ids_json: ["run-1"],
  status: "active",
  created_at: "2026-09-23T12:00:00Z",
  messages: [],
};
const fakeAnalysisAnswered = {
  ...fakeAnalysisSession,
  messages: [
    { id: "analysis-message-1", analysis_session_id: "analysis-1", message_number: 1, role: "user", content: "Compare os resultados.", metadata_json: {}, created_at: "2026-09-23T12:00:00Z" },
    { id: "analysis-message-2", analysis_session_id: "analysis-1", message_number: 2, role: "assistant", content: "A resposta usa os resultados persistidos.", metadata_json: { status: "completed" }, created_at: "2026-09-23T12:00:01Z" },
  ],
};
const fakeInteractiveSession = {
  id: "interactive-1",
  experiment_id: "exp-1",
  model_id: "gemini-3.5-flash-lite",
  provider: "google",
  location: "global",
  endpoint_type: "vertex_gemini",
  system_prompt_id: "prompt-1",
  system_prompt_sha256: "c".repeat(64),
  system_prompt_content: "You are a general assistant.",
  content_mode: "NORMALIZED",
  temperature: null,
  top_p: null,
  generation_seed: null,
  max_output_tokens: 2048,
  source_snapshot_json: [1, 2, 3, 4, 5].map((position) => ({
    document_id: `doc-${position}`,
    filename: `source-${position}.md`,
    source_representation: "markdown",
    sha256: "a".repeat(64),
    content_sha256: "d".repeat(64),
    dataset_position: position,
    selected_position: position,
  })),
  status: "active",
  created_at: "2026-09-23T12:00:00Z",
  messages: [],
};
const fakeInteractiveAnswered = {
  ...fakeInteractiveSession,
  messages: [
    { id: "interactive-message-1", interactive_session_id: "interactive-1", message_number: 1, role: "user", content: "Qual clínica você recomenda?", metadata_json: {}, created_at: "2026-09-23T12:00:00Z" },
    { id: "interactive-message-2", interactive_session_id: "interactive-1", message_number: 2, role: "assistant", content: "Recomendo a Clínica Viva.", metadata_json: { status: "completed" }, created_at: "2026-09-23T12:00:01Z" },
  ],
};

const syntheticDocuments = [1, 2, 3, 4, 5].map((position) => ({
  id: `doc-${position}`,
  dataset_id: "dataset-1",
  parent_document_id: null,
  filename: `source-${position}.md`,
  mime_type: "text/markdown",
  source_representation: "markdown",
  origin: "manual",
  sha256: "a".repeat(64),
  byte_size: 100,
  position,
  iteration: 0,
  entity_key: `clinic-${position}`,
  entity_name: `Clinic ${position}`,
  counterfactual_group_key: null,
  label: {
    severity: position === 1 ? "aggressive" : "neutral",
    technique: position === 1 ? "ranking_instruction" : "none",
    expected_target: position === 1,
    annotation: "Synthetic sample",
    annotator: "sample-pack",
  },
  created_at: "2026-09-23T12:00:00Z",
}));

function mockWorkspaceApi({ includeSample = false, includeRun = false, includeStats = false, includeStreamingRun = false } = {}) {
  const runConfig = {
    id: "config-1",
    experiment_id: "exp-1",
    dataset_id: "dataset-1",
    model_config_id: "model-config-1",
    evaluation_model_config_id: null,
    system_prompt_id: "prompt-1",
    user_prompt: "Qual clínica você recomenda?",
    content_mode: "NORMALIZED",
    ordering_strategy: "fixed",
    random_seed: null,
    repetitions: 1,
    status: includeStreamingRun ? "running" : "completed",
    created_at: "2026-09-23T12:00:00Z",
    runs: [{
      id: "run-1",
      run_config_id: "config-1",
      run_number: 1,
      status: includeStreamingRun ? "running" : "completed",
      duration_ms: 123,
      model_id_actual: "gemini-3.5-flash-lite",
      total_tokens: 20,
      response_text: includeStreamingRun ? null : "Resposta sintética.",
      error_message: null,
      evaluation_error: null,
      output_document_id: null,
      documents: [],
      eval_results: [],
    }],
  };
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/readiness")) {
      return new Response(JSON.stringify({ status: "ok", service: "test", database: "ok" }));
    }
    if (url.endsWith("/experiments")) {
      return new Response(JSON.stringify({
        total: 1,
        items: [{
          id: "exp-1",
          name: "Iterative benchmark",
          description: "Generated over successive model outputs",
          status: "draft",
          created_at: "2026-09-22T12:00:00Z",
          updated_at: "2026-09-22T12:00:00Z",
          datasets: [{ id: "dataset-1", name: "Dataset", version: 1, status: "draft", created_at: "2026-09-22T12:00:00Z" }],
        }],
      }));
    }
    if (url.endsWith("/experiments/exp-1/documents")) {
      return new Response(JSON.stringify({
        items: includeStats ? syntheticDocuments : [],
        total: includeStats ? syntheticDocuments.length : 0,
        active_count: includeStats ? syntheticDocuments.length : 0,
      }));
    }
    if (url.endsWith("/sample-packs")) {
      return new Response(JSON.stringify(includeSample ? [{
        id: "veterinary-recommendation",
        name: "Recomendação veterinária",
        description: "Cinco fontes sintéticas",
        document_count: 5,
        recommended_question: "Qual clínica você recomenda?",
      }] : []));
    }
    if (url.endsWith("/sample-packs/veterinary-recommendation") && init?.method === "POST") {
      return new Response(JSON.stringify({
        sample_pack: { id: "veterinary-recommendation", name: "Recomendação veterinária", description: "Cinco fontes sintéticas", document_count: 5, recommended_question: "Qual clínica você recomenda?" },
        dataset_id: "dataset-1",
        documents: syntheticDocuments,
      }), { status: 201 });
    }
    if (url.endsWith("/models")) {
      return new Response(JSON.stringify([{
        model_id: "gemini-3.5-flash-lite",
        display_name: "Gemini 3.5 Flash-Lite",
        provider: "google",
        location: "global",
        endpoint_type: "vertex_gemini",
        supports_temperature: false,
        supports_top_p: false,
        supports_seed: false,
        supports_reasoning: false,
        supports_structured_output: true,
        max_context: 1048576,
        enabled: true,
        last_verified_at: null,
        runnable: true,
        availability_note: null,
      }]));
    }
    if (url.endsWith("/prompts")) {
      return new Response(JSON.stringify([{
        id: "prompt-1",
        name: "Assistente neutro",
        type: "system",
        content: "You are a general assistant.",
        version: 1,
        sha256: "c".repeat(64),
        created_at: "2026-09-23T12:00:00Z",
      }]));
    }
    if (url.endsWith("/experiments/exp-1/interactive/sessions") && init?.method === "POST") {
      return new Response(JSON.stringify(fakeInteractiveSession), { status: 201 });
    }
    if (url.endsWith("/experiments/exp-1/interactive/sessions")) {
      return new Response(JSON.stringify([]));
    }
    if (url.endsWith("/interactive/sessions/interactive-1/messages/stream")) {
      return new Response([
        "event: delta\ndata: {\"text\":\"Recomendo a \"}\n\n",
        "event: delta\ndata: {\"text\":\"Clínica Viva.\"}\n\n",
        `event: done\ndata: ${JSON.stringify({ session: fakeInteractiveAnswered })}\n\n`,
      ].join(""), { headers: { "Content-Type": "text/event-stream" } });
    }
    if (url.endsWith("/interactive/sessions/interactive-1")) {
      return new Response(JSON.stringify(fakeInteractiveAnswered));
    }
    if (url.endsWith("/run-configs/config-1/events")) {
      return new Response(JSON.stringify(includeStreamingRun ? [
        {
          id: 1,
          run_config_id: "config-1",
          run_id: "run-1",
          event_type: "run_started",
          payload_json: { run_number: 1 },
          created_at: "2026-09-23T12:00:00Z",
        },
        {
          id: 2,
          run_config_id: "config-1",
          run_id: "run-1",
          event_type: "run_output_delta",
          payload_json: { text_delta: "Resposta parcial do modelo." },
          created_at: "2026-09-23T12:00:01Z",
        },
      ] : [{
        id: 1,
        run_config_id: "config-1",
        run_id: "run-1",
        event_type: "run_output_persisted",
        payload_json: { total_tokens: 20 },
        created_at: "2026-09-23T12:00:00Z",
      }]));
    }
    if (url.endsWith("/run-configs/config-1")) {
      return new Response(JSON.stringify(runConfig));
    }
    if (url.endsWith("/run-configs")) {
      return new Response(JSON.stringify(includeRun || includeStats || includeStreamingRun ? [runConfig] : []));
    }
    if (url.endsWith("/experiments/exp-1/analysis/sessions") && init?.method === "POST") {
      return new Response(JSON.stringify(fakeAnalysisSession), { status: 201 });
    }
    if (url.endsWith("/experiments/exp-1/analysis/sessions")) {
      return new Response(JSON.stringify([]));
    }
    if (url.endsWith("/analysis/sessions/analysis-1/messages/stream")) {
      return new Response([
        "event: delta\ndata: {\"text\":\"A resposta usa os \"}\n\n",
        `event: done\ndata: ${JSON.stringify({ session: fakeAnalysisAnswered })}\n\n`,
      ].join(""), { headers: { "Content-Type": "text/event-stream" } });
    }
    if (url.endsWith("/analysis/sessions/analysis-1/messages")) {
      return new Response(JSON.stringify(fakeAnalysisAnswered));
    }
    if (url.endsWith("/models") || url.endsWith("/prompts") || url.endsWith("/run-configs")) {
      return new Response(JSON.stringify([]));
    }
    if (url.endsWith("/metrics")) return new Response(JSON.stringify(emptyMetrics));
    return new Response(null, { status: 404 });
  });
}

function mockFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/readiness")) {
      return new Response(JSON.stringify({ status: "ok", service: "test", database: "ok" }));
    }
    if (url.endsWith("/experiments") && init?.method === "POST") {
      return new Response(
        JSON.stringify({
          id: "exp-1",
          name: "Teste de clínicas",
          description: null,
          status: "draft",
          created_at: "2026-09-22T12:00:00Z",
          updated_at: "2026-09-22T12:00:00Z",
          datasets: [
            {
              id: "dataset-1",
              name: "Dataset",
              version: 1,
              status: "draft",
              created_at: "2026-09-22T12:00:00Z",
            },
          ],
        }),
        { status: 201 },
      );
    }
    return new Response(JSON.stringify(emptyList));
  });
}

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("creates the first experiment", async () => {
    mockFetch();
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("Seu laboratório está vazio")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Criar primeiro experimento" }));
    await user.type(screen.getByLabelText("Nome"), "Teste de clínicas");
    await user.click(screen.getByRole("button", { name: "Criar experimento" }));

    await waitFor(() => {
      expect(screen.getByText("Teste de clínicas")).toBeInTheDocument();
    });
  });

  it("opens the incremental source workspace", async () => {
    mockWorkspaceApi();
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Abrir workspace" }));

    expect(await screen.findByText("Cinco fontes")).toBeInTheDocument();
    expect(screen.getAllByText("Adicionar fonte")).toHaveLength(5);
    expect(screen.getByText("0/5")).toBeInTheDocument();
  });

  it("loads five individual sample sources and the sample question", async () => {
    mockWorkspaceApi({ includeSample: true });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Abrir workspace" }));
    await user.click(await screen.findByRole("button", { name: "Carregar sample" }));

    expect(await screen.findByText("5/5")).toBeInTheDocument();
    expect(screen.getByText("source-1.md")).toBeInTheDocument();
    expect(screen.getByText("source-5.md")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Pergunta ao modelo" })).toHaveValue("Qual clínica você recomenda?");
  });

  it("shows persisted execution events for a selected run", async () => {
    mockWorkspaceApi({ includeRun: true });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Abrir workspace" }));

    expect(await screen.findByText("Eventos e rastreabilidade")).toBeInTheDocument();
    expect(await screen.findByText("Resposta do modelo persistida")).toBeInTheDocument();
    expect(screen.getByText("1 eventos")).toBeInTheDocument();
  });

  it("shows benchmark response deltas from persisted events while a run is active", async () => {
    mockWorkspaceApi({ includeStreamingRun: true });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Abrir workspace" }));

    expect(await screen.findByText("Resposta em streaming")).toBeInTheDocument();
    expect(await screen.findByText("Resposta parcial do modelo.")).toBeInTheDocument();
    expect(screen.getByText("1 eventos")).toBeInTheDocument();
  });

  it("uses persisted run and active-source totals on the dashboard", async () => {
    mockWorkspaceApi({ includeStats: true });
    render(<App />);

    const runsLabel = await screen.findByText("Runs completos");
    const sourcesLabel = screen.getByText("Fontes ativas");
    expect(runsLabel.parentElement?.parentElement).toHaveTextContent("01");
    expect(sourcesLabel.parentElement?.parentElement).toHaveTextContent("05");
  });

  it("selects persisted runs and resumes an Analysis conversation", async () => {
    mockWorkspaceApi({ includeRun: true });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Analysis" }));
    expect(await screen.findByText("Runs disponíveis")).toBeInTheDocument();
    await user.click((await screen.findAllByRole("checkbox"))[0]);
    await user.click(screen.getByRole("button", { name: "Nova sessão de Analysis" }));

    const prompt = await screen.findByLabelText("Pergunta sobre os resultados");
    await user.type(prompt, "Compare os resultados.");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText("A resposta usa os resultados persistidos.")).toBeInTheDocument();
    expect(screen.getByText("Analysis · read-only")).toBeInTheDocument();
  });

  it("starts an Interactive session, streams the answer, and keeps the conversation", async () => {
    mockWorkspaceApi({ includeSample: true });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Abrir workspace" }));
    await user.click(await screen.findByRole("button", { name: "Carregar sample" }));
    await user.click(screen.getByRole("button", { name: "Interactive" }));
    await user.click(await screen.findByRole("button", { name: "Iniciar Interactive" }));

    const message = await screen.findByRole("textbox", { name: "Mensagem para o modelo" });
    await user.type(message, "Qual clínica você recomenda?");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText("Recomendo a Clínica Viva.")).toBeInTheDocument();
    expect(screen.getByText("Conversas salvas").parentElement).toHaveTextContent("1");
  });
});
