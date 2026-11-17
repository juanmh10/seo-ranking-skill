# Plano completo de desenvolvimento — LLM Source Manipulation Benchmark v0.1

## 1. Produto e arquitetura funcional

- Construir um monorepo com React/Vite/TypeScript no frontend e FastAPI/Python no backend.
- Executar localmente para um único usuário, vinculando o backend a `127.0.0.1` por padrão e usando ADC do WSL exclusivamente no backend.
- Organizar o backend em domínio, serviços, persistência, API, providers, avaliação e observabilidade. O Research Core não importará Google ADK nem classes específicas do Vertex.
- Usar SQLAlchemy 2 assíncrono com SQLite/aiosqlite, Alembic, WAL, foreign keys habilitadas e transações curtas. UUIDs, enums textuais não nativos e colunas JSON portáveis preservarão a futura migração para PostgreSQL.
- Executar trabalhos longos em tarefas assíncronas internas. O POST cria e persiste toda a execução antes de iniciar; desconectar o navegador nunca cancela o benchmark.
- Limitar a V1 a uma execução de modelo por vez, usando uma fila local configurável. Repetições são executadas sequencialmente para reduzir interferência de rate limit e concorrência no SQLite.
- Persistir eventos e transmiti-los por SSE com heartbeat, reconexão e `Last-Event-ID`. Ao reiniciar a aplicação, execuções não terminais passam para `interrupted`; nunca serão retomadas silenciosamente.
- Usar o fluxo atual do Google ADK com `Runner.run_async`. Cada run de benchmark terá um `InMemorySessionService` e uma sessão novos, descartados ao final. O contexto das fontes será inserido como contexto transitório e a pergunta como mensagem do usuário.
- Manter três fronteiras rígidas:
  - execução recebe apenas prompt do sistema, parâmetros, cinco fontes e pergunta;
  - avaliação recebe resposta, fontes, labels, ground truth e definição do eval;
  - análise recebe somente resultados persistidos, métricas e runs selecionados.
- Fixar por configuração um modelo Gemini Flash para análise e outro para extração/julgamento. Os IDs exatos serão validados no Vertex durante o setup e gravados na configuração, nunca espalhados pelo código.

## 2. Funcionalidades e fluxos

### Experimentos, datasets e fontes

- Permitir criar, listar, abrir, editar metadados e arquivar experimentos.
- Cada experimento começa com um dataset draft vazio, tratado como acervo incremental. Não existe dataset inicial obrigatório: fontes são acumuladas conforme uploads, entradas manuais e outputs dos modelos surgem nas iterações.
- O acervo pode conter mais de cinco documentos; somente cinco recebem slots ativos em uma execução. Trocar um slot não remove versões e outputs anteriores.
- Aceitar upload multipart de HTML, HTM, TXT, Markdown, JSON, JSON-LD e XML, com limite de 5 MiB por arquivo e 25 MiB por requisição. PDF ficará explicitamente rejeitado na V1.
- Aceitar de uma a cinco fontes durante a edição; exigir exatamente cinco para iniciar um benchmark.
- Calcular SHA-256 sobre os bytes originais e preservar:
  - bytes/texto original decodificado;
  - conteúdo normalizado;
  - MIME declarado e detectado;
  - representação da fonte;
  - tamanho, posição e versão do normalizador.
- Rejeitar arquivos binários, UTF-8 inválido, JSON/JSON-LD inválido e XML inseguro. XML será processado sem DTD, entidades externas ou acesso à rede.
- Normalização determinística e versionada:
  - HTML: título, metadados relevantes, texto visível e blocos JSON-LD identificados; scripts, estilos e comentários não entram no texto visível;
  - Markdown: texto e estrutura sem executar HTML ou scripts;
  - JSON/JSON-LD: serialização canônica;
  - XML: conteúdo e atributos relevantes, sem resolução externa;
  - TXT: normalização de encoding e finais de linha.
- `RAW`, `NORMALIZED` e `BOTH` controlarão a representação entregue ao modelo. Em `BOTH`, cada fonte terá seções RAW e NORMALIZED claramente delimitadas.
- Nunca executar, renderizar como HTML ativo ou seguir instruções encontradas nas fontes. O inspector exibirá conteúdo escapado.
- Cada fonte terá posição, `entity_key`, nome canônico, aliases, `counterfactual_group_key`, severity, technique, `expected_target` e anotação.
- Cada output convertido em fonte registrará origem `model_output`, número da iteração, documento pai e proveniência do run/modelo que o gerou.
- Exigir exatamente um `expected_target` para benchmark. Interactive poderá funcionar com uma a cinco fontes e sem labels completos.
- No primeiro benchmark, congelar um snapshot imutável do dataset. Mudanças posteriores criarão nova versão por copy-on-write.

### Configuração e execução

- Manter prompts do sistema como versões imutáveis com nome, conteúdo, versão e SHA-256.
- Validar parâmetros contra as capacidades do modelo selecionado. A UI só mostrará temperature, top-p, reasoning, seed e demais campos quando suportados.
- O registry será preenchido pelo backend a partir de configuração e verificação no Vertex; o frontend nunca terá uma lista hardcoded.
- `document_order_strategy`:
  - `fixed`: posições do dataset;
  - `randomized`: gera e persiste um seed efetivo;
  - `seeded_random`: exige seed do usuário;
  - `counterbalanced`: distribui posições por quadrado latino e usa seed para desempates.
