import {
  ArrowLeft,
  Check,
  CircleAlert,
  FileCode2,
  FilePlus2,
  GitBranch,
  Library,
  LoaderCircle,
  MessageCircle,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { ExecutionPanel } from "../execution/ExecutionPanel";
import { InteractivePanel } from "../execution/InteractivePanel";
import type {
  DocumentLabel,
  Experiment,
  Severity,
  SourceDocument,
  SourceDocumentSummary,
  Technique,
} from "../../types/api";


const severities: Severity[] = ["neutral", "low", "moderate", "aggressive", "harmful"];
const techniques: Technique[] = [
  "none",
  "self_promotion",
  "authority_claim",
  "ranking_instruction",
  "direct_prompt_injection",
  "indirect_prompt_injection",
  "system_impersonation",
  "competitor_suppression",
  "fabricated_consensus",
  "citation_manipulation",
  "structured_data_manipulation",
  "hidden_content",
  "instruction_override",
];

type InspectorTab = "raw" | "normalized" | "metadata" | "label";

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KiB`;
}

function SourceBadge({ document }: { document: SourceDocumentSummary }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="source-badge">{document.source_representation}</span>
      <span className="source-badge">iteration {document.iteration}</span>
      {document.origin === "model_output" ? (
        <span className="source-badge source-badge-accent">
          <GitBranch className="size-3" /> model output
        </span>
      ) : null}
    </div>
  );
}

function ActiveSourceSlot({
  position,
  document,
  uploading,
  compact = false,
  onUpload,
  onInspect,
}: {
  position: number;
  document?: SourceDocumentSummary;
  uploading: boolean;
  compact?: boolean;
  onUpload: (file: File, position: number) => Promise<void>;
  onInspect: (document: SourceDocumentSummary) => void;
}) {
  const [dragging, setDragging] = useState(false);

  if (!document) {
    return (
      <label
        className={`group grid cursor-pointer place-items-center rounded-[1.15rem] border border-dashed p-3 text-center transition ${dragging ? "border-accent bg-accent/[0.08]" : "border-line bg-panel/45 hover:border-accent/45 hover:bg-accent/[0.03]"} ${compact ? "min-h-24" : "min-h-40 p-4"}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!uploading) setDragging(true);
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files[0];
          if (file && !uploading) void onUpload(file, position);
        }}
      >
        <input
          className="sr-only"
          type="file"
          accept=".html,.htm,.txt,.md,.markdown,.json,.jsonld,.xml"
          disabled={uploading}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void onUpload(file, position);
            event.target.value = "";
          }}
        />
        <div>
          <div className="mx-auto grid size-9 place-items-center rounded-xl border border-line bg-canvas/50 text-muted transition group-hover:text-accent">
            {uploading ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <FilePlus2 className="size-4" />
            )}
          </div>
          <p className="mt-2 text-xs font-semibold text-ink">Slot {position}</p>
          <p className="mt-0.5 text-[0.68rem] text-muted">Adicionar fonte</p>
        </div>
      </label>
    );
  }

  return (
    <button
      type="button"
      className={`rounded-[1.15rem] border border-line bg-panel p-3 text-left transition hover:-translate-y-0.5 hover:border-accent/40 ${compact ? "min-h-24" : "min-h-40 p-4"}`}
      onClick={() => onInspect(document)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="grid size-8 place-items-center rounded-xl bg-accent-soft text-accent">
          <FileCode2 className="size-4" />
        </div>
        <span className="font-mono text-[0.58rem] uppercase tracking-[0.15em] text-muted">
          Slot {position}
        </span>
      </div>
      <p className={`${compact ? "mt-2" : "mt-4"} truncate text-sm font-semibold text-ink`}>{document.filename}</p>
      <p className="mt-1 text-[0.68rem] text-muted">
        {formatBytes(document.byte_size)} · {document.label.severity}
      </p>
      <div className="mt-2">
        <SourceBadge document={document} />
      </div>
    </button>
  );
}

