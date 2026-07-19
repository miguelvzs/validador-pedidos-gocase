# Integrações low-code — Validador de Pedidos GoCase

A API HTTP (`api.py`) é o ponto único de integração. Qualquer ferramenta que
fale HTTP consome o validador sem instalar nada — n8n, Power Automate, Make.

## Contrato da API

Base: `http://SEU_SERVIDOR:8000`

| Método | Rota | Entrada | Saída |
|---|---|---|---|
| `POST` | `/validar` | multipart/form-data, campo **`arquivo`** = .xlsx (n8n, web) | JSON `{ job_id, resumo }` |
| `POST` | `/validar-base64` | JSON `{ nome_arquivo, conteudo_base64 }` (Power Automate) | JSON `{ job_id, resumo }` |
| `GET` | `/download/{job_id}` | — | `.zip` com os 3 relatórios |
| `GET` | `/download/{job_id}/{tipo}` | tipo = validados\|rejeitados\|resumo | 1 relatório .xlsx |

Erros: `400` (não é Excel), `422` (planilha com colunas erradas — mensagem
legível), `404` (job_id inexistente).

Exemplo do `resumo` retornado:

```json
{
  "job_id": "0670d93e9ec2",
  "resumo": {
    "total_processados": 50,
    "total_validos": 40,
    "total_rejeitados": 10,
    "percentual_validos": 80.0,
    "por_prioridade": {"URGENTE": 7, "ALTA": 8, "NORMAL": 13, "BAIXA": 12},
    "por_canal": {"site": 15, "marketplace": 15, "b2b": 13, "loja_fisica": 7},
    "valor_total_validos": 17680.34,
    "valor_total_rejeitados": 2870.49
  }
}
```

## n8n (caminho principal na GoCase)

Importe `n8n_validador_workflow.json` (menu → Import from File). O fluxo:

1. **Trigger** — troque o Manual Trigger pelo seu gatilho real (novo arquivo no
   Google Drive/SharePoint, webhook, schedule).
2. **HTTP Request** — `POST /validar`, body `multipart/form-data`, campo binário
   `arquivo`. Aponte a URL para o seu servidor.
3. **IF** — ramifica em cima de `resumo.total_rejeitados` (ex.: se > 0, notifica
   a gestão; senão segue para produção).

O nó HTTP Request já vem configurado com o campo `arquivo` e `multipart/form-data`.

## Power Automate

Ver `POWER_AUTOMATE.md` — passo a passo com a ação **HTTP** (POST multipart),
`Parse JSON` do resumo e `Condition` sobre os rejeitados.
