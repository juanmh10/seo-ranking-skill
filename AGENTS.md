# AGENTS.md

Documentação técnica e instruções operacionais deste repositório, baseadas exclusivamente na arquitetura, nos scripts e nas validações do projeto.

## Fontes de referência do projeto

- **Especificação do benchmark**: [`LLM_SOURCE_MANIPULATION_SPEC.md`](./LLM_SOURCE_MANIPULATION_SPEC.md) — baseline técnica de arquitetura, domínio, APIs, persistência, métricas e fluxos.
- **Skill de GEO / LLM Ranking**: [`.agents/skills/geo-llm-ranking/SKILL.md`](./.agents/skills/geo-llm-ranking/SKILL.md) — estrutura validada de conteúdo (*Winning Candidate*), anti-padrões e script de validação.

## Estrutura do repositório

- `.agents/skills/geo-llm-ranking/` — skill pronta para uso/distribuição (`SKILL.md`, `examples/`, `resources/`, `scripts/validate_geo_candidate.py`).
- `packages/` — pacote `.zip` pronto para shipping da skill (`geo-llm-ranking-skill.zip`), gerado de forma reproduzível a partir de `.agents/skills/geo-llm-ranking/`.
- `evals/` — estudos empíricos e artefatos de avaliação versionados (`counterfactual-study/` e `30-niche-evals/`).
- `backend/` — API FastAPI, serviços de domínio, modelos SQLAlchemy/Alembic, adapters de provedores e suíte `pytest`.
- `frontend/` — aplicação React/Vite/TypeScript e testes Vitest.
- `migrations/` — migrações Alembic para SQLite (`aiosqlite`).
- `examples/` — sample packs sintéticos e fictícios para uso no benchmark.
- `docs/` — documentação de infraestrutura e configuração de provedores.
- `scripts/` — scripts de reprodução dos estudos, empacotamento da skill e auditoria do repositório.
- `input/`, `output/`, `deprecated/`, `trash/`, `data/` — diretórios locais ignorados pelo Git (exceto `.gitkeep`).

## Invariantes técnicas e de segurança

- **Credenciais e dados sensíveis**: nunca versionar `.env`, chaves, tokens, bancos SQLite (`*.db`), caminhos locais absolutos ou dados privados. Credenciais e ADC permanecem exclusivamente no backend.
- **Desacoplamento de domínio**: manter o núcleo de pesquisa (`backend/app/domain/` e `backend/app/services/`) desacoplado dos adapters de provedores (`backend/app/providers/`).
- **Isolamento de contextos**: preservar a separação entre execução do modelo avaliado (sem labels ou ground truth no contexto), avaliação (scorers determinísticos e LLM judge) e análise (somente leitura sobre runs e métricas persistidos).
- **Reprodutibilidade**: runs persistidos registram hashes SHA-256, ordem das fontes, seeds, parâmetros e versões de normalizador/avaliador.
- **Empacotamento da skill**: qualquer alteração em `.agents/skills/geo-llm-ranking/` deve ser acompanhada pela atualização de `packages/geo-llm-ranking-skill.zip` via `scripts/package_skill.py`.

## Comandos de validação

```bash
# Backend: lint, testes e análise estática de segurança
.venv/bin/ruff check backend/app backend/tests scripts .agents/skills/geo-llm-ranking/scripts
.venv/bin/pytest backend/tests -q
bandit -r backend/app -ll

# Frontend: lint, testes e build
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build

# Skill, pacote zip, evals e auditoria de exposição
python3 scripts/package_skill.py --check
python3 scripts/audit_repo.py
```
