# Infraestrutura e acesso a modelos

## Configuração GCP e ADC

- Habilite a API `aiplatform.googleapis.com` no projeto GCP configurado em `APP_GCP_PROJECT`.
- O backend usa Application Default Credentials (ADC). Credenciais não são copiadas para o repositório nem expostas ao frontend.
- O timeout por chamada de modelo é configurável via `APP_MODEL_TIMEOUT_SECONDS`, com persistência de saídas parciais e transição explícita para `interrupted` em caso de reinicialização do backend durante uma execução.

## Menor permissão para o principal de execução

Conceda ao principal de execução somente `roles/aiplatform.user` no projeto. O usuário que executa Terraform também precisa poder alterar IAM do projeto. Prefira `google_project_iam_member`, que adiciona apenas um vínculo sem substituir os demais membros da role.

Exemplo mínimo para configuração local:

```hcl
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project_id" {
  type = string
}

variable "runtime_member" {
  type        = string
  description = "Principal que executará o backend, por exemplo user:alguem@example.com"
}

provider "google" {
  project = var.project_id
}

resource "google_project_iam_member" "model_inference" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = var.runtime_member
}
```

Guarde os arquivos Terraform e o state local em `infra/`, que fica ignorado pelo Git. Use ADC também no Terraform; não crie chaves de service account.

```bash
terraform -chdir=infra init
terraform -chdir=infra plan -var="project_id=your-gcp-project-id" -var="runtime_member=user:alguem@example.com"
terraform -chdir=infra apply -var="project_id=your-gcp-project-id" -var="runtime_member=user:alguem@example.com"
terraform -chdir=infra destroy -var="project_id=your-gcp-project-id" -var="runtime_member=user:alguem@example.com"
```

Se um vínculo temporário for criado para outro principal, destrua-o pelo mesmo state logo após o uso.

## Provedores do catálogo

- **Gemini (3.5 Flash-Lite, 3.8 Flash, 3.1 Pro)**: usa Vertex AI e ADC no backend.
- **Claude 5 (Sonnet 5, Opus 5, Opus 5.5, Fable 5, Fable 5.1)**: usa os endpoints de partner models do Vertex e ADC. Cada modelo precisa estar habilitado no Model Garden e os termos Anthropic precisam estar aceitos no projeto GCP.
- **Grok 4.7**: usa a API xAI, fora do projeto GCP. Configure `APP_XAI_API_KEY` somente no `.env` do backend. Sem essa chave, o modelo permanece visível e indisponível na seleção.
- O registry em `.env` é configuração local. O endpoint `/api/models` informa se o adapter e as credenciais locais permitem executar cada opção; isso não confirma quota, billing, termos ou acesso no Model Garden.

## Referências do provedor

- [Claude no Gemini Enterprise Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/use-claude)
- [Grok 4.7 na API xAI](https://docs.x.ai/developers/grok-4-7)
- [Gemini 3.5 Flash-Lite no Google Cloud](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite)
