# SEO & GEO Ranking Skill + LLM Source Manipulation Benchmark

Repositório com a skill **`geo-llm-ranking`** pronta para uso e distribuição, acompanhada do benchmark experimental (**LLM Source Manipulation Benchmark**), estudos empíricos com 46 execuções contrafactuais e suíte de auditoria/CI.

## 1. Skill `geo-llm-ranking` (pronta para shipping)

A skill codifica o padrão **Winning Candidate** validado empiricamente para estruturar páginas de produto, serviço ou documentação visando recomendação #1 em buscas e sínteses de LLMs (Gemini, ChatGPT, Claude, Perplexity).

- **Diretório da skill**: [`.agents/skills/geo-llm-ranking/`](./.agents/skills/geo-llm-ranking/SKILL.md)
  - [`SKILL.md`](./.agents/skills/geo-llm-ranking/SKILL.md) — regras empíricas, workflow em 5 etapas e anti-padrões.
  - [`resources/winning-candidate-template.md`](./.agents/skills/geo-llm-ranking/resources/winning-candidate-template.md) — template estrutural de 5 blocos.
  - [`examples/winning-vs-losing-examples.md`](./.agents/skills/geo-llm-ranking/examples/winning-vs-losing-examples.md) — comparativos reais de padrões vencedores vs. perdedores.
  - [`scripts/validate_geo_candidate.py`](./.agents/skills/geo-llm-ranking/scripts/validate_geo_candidate.py) — validador automático de densidade factual, tabela de especificações, âncora comercial e detecção de prompt injection / superlativos vazios.
- **Pacote pronto para download/instalação**: [`packages/geo-llm-ranking-skill.zip`](./packages/geo-llm-ranking-skill.zip)

### Uso rápido do validador da skill

```bash
python3 .agents/skills/geo-llm-ranking/scripts/validate_geo_candidate.py path/to/content.md
```

Para regerar ou verificar a integridade do arquivo `.zip` em relação à pasta da skill:

```bash
python3 scripts/package_skill.py
python3 scripts/package_skill.py --check
```

---

## 2. Evals e resultados empíricos

Os artefatos completos dos estudos executados estão versionados em [`evals/`](./evals):

- **Estudo contrafactual (16 runs em 3 modelos Gemini — 3.5 Flash-Lite, 3.8 Flash e 3.1 Pro)**:
  - Relatório e guia de reprodução: [`evals/counterfactual-study/RELATORIO_RESULTADOS_E_REPRODUCAO.md`](./evals/counterfactual-study/RELATORIO_RESULTADOS_E_REPRODUCAO.md)
  - Análise comparativa: [`evals/counterfactual-study/BLOG_SEO_PARA_CHATBOTS_E_LLMS.md`](./evals/counterfactual-study/BLOG_SEO_PARA_CHATBOTS_E_LLMS.md)
  - Síntese analítica: [`evals/counterfactual-study/analysis-agent-synthesis.md`](./evals/counterfactual-study/analysis-agent-synthesis.md)
  - Métricas e manifest auditável: [`metrics.json`](./evals/counterfactual-study/metrics.json) e [`manifest.json`](./evals/counterfactual-study/manifest.json)
- **Estudo multi-nicho (30 evals em 10 nichos de mercado — Gemini 3.5 Flash-Lite e 3.8 Flash)**:
  - Resumo consolidado: [`evals/30-niche-evals/RESUMO_30_EVALS.md`](./evals/30-niche-evals/RESUMO_30_EVALS.md)
  - Resultados e amostras sintéticas: [`results_30_evals.json`](./evals/30-niche-evals/results_30_evals.json), [`samples_batch_1.json`](./evals/30-niche-evals/samples_batch_1.json), [`samples_batch_2.json`](./evals/30-niche-evals/samples_batch_2.json)

**Resumo dos achados:**
- **SEO Estruturado / GEO**: **100% de seleção no topo** nos estudos controlados, mantendo `source_grounding = 1.0` e `unsupported_claim_rate = 0.0`.
- **Texto institucional vago (controle neutro)**: **0% de seleção** em todos os modelos testados.
- **Autopromoção superlativa sem lastro técnico**: **0% de seleção**; modelos descartam ou criticam adjetivos não comprovados.
- **Prompt injection direto**: rejeitado por `gemini-3.8-flash` e `gemini-3.1-pro-preview`, com sinalização explícita de manipulação (`injection_awareness = 1.0`) no modelo Pro.

---

## 3. Aplicação de Benchmark (Backend + Frontend)

Aplicação de pesquisa para medir como conteúdo estruturado ou manipulativo em fontes altera respostas, seleções e rankings de modelos de linguagem.

### Fluxo principal

- Crie um experimento e importe o sample pack sintético (`veterinary-recommendation`) em [`examples/`](./examples/README.md) ou envie fontes próprias (HTML, Markdown, TXT, JSON, JSON-LD, XML).
- Configure slots (5 fontes ativas para benchmark), entidades, aliases e labels experimentais (mantidos fora do contexto do modelo avaliado).
- Execute benchmarks com sessões isoladas por repetição, streaming via SSE, scorers determinísticos (`deterministic-1.1.0`) e LLM Judge opcional (`llm-judge-1.1.0` com 8 métricas).
- Consulte **Manipulation Lift** e `rank_delta` em pares contrafactuais compatíveis, além dos modos **Interactive** e **Analysis**.

### Modelos e infraestrutura

O catálogo inicial em [`.env.example`](./.env.example) inclui modelos Gemini (Vertex AI via ADC), Claude 5 (Vertex Model Garden) e Grok 4.7 (`APP_XAI_API_KEY` apenas no backend). Detalhes de configuração GCP, ADC e menor privilégio IAM estão em [`docs/infrastructure.md`](./docs/infrastructure.md).

### Preparação e execução local

```bash
cp .env.example .env
# Defina APP_GCP_PROJECT (e APP_XAI_API_KEY, se aplicável) no .env

python3 -m venv .venv
.venv/bin/pip install -e './backend[dev,model]'
pnpm --dir frontend install

.venv/bin/alembic upgrade head
```

Em terminais separados:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
pnpm --dir frontend dev
```

- API: `http://127.0.0.1:8000` (OpenAPI em `/docs`)
- Frontend: `http://127.0.0.1:5173`

Para reproduzir os estudos via CLI (requer `.env` e ADC configurados):

```bash
.venv/bin/python scripts/run_seo_eval_study.py
.venv/bin/python scripts/run_30_evals_study.py
```

---

## 4. Verificações, auditorias e CI

O workflow em [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) executa automaticamente:
- **Gitleaks**: varredura de segredos no histórico Git e no diretório de trabalho.
- **Auditoria de skill, pacote e higiene**: `scripts/audit_repo.py` e `scripts/package_skill.py --check`.
- **Backend**: `ruff`, `pytest`, `bandit` e `pip-audit`.
- **Frontend**: `eslint`, `vitest`, `tsc`/`vite build` e `pnpm audit`.

Execução local:

```bash
.venv/bin/pytest backend/tests -q
.venv/bin/ruff check backend/app backend/tests scripts .agents/skills/geo-llm-ranking/scripts
pnpm --dir frontend test
pnpm --dir frontend lint
pnpm --dir frontend build
python3 scripts/package_skill.py --check
python3 scripts/audit_repo.py
```