function LabelEditor({
  document,
  onSave,
}: {
  document: SourceDocument;
  onSave: (label: DocumentLabel) => Promise<void>;
}) {
  const [label, setLabel] = useState(document.label);
  const [saving, setSaving] = useState(false);

  useEffect(() => setLabel(document.label), [document]);

  async function save() {
    setSaving(true);
    try {
      await onSave(label);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label>
          <span className="field-label">Severity</span>
          <select
            className="field-input"
            value={label.severity}
            onChange={(event) => setLabel({ ...label, severity: event.target.value as Severity })}
          >
            {severities.map((severity) => (
              <option key={severity}>{severity}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="field-label">Technique</span>
          <select
            className="field-input"
            value={label.technique}
            onChange={(event) => setLabel({ ...label, technique: event.target.value as Technique })}
          >
            {techniques.map((technique) => (
              <option key={technique}>{technique}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="flex items-start gap-3 rounded-xl border border-line bg-canvas/35 p-4">
        <input
          className="mt-0.5 size-4 accent-[var(--color-accent)]"
          type="checkbox"
          checked={label.expected_target}
          onChange={(event) => setLabel({ ...label, expected_target: event.target.checked })}
        />
        <span>
          <span className="flex items-center gap-2 text-sm font-semibold text-ink">
            <Target className="size-4 text-accent" /> Expected target
          </span>
          <span className="mt-1 block text-xs leading-5 text-muted">
            Ao marcar esta fonte, qualquer target anterior no acervo atual será desmarcado.
          </span>
        </span>
      </label>
      <label>
        <span className="field-label">Anotação</span>
        <textarea
          className="field-input min-h-24 resize-none"
          value={label.annotation ?? ""}
          onChange={(event) => setLabel({ ...label, annotation: event.target.value || null })}
          placeholder="Evidência ou intenção experimental desta classificação"
        />
      </label>
      <div className="flex justify-end">
        <button className="button-primary" type="button" disabled={saving} onClick={() => void save()}>
          <Check className="size-4" /> {saving ? "Salvando…" : "Salvar labels"}
        </button>
      </div>
    </div>
  );
}

function SourceIdentityEditor({
  document,
  onSave,
}: {
  document: SourceDocument;
  onSave: (
    entityKey: string | null,
    entityName: string | null,
    aliases: string[],
    counterfactualGroupKey: string | null,
  ) => Promise<void>;
}) {
  const [entityKey, setEntityKey] = useState(document.entity_key ?? "");
  const [entityName, setEntityName] = useState(document.entity_name ?? "");
  const [aliases, setAliases] = useState(document.aliases_json.join(", "));
  const [counterfactualGroupKey, setCounterfactualGroupKey] = useState(document.counterfactual_group_key ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setEntityKey(document.entity_key ?? "");
    setEntityName(document.entity_name ?? "");
    setAliases(document.aliases_json.join(", "));
    setCounterfactualGroupKey(document.counterfactual_group_key ?? "");
  }, [document]);

  async function save() {
    setSaving(true);
    try {
      await onSave(
        entityKey.trim() || null,
        entityName.trim() || null,
        aliases.split(",").map((alias) => alias.trim()).filter(Boolean),
        counterfactualGroupKey.trim() || null,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mb-5 grid gap-4 rounded-xl border border-line bg-canvas/35 p-4">
      <label>
        <span className="field-label">Chave canônica da entidade</span>
        <input className="field-input" value={entityKey} onChange={(event) => setEntityKey(event.target.value)} placeholder="Ex.: clinica-central" />
        <span className="mt-1 block text-[0.68rem] leading-4 text-muted">Use a mesma chave em todas as versões da mesma entidade; ela também ancora o scorer determinístico.</span>
      </label>
      <label>
        <span className="field-label">Nome da entidade</span>
        <input className="field-input" value={entityName} onChange={(event) => setEntityName(event.target.value)} placeholder="Nome canônico para avaliação determinística" />
      </label>
      <label>
        <span className="field-label">Aliases, separados por vírgula</span>
        <input className="field-input" value={aliases} onChange={(event) => setAliases(event.target.value)} placeholder="Ex.: Clínica Central, Central Vet" />
      </label>
      <label>
        <span className="field-label">Grupo contrafactual</span>
        <input className="field-input" value={counterfactualGroupKey} onChange={(event) => setCounterfactualGroupKey(event.target.value)} placeholder="Ex.: clinica-central-copy-v1" />
        <span className="mt-1 block text-[0.68rem] leading-4 text-muted">Repita a chave apenas entre versões da mesma fonte-alvo; configure grupo e identidade antes de marcar as variantes como expected target.</span>
      </label>
      <button type="button" className="button-secondary justify-self-start" disabled={saving} onClick={() => void save()}>
        {saving ? "Salvando…" : "Salvar identidade"}
      </button>
    </div>
  );
}

function SourceInspector({
  document,
  onClose,
  onSaveLabel,
  onSaveIdentity,
  onUnassign,
}: {
  document: SourceDocument;
  onClose: () => void;
  onSaveLabel: (label: DocumentLabel) => Promise<void>;
  onSaveIdentity: (
    entityKey: string | null,
    entityName: string | null,
    aliases: string[],
    counterfactualGroupKey: string | null,
  ) => Promise<void>;
  onUnassign: () => Promise<void>;
}) {
  const [tab, setTab] = useState<InspectorTab>("normalized");
  const tabs: { id: InspectorTab; label: string }[] = [
    { id: "raw", label: "Raw" },
    { id: "normalized", label: "Normalized" },
    { id: "metadata", label: "Metadata" },
    { id: "label", label: "Label" },
  ];

  return (
    <section className="mt-6 overflow-hidden rounded-[1.35rem] border border-line bg-panel">
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <p className="eyebrow">Source inspector</p>
          <h3 className="mt-2 truncate text-base font-semibold">{document.filename}</h3>
          <p className="mt-1 font-mono text-[0.62rem] text-muted">sha256:{document.sha256.slice(0, 16)}…</p>
        </div>
        <div className="flex gap-2">
          {document.position ? (
            <button type="button" className="button-secondary" onClick={() => void onUnassign()}>
              Remover do slot
            </button>
          ) : null}
          <button type="button" className="icon-button" aria-label="Fechar inspector" onClick={onClose}>
            <X className="size-4" />
          </button>
        </div>
      </div>
      <div className="flex gap-1 overflow-x-auto border-b border-line px-4 pt-3">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`inspector-tab ${tab === item.id ? "inspector-tab-active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="p-5">
        {tab === "raw" ? <pre className="source-code">{document.raw_content}</pre> : null}
        {tab === "normalized" ? (
          <pre className="source-code">{document.normalized_content}</pre>
        ) : null}
        {tab === "metadata" ? (
          <>
            <SourceIdentityEditor document={document} onSave={onSaveIdentity} />
            <pre className="source-code">{JSON.stringify(document.metadata_json, null, 2)}</pre>
          </>
        ) : null}
        {tab === "label" ? <LabelEditor document={document} onSave={onSaveLabel} /> : null}
      </div>
    </section>
  );
}

export function ExperimentWorkspace({
  experiment,
  onBack,
}: {
  experiment: Experiment;
  onBack: () => void;
}) {
  const [documents, setDocuments] = useState<SourceDocumentSummary[]>([]);
  const [selected, setSelected] = useState<SourceDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploadingSlot, setUploadingSlot] = useState<number | null>(null);
  const [uploadingLibrary, setUploadingLibrary] = useState(false);
  const [loadingSample, setLoadingSample] = useState(false);
  const [sampleQuestion, setSampleQuestion] = useState("");
  const [executionMode, setExecutionMode] = useState<"benchmark" | "interactive">("benchmark");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.listDocuments(experiment.id);
      setDocuments(result.items);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao carregar fontes.");
    } finally {
      setLoading(false);
    }
  }, [experiment.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const activeDocuments = useMemo(
    () => new Map(documents.filter((item) => item.position).map((item) => [item.position, item])),
    [documents],
  );
  const libraryDocuments = documents.filter((item) => item.position === null);
  const firstFreeSlot = [1, 2, 3, 4, 5].find((position) => !activeDocuments.has(position));

  async function inspect(document: SourceDocumentSummary) {
    try {
      setSelected(await api.getDocument(document.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao abrir fonte.");
    }
  }

  async function upload(file: File, position: number) {
    setUploadingSlot(position);
    setError(null);
    try {
      const created = await api.uploadDocument(experiment.id, file, position);
      setDocuments((current) => [...current, created]);
      setSelected(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha no upload.");
    } finally {
      setUploadingSlot(null);
    }
  }

  async function uploadToLibrary(file: File) {
    setUploadingLibrary(true);
    setError(null);
    try {
      const created = await api.uploadDocument(experiment.id, file);
      setDocuments((current) => [...current, created]);
      setSelected(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao adicionar fonte ao acervo.");
    } finally {
      setUploadingLibrary(false);
    }
  }

  async function saveLabel(label: DocumentLabel) {
    if (!selected) return;
    const updated = await api.updateDocumentLabel(selected.id, label);
    setSelected(updated);
    await load();
  }

  async function saveIdentity(
    entityKey: string | null,
    entityName: string | null,
    aliases: string[],
    counterfactualGroupKey: string | null,
  ) {
    if (!selected) return;
    const updated = await api.updateDocument(selected.id, {
      entity_key: entityKey,
      entity_name: entityName,
      aliases,
      counterfactual_group_key: counterfactualGroupKey,
    });
    setSelected(updated);
    await load();
  }

  async function unassignSelected() {
    if (!selected) return;
    const updated = await api.updateDocument(selected.id, { position: null });
    setSelected(updated);
    await load();
  }

  async function activate(document: SourceDocumentSummary) {
    if (!firstFreeSlot) return;
    const updated = await api.updateDocument(document.id, { position: firstFreeSlot });
    setSelected(updated);
    await load();
  }

  async function loadSamplePack() {
    setLoadingSample(true);
    setError(null);
    try {
      const availablePacks = await api.listSamplePacks();
      const pack = availablePacks[0];
      if (!pack) throw new Error("Nenhum sample está configurado.");
      const imported = await api.importSamplePack(experiment.id, pack.id);
      setDocuments(imported.documents);
      setSampleQuestion(pack.recommended_question);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha ao carregar o sample.");
    } finally {
      setLoadingSample(false);
    }
  }

  return (
    <section className="min-w-0">
      <button type="button" className="mb-5 inline-flex items-center gap-2 text-xs font-semibold text-muted hover:text-accent" onClick={onBack}>
        <ArrowLeft className="size-4" /> Voltar aos experimentos
      </button>

      <div className="flex flex-col justify-between gap-5 rounded-[1.5rem] border border-line bg-panel p-6 md:flex-row md:items-end">
        <div>
          <p className="eyebrow">Iterative source workspace</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.025em]">{experiment.name}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
            O acervo cresce a cada iteração. Escolha cinco fontes ativas para a próxima execução sem perder outputs anteriores.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-line bg-canvas/35 px-4 py-3">
          <Library className="size-4 text-accent" />
          <div>
            <p className="font-mono text-xs text-ink">{documents.length} fontes</p>
            <p className="text-[0.65rem] text-muted">{activeDocuments.size}/5 ativas</p>
          </div>
        </div>
      </div>

      {error ? (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          <CircleAlert className="size-4" /> {error}
        </div>
      ) : null}

      <div className="mt-6 inline-flex rounded-xl border border-line bg-panel p-1" aria-label="Modo de execução">
        <button
          type="button"
          className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition ${executionMode === "benchmark" ? "bg-accent text-canvas" : "text-muted hover:text-ink"}`}
          aria-pressed={executionMode === "benchmark"}
          onClick={() => setExecutionMode("benchmark")}
        >
          <Sparkles className="size-3.5" /> Benchmark
        </button>
        <button
          type="button"
          className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition ${executionMode === "interactive" ? "bg-accent text-canvas" : "text-muted hover:text-ink"}`}
          aria-pressed={executionMode === "interactive"}
          onClick={() => setExecutionMode("interactive")}
        >
          <MessageCircle className="size-3.5" /> Interactive
        </button>
      </div>

      <div className="workspace-columns mt-3">
        {executionMode === "benchmark" ? (
          <ExecutionPanel
            experimentId={experiment.id}
            documents={documents}
            activeCount={activeDocuments.size}
            targetCount={Array.from(activeDocuments.values()).filter((item) => item.label.expected_target).length}
            sampleQuestion={sampleQuestion}
            onPromoted={load}
          />
        ) : (
          <InteractivePanel
            experimentId={experiment.id}
            documents={documents}
            sampleQuestion={sampleQuestion}
          />
        )}

        <aside className="source-rail">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Execution context</p>
              <h2 className="mt-2 text-base font-semibold">Cinco fontes</h2>
            </div>
            <span className="rounded-full border border-line bg-canvas/35 px-2.5 py-1 font-mono text-[0.62rem] text-muted">
              {loading ? "…" : `${activeDocuments.size}/5`}
            </span>
          </div>

          {!documents.length ? (
            <div className="mt-4 rounded-xl border border-accent/25 bg-accent/[0.035] p-3">
              <div className="flex items-start gap-2.5">
                <Sparkles className="mt-0.5 size-4 shrink-0 text-accent" />
                <div>
                  <p className="text-xs font-semibold">Sample demonstrativo</p>
                  <p className="mt-1 text-[0.68rem] leading-4 text-muted">
                    Cinco arquivos sintéticos, com labels e um alvo esperado.
                  </p>
                </div>
              </div>
              <button type="button" className="button-secondary mt-3 w-full" disabled={loadingSample || loading} onClick={() => void loadSamplePack()}>
                {loadingSample ? <LoaderCircle className="size-4 animate-spin" /> : <Library className="size-4" />}
                {loadingSample ? "Carregando…" : "Carregar sample"}
              </button>
            </div>
          ) : null}

          <div className="mt-3 grid gap-2">
            {[1, 2, 3, 4, 5].map((position) => (
              <ActiveSourceSlot
                key={position}
                position={position}
                document={activeDocuments.get(position)}
                uploading={uploadingSlot === position}
                compact
                onUpload={upload}
                onInspect={inspect}
              />
            ))}
          </div>

          <label className="button-secondary mt-3 w-full cursor-pointer justify-center">
            {uploadingLibrary ? <LoaderCircle className="size-4 animate-spin" /> : <FilePlus2 className="size-4" />}
            {uploadingLibrary ? "Adicionando ao acervo…" : "Adicionar fonte ao acervo"}
            <input
              className="sr-only"
              type="file"
              accept=".html,.htm,.txt,.md,.markdown,.json,.jsonld,.xml"
              disabled={uploadingLibrary}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadToLibrary(file);
                event.target.value = "";
              }}
            />
          </label>

          {libraryDocuments.length ? (
            <details className="mt-4 rounded-xl border border-line bg-canvas/20 p-3">
              <summary className="cursor-pointer list-none text-xs font-semibold">
                Fontes preservadas <span className="ml-1 font-mono text-muted">{libraryDocuments.length}</span>
              </summary>
              <div className="mt-3 space-y-2">
                {libraryDocuments.map((document) => (
                  <article key={document.id} className="rounded-lg border border-line bg-panel p-3">
                    <div className="flex items-start justify-between gap-2">
                      <button className="min-w-0 text-left" type="button" onClick={() => void inspect(document)}>
                        <p className="truncate text-xs font-semibold">{document.filename}</p>
                        <p className="mt-1 text-[0.65rem] text-muted">Iteração {document.iteration} · {document.origin}</p>
                      </button>
                      {firstFreeSlot ? (
                        <button className="text-[0.68rem] font-semibold text-accent" type="button" onClick={() => void activate(document)}>
                          Ativar
                        </button>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            </details>
          ) : null}

          {selected ? (
            <SourceInspector
              document={selected}
              onClose={() => setSelected(null)}
              onSaveLabel={saveLabel}
              onSaveIdentity={saveIdentity}
              onUnassign={unassignSelected}
            />
          ) : null}
        </aside>
      </div>
    </section>
  );
}