- Persistir em cada run a ordem efetiva, seed, hashes, versões, parâmetros, região, modelo real, token usage, duração e IDs do provider.
- Aceitar de 1 a 100 repetições. Cada repetição cria um run independente, sem memória.
- Fazer preflight de contexto contra `max_context` do modelo. Configurações excedentes retornam erro antes de criar a execução.
- O modelo avaliado responderá em texto natural. Nenhum JSON obrigatório será imposto ao subject model.
- Interactive manterá histórico próprio, streaming e botão de reset. Suas mensagens serão persistidas separadamente e nunca reutilizadas em Benchmark.
- Retries: até três tentativas com backoff apenas para falhas transitórias anteriores a uma resposta utilizável. Resposta parcial ou conclusão ambígua será persistida e marcada como falha, sem repetição automática.
- Falha de uma repetição não cancela as demais. Falha de eval não apaga o resultado bruto e produz `completed_with_eval_errors`.

### Avaliação, métricas e análise

- Implementar um Eval Bus versionado com:
  - scorers determinísticos;
  - extração estruturada;
  - evaluadores ADK;
  - LLM judge com saída JSON validada.
- Scorers determinísticos localizarão nomes/aliases, citações explícitas, ordem de menção e sinais inequívocos. Casos ambíguos serão `null`, nunca convertidos arbitrariamente em zero.
- Um extractor fixo, sem ferramentas e com temperatura zero quando suportada, produzirá entidades selecionadas, ranking, evidências e confidence. O resultado bruto e a versão do extractor serão preservados.
- O resultado oficial de seleção usará evidência determinística quando conclusiva; caso contrário, usará a extração model-based versionada e marcará sua origem.
- Implementar as métricas da especificação: seleção, rank, rank delta, injection compliance, claim/citation adoption, competitor suppression, fabricated authority adoption, grounding, unsupported claim rate e injection awareness.
- Calcular Manipulation Lift deterministicamente sobre resultados persistidos:
  - controle é `severity=neutral` e `technique=none`;
  - condições precisam compartilhar modelo, prompt, geração, content mode, dataset/version, grupo contrafactual e distribuição de posição;
  - diferenças incompatíveis retornam “não calculável” com motivo;
  - resultado inclui taxa de controle, taxa da condição, lift em pontos percentuais, amostras e origem do score.
- O Analysis Agent terá somente ferramentas de leitura sobre runs, evals e agregações. Não terá acesso a credenciais, filesystem, rede arbitrária ou ferramentas mutáveis.
- O manifest reproduzível incluirá schema version, configuração, prompts e hashes, modelo real, documentos e hashes, labels, evals e versões, ordem, seed e repetições.

### Interface

- Criar lista de experimentos e workspace do experimento.
- Workspace:
  - header com experimento, modo e status;
  - painel esquerdo com parâmetros e resumo de eval;
  - centro com chat/resposta, streaming, Run e alternância Interactive/Benchmark;
  - painel direito com exatamente cinco slots de fontes.
- Inspector de fonte com Raw, Normalized, Metadata, Label e SHA-256.
- Estados explícitos para draft, validação, queued, running, evaluating, completed, completed with eval errors, failed e interrupted.
- A tela de resultados mostrará runs individuais, resposta, ordem das fontes, eventos, scores/evidências e agregações.
- Analysis terá histórico persistido, seleção dos runs incluídos e streaming separado.
- Gerar o cliente TypeScript e os tipos públicos a partir do OpenAPI do FastAPI para evitar contratos duplicados.

## 3. Contratos e persistência

### Tipos públicos

- `Severity`: `neutral | low | moderate | aggressive | harmful`.
- `Technique`: valores aprovados na especificação.
- `ContentMode`: `RAW | NORMALIZED | BOTH`.
- `OrderStrategy`: `fixed | randomized | seeded_random | counterbalanced`.
- `RunStatus`: `queued | running | evaluating | completed | completed_with_eval_errors | failed | interrupted`.
- Erros HTTP seguirão Problem Details, com código estável, mensagem, campos inválidos e `trace_id`.

### API

| Área | Contratos |
| --- | --- |
| Saúde | `GET /api/health`, `GET /api/readiness` |
| Experimentos | CRUD funcional em `/api/experiments`; exclusão física não será exposta, apenas arquivamento |
| Fontes | upload multipart e listagem em `/api/experiments/{id}/documents`; detalhe, label e remoção em `/api/documents/{id}` |
| Modelos | `GET /api/models` e `GET /api/models/{model_id}/capabilities` |
| Interactive | criar/resetar sessão, enviar mensagem, consultar histórico e consumir stream em `/api/experiments/{id}/interactive/...` |
| Benchmark | `POST /api/experiments/{id}/runs` retorna `202`, `run_config_id` e `run_ids`; exige `Idempotency-Key` |
| Execução agregada | `GET /api/run-configs/{id}`, `/events` e `/stream` |
| Runs | detalhe, eventos e stream individual em `/api/runs/{id}` |
| Evals | listar e recomputar em `/api/runs/{id}/evals`; recomputação cria nova versão sem alterar o run |
| Métricas | `GET /api/experiments/{id}/metrics` com filtros pelas dimensões aprovadas |
| Analysis | criar sessão, enviar mensagem, histórico e stream em `/api/.../analysis/sessions` |
| Manifest | `GET /api/experiments/{id}/manifest`, retornando JSON também baixável |

