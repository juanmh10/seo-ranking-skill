import {
  Activity,
  Archive,
  ArrowUpRight,
  Beaker,
  Braces,
  CircleDot,
  Database,
  FileStack,
  FlaskConical,
  Plus,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { AnalysisWorkspace } from "../features/analysis/AnalysisWorkspace";
import { ExperimentWorkspace } from "../features/sources/ExperimentWorkspace";
import type { Experiment, ExperimentCreate } from "../types/api";

type LoadState = "loading" | "ready" | "error";
type AppView = "experiments" | "datasets" | "analysis";

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function ExperimentCard({
  experiment,
  onArchive,
  onOpen,
}: {
  experiment: Experiment;
  onArchive: (id: string) => Promise<void>;
  onOpen: (experiment: Experiment) => void;
}) {
  const dataset = experiment.datasets.at(-1);

  return (
    <article className="group rounded-[1.35rem] border border-line bg-panel p-5 transition hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-[0_18px_60px_rgba(4,12,24,.24)]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent">
            <FlaskConical className="size-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-[1.02rem] font-semibold text-ink">{experiment.name}</h3>
            <p className="mt-1 font-mono text-[0.68rem] uppercase tracking-[0.16em] text-muted">
              Dataset v{dataset?.version ?? 1} · {experiment.status}
            </p>
          </div>
        </div>
        <button
          type="button"
          className="icon-button opacity-0 group-hover:opacity-100 focus:opacity-100"
          aria-label={`Arquivar ${experiment.name}`}
          onClick={() => void onArchive(experiment.id)}
        >
          <Archive className="size-4" aria-hidden="true" />
        </button>
      </div>

      <p className="mt-5 line-clamp-2 min-h-10 text-sm leading-5 text-muted">
        {experiment.description || "Sem descrição. Pronto para receber as cinco fontes do cenário."}
      </p>

      <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
        <span className="text-xs text-muted">Atualizado {formatDate(experiment.updated_at)}</span>
        <button
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent"
          type="button"
          onClick={() => onOpen(experiment)}
        >
          Abrir workspace
          <ArrowUpRight className="size-3.5" aria-hidden="true" />
        </button>
      </div>
    </article>
  );
}

function CreateExperimentForm({
  onCreate,
  onCancel,
}: {
  onCreate: (payload: ExperimentCreate) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({ name, description: description || undefined });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao criar experimento.");
      setSubmitting(false);
    }
  }

  return (
    <form className="rounded-[1.5rem] border border-accent/35 bg-panel p-6 shadow-[0_24px_80px_rgba(0,0,0,.22)]" onSubmit={submit}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Novo estudo</p>
          <h2 className="mt-2 text-xl font-semibold text-ink">Crie a base do experimento</h2>
        </div>
        <span className="rounded-full border border-accent/30 bg-accent-soft px-3 py-1 font-mono text-[0.65rem] uppercase tracking-wider text-accent">
          Draft
        </span>
      </div>

      <label className="mt-6 block">
        <span className="field-label">Nome</span>
        <input
          autoFocus
          required
          maxLength={160}
          className="field-input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Ex.: Recomendações de clínicas veterinárias"
        />
      </label>

      <label className="mt-4 block">
        <span className="field-label">Descrição</span>
        <textarea
          maxLength={4000}
          className="field-input min-h-24 resize-none"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Qual comportamento será investigado?"
        />
      </label>

      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

      <div className="mt-6 flex justify-end gap-3">
        <button type="button" className="button-secondary" onClick={onCancel}>
          Cancelar
        </button>
        <button type="submit" className="button-primary" disabled={submitting || !name.trim()}>
          {submitting ? "Criando…" : "Criar experimento"}
        </button>
      </div>
    </form>
  );
}

function DatasetOverview({
  experiments,
  onOpen,
}: {
  experiments: Experiment[];
  onOpen: (experiment: Experiment) => void;
}) {
  return (
    <section className="min-w-0">
      <div className="rounded-[1.5rem] border border-line bg-panel p-6">
        <p className="eyebrow">Source library</p>
        <h1 className="mt-2 text-2xl font-semibold">Datasets incrementais</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          Cada experimento mantém versões do acervo. Abra o workspace para adicionar fontes individualmente, carregar samples e escolher quais cinco entram no próximo benchmark.
        </p>
      </div>
      {!experiments.length ? (
        <p className="mt-5 rounded-xl border border-dashed border-line bg-panel/45 p-6 text-sm text-muted">Nenhum dataset disponível.</p>
      ) : (
        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {experiments.map((experiment) => {
            const dataset = experiment.datasets.at(-1);
            return (
              <article key={experiment.id} className="rounded-[1.25rem] border border-line bg-panel p-5">
                <p className="eyebrow">{dataset?.status ?? "draft"} · v{dataset?.version ?? 1}</p>
                <h2 className="mt-2 text-base font-semibold">{dataset?.name ?? experiment.name}</h2>
                <p className="mt-1 text-xs text-muted">Experimento: {experiment.name}</p>
                <button type="button" className="button-secondary mt-5" onClick={() => onOpen(experiment)}>
                  <Database className="size-4" /> Gerenciar acervo
                </button>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function App() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [dashboardTotals, setDashboardTotals] = useState({ completedRuns: 0, activeSources: 0 });
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [backendReady, setBackendReady] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedExperiment, setSelectedExperiment] = useState<Experiment | null>(null);
  const [activeView, setActiveView] = useState<AppView>("experiments");

  const load = useCallback(async () => {
    try {
      const [health, result] = await Promise.all([api.health(), api.listExperiments()]);
      const totals = await Promise.all(result.items.map(async (experiment) => {
        const [sources, configs] = await Promise.all([
          api.listDocuments(experiment.id),
          api.listRunConfigs(experiment.id),
        ]);
        return {
          completedRuns: configs.reduce(
            (count, config) => count + config.runs.filter((run) => run.status === "completed").length,
            0,
          ),
          activeSources: sources.active_count,
        };
      }));
      setBackendReady(health.status === "ok" && health.database === "ok");
      setExperiments(result.items);
      setDashboardTotals({
        completedRuns: totals.reduce((count, item) => count + item.completedRuns, 0),
        activeSources: totals.reduce((count, item) => count + item.activeSources, 0),
      });
      setLoadState("ready");
    } catch {
      setBackendReady(false);
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(
    () => [
      { label: "Experimentos", value: experiments.length.toString().padStart(2, "0"), icon: Beaker },
      { label: "Runs completos", value: dashboardTotals.completedRuns.toString().padStart(2, "0"), icon: Activity },
      { label: "Fontes ativas", value: dashboardTotals.activeSources.toString().padStart(2, "0"), icon: FileStack },
    ],
    [experiments.length, dashboardTotals],
  );

  async function createExperiment(payload: ExperimentCreate) {
    const experiment = await api.createExperiment(payload);
    setExperiments((current) => [experiment, ...current]);
    setShowCreate(false);
  }

  async function archiveExperiment(id: string) {
    await api.archiveExperiment(id);
    await load();
  }

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="sticky top-0 z-30 border-b border-line/80 bg-canvas/90 backdrop-blur-xl">
        <div className="mx-auto flex h-[4.5rem] max-w-[1600px] items-center justify-between px-5 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl bg-accent text-canvas shadow-[0_0_35px_rgba(117,240,194,.18)]">
              <Braces className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-sm font-semibold leading-none">Source Manipulation Lab</p>
              <p className="mt-1.5 font-mono text-[0.58rem] uppercase tracking-[0.22em] text-muted">Research console · v0.1</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 sm:flex">
              <span className={`size-1.5 rounded-full ${backendReady ? "bg-accent shadow-[0_0_9px_var(--color-accent)]" : "bg-danger"}`} />
              <span className="font-mono text-[0.62rem] uppercase tracking-[0.14em] text-muted">
                {backendReady ? "System ready" : "Backend offline"}
              </span>
            </div>
            <button className="button-primary" type="button" onClick={() => setShowCreate(true)}>
              <Plus className="size-4" aria-hidden="true" />
              Novo experimento
            </button>
          </div>
        </div>
      </header>

      <main className={`mx-auto grid max-w-[1800px] gap-8 px-5 py-8 lg:px-8 lg:py-10 ${selectedExperiment ? "grid-cols-1" : "lg:grid-cols-[250px_minmax(0,1fr)]"}`}>
        {!selectedExperiment ? <aside className="app-sidebar space-y-2">
          <p className="mb-4 px-3 font-mono text-[0.62rem] uppercase tracking-[0.18em] text-muted">Workspace</p>
          <button className={`nav-item ${activeView === "experiments" ? "nav-item-active" : ""}`} type="button" onClick={() => { setSelectedExperiment(null); setActiveView("experiments"); }}>
            <FlaskConical className="size-4" /> Experimentos
          </button>
          <button className={`nav-item ${activeView === "datasets" ? "nav-item-active" : ""}`} type="button" onClick={() => { setSelectedExperiment(null); setActiveView("datasets"); }}>
            <Database className="size-4" /> Datasets
          </button>
          <button className={`nav-item ${activeView === "analysis" ? "nav-item-active" : ""}`} type="button" onClick={() => { setSelectedExperiment(null); setActiveView("analysis"); }}>
            <Sparkles className="size-4" /> Analysis
          </button>

          <div className="mt-8 rounded-2xl border border-line bg-panel/60 p-4">
            <div className="flex items-center gap-2 text-accent">
              <ShieldCheck className="size-4" />
              <span className="text-xs font-semibold">Execution boundary</span>
            </div>
            <p className="mt-3 text-xs leading-5 text-muted">
              Labels e ground truth permanecem fora do contexto do modelo avaliado.
            </p>
          </div>
        </aside> : null}

        {selectedExperiment ? (
          <ExperimentWorkspace
            experiment={selectedExperiment}
            onBack={() => {
              setSelectedExperiment(null);
              setActiveView("experiments");
              void load();
            }}
          />
        ) : activeView === "analysis" ? (
          <AnalysisWorkspace
            experiments={experiments}
            onBack={() => setActiveView("experiments")}
          />
        ) : activeView === "datasets" ? (
          <DatasetOverview
            experiments={experiments}
            onOpen={(experiment) => {
              setSelectedExperiment(experiment);
              setActiveView("experiments");
            }}
          />
        ) : (
          <section className="min-w-0">
          <div className="relative overflow-hidden rounded-[1.75rem] border border-line bg-panel px-6 py-7 md:px-8">
            <div className="pointer-events-none absolute -right-24 -top-28 size-72 rounded-full bg-accent/[0.07] blur-3xl" />
            <div className="relative flex flex-col justify-between gap-8 xl:flex-row xl:items-end">
              <div className="max-w-2xl">
                <p className="eyebrow">Benchmark workspace</p>
                <h1 className="mt-3 text-3xl font-semibold tracking-[-0.035em] md:text-[2.6rem] md:leading-[1.08]">
                  Meça quando uma fonte começa a <span className="text-accent">mudar a resposta.</span>
                </h1>
                <p className="mt-4 max-w-xl text-sm leading-6 text-muted md:text-base">
                  Compare modelos, formatos e técnicas de manipulação com execuções isoladas e resultados auditáveis.
                </p>
              </div>

              <div className="grid grid-cols-3 gap-2">
                {stats.map(({ label, value, icon: Icon }) => (
                  <div key={label} className="min-w-24 rounded-2xl border border-line bg-canvas/45 px-4 py-3">
                    <div className="flex items-center justify-between gap-3 text-muted">
                      <span className="font-mono text-[0.56rem] uppercase tracking-[0.13em]">{label}</span>
                      <Icon className="size-3.5" />
                    </div>
                    <p className="mt-3 font-mono text-xl text-ink">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-8 flex items-end justify-between gap-4">
            <div>
              <p className="eyebrow">Recentes</p>
              <h2 className="mt-2 text-xl font-semibold">Experimentos</h2>
            </div>
            <span className="font-mono text-[0.65rem] uppercase tracking-[0.13em] text-muted">
              {experiments.length} ativos
            </span>
          </div>

          {showCreate ? (
            <div className="mt-5">
              <CreateExperimentForm onCreate={createExperiment} onCancel={() => setShowCreate(false)} />
            </div>
          ) : null}

          {loadState === "loading" ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Carregando experimentos">
              {[0, 1, 2].map((item) => (
                <div key={item} className="h-56 animate-pulse rounded-[1.35rem] border border-line bg-panel" />
              ))}
            </div>
          ) : null}

          {loadState === "error" ? (
            <div className="mt-5 rounded-[1.35rem] border border-danger/30 bg-danger/5 p-6">
              <div className="flex items-center gap-2 text-danger">
                <CircleDot className="size-4" />
                <p className="font-semibold">A API ainda não está disponível.</p>
              </div>
              <p className="mt-2 text-sm text-muted">Inicie o backend e tente reconectar.</p>
              <button type="button" className="button-secondary mt-5" onClick={() => void load()}>
                Tentar novamente
              </button>
            </div>
          ) : null}

          {loadState === "ready" && experiments.length === 0 ? (
            <div className="mt-5 grid min-h-72 place-items-center rounded-[1.35rem] border border-dashed border-line bg-panel/45 p-8 text-center">
              <div>
                <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent">
                  <Beaker className="size-5" />
                </div>
                <h3 className="mt-4 font-semibold">Seu laboratório está vazio</h3>
                <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted">
                  Crie o primeiro experimento para preparar o dataset e as cinco fontes do benchmark.
                </p>
                <button className="button-primary mt-5" type="button" onClick={() => setShowCreate(true)}>
                  <Plus className="size-4" /> Criar primeiro experimento
                </button>
              </div>
            </div>
          ) : null}

          {loadState === "ready" && experiments.length > 0 ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {experiments.map((experiment) => (
                <ExperimentCard
                  key={experiment.id}
                  experiment={experiment}
                  onArchive={archiveExperiment}
                  onOpen={setSelectedExperiment}
                />
              ))}
            </div>
          ) : null}
          </section>
        )}
      </main>
    </div>
  );
}