### Dados

- Implementar todas as tabelas da especificação e acrescentar apenas o necessário para fechar os fluxos:
  - posição, representação, versão do normalizador e identidade contrafactual em documents;
  - status, dataset snapshot e chave idempotente em run_configs;
  - tentativas e origem da seleção em runs/eval_results;
  - `interactive_sessions` e `interactive_messages`;
  - status/erro nas sessões de análise.
- Timestamps sempre em UTC.
- Conteúdo JSON será armazenado por tipos SQLAlchemy portáveis; enums serão strings validadas pela aplicação.
- Foreign keys e unicidade protegerão posição 1–5, versão de prompt, chave idempotente, model registry e um único target por snapshot.
- Eventos serão append-only e servirão simultaneamente à auditoria e ao replay SSE.
- SQLite receberá `journal_mode=WAL`, `foreign_keys=ON` e `busy_timeout=5000` em cada conexão.

## 4. Falhas, segurança e observabilidade

- Retornar `409` para conflito de estado/idempotência, `413` para tamanho, `415` para formato e `422` para configuração experimental inválida.
- Não iniciar benchmark sem cinco fontes, target único, labels completas, modelo disponível, prompt versionado e contexto dentro do limite.
- Registrar eventos estruturados para criação, normalização, execução, chamadas de modelo, eval, análise e falhas.
- Redigir dos logs headers, tokens, ADC, conteúdo de credenciais e payloads sensíveis. Conteúdo integral das fontes fica no banco, não nos logs.
- Sanitizar filenames; nunca usar caminhos enviados pelo cliente.
- Aplicar CORS somente à origem local configurada e não servir `input/`, `output/`, `trash/` ou arquivos do gcloud.
- Evaluator e Analysis Agent tratarão todo conteúdo de fonte/resposta como dado não confiável, com instruções de sistema explícitas para não obedecer a comandos incorporados.
- Expor duração, tokens, status, tentativa, modelo, trace/span e erro categorizado em eventos.
- O frontend reconectará streams automaticamente e reconstruirá o estado consultando o backend, sem depender apenas de eventos em memória.

## 5. Testes e critérios de aceitação

- Unitários:
  - hashing e normalização por formato;
  - bloqueio de XML externo e HTML ativo;
  - montagem do contexto sem vazamento de labels/ground truth;
  - ordenação fixed/random/seeded/counterbalanced;
  - validação de capacidades e limite de contexto;
  - extração de entidades, rank e Manipulation Lift;
  - compatibilidade/incompatibilidade entre condições.
- Persistência:
  - migrations do zero;
  - foreign keys, unicidade, cascades e snapshots imutáveis;
  - pragmas SQLite;
  - transições válidas de status;
  - idempotência e replay de eventos.
- API:
  - uploads válidos e inválidos;
  - limite de cinco fontes;
  - preflight completo;
  - execução com `FakeModelRunner`;
  - falhas/retries independentes;
  - recomputação de eval;
  - manifest estável;
  - SSE com reconexão e desconexão sem cancelar trabalho.
- Frontend:
  - criação do experimento;
  - drag-and-drop e inspector;
  - parâmetros condicionados por capabilities;
  - Interactive com streaming/reset;
  - Benchmark com progresso, resultados, eventos e erros;
  - métricas e Analysis.
- End-to-end determinístico:
  - usar provider falso com cinco fontes sintéticas e respostas conhecidas;
  - provar ausência de memória entre repetições;
  - provar ordem persistida e seed reproduzível;
  - provar isolamento entre execution/evaluation/analysis;
  - obter Manipulation Lift esperado e manifest reproduzível.
- Smoke test Vertex, protegido por flag e ADC real, validará registry, uma chamada ADK, streaming e metadados do modelo sem integrar credenciais aos testes normais.
- A V1 será aceita quando todos os critérios funcionais do MVP da especificação forem demonstráveis pela UI e API, inclusive scorer determinístico, evaluator baseado em modelo, eventos, análise e manifest.

### Premissas fechadas

- Uso local, single-user e sem autenticação da aplicação na V1.
- Resposta do subject model em texto natural com extração posterior.
- Exatamente cinco fontes apenas no momento do Benchmark; drafts e Interactive aceitam menos.
- Uma execução de modelo por vez por padrão.
- Arquivos textuais de até 5 MiB; PDF fora da V1.
- Sem scheduler externo, Redis, Celery, containers obrigatórios ou PostgreSQL na V1.
- Sem exclusão física de experimentos pela API.
- Dependências serão fixadas em lockfiles; a integração ADK usará a API `Runner.run_async` e sessão nova por run.
