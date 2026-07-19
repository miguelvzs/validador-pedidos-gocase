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
legível), `404` (job_id inexistente ou expirado).

**Janela de download:** os relatórios de um `job_id` ficam disponíveis por
1 hora (TTL configurável via `JOBS_TTL_SEGUNDOS`); depois a pasta é apagada
automaticamente. No fluxo, baixe o resultado logo após validar.

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

## Onde a API roda (universalidade)

A API é a **única** peça que precisa de Python — mas roda **num lugar só**, não
na máquina de cada usuário. Dois modelos:

- **Central (produção):** a API é hospedada uma vez (servidor/VM/nuvem). Todos os
  n8n e usuários apontam para essa URL. Ninguém instala nada.
- **Portátil (demo/avaliação):** API + n8n na mesma máquina → a URL é
  `http://localhost:8000`. O workflow abaixo já usa `localhost`, então **importa
  e roda em qualquer máquina sem editar nada** — basta ter a API no ar ali.

O workflow **não lê arquivo de disco** (nada de caminho fixo tipo `C:\...`, que
quebraria em outra máquina): a planilha entra por um **formulário de upload** do
próprio n8n. Portável por construção.

## n8n (caminho principal na GoCase)

1. Suba a API na máquina: `uvicorn api:app --host 0.0.0.0 --port 8000`.
2. Importe `n8n_validador_workflow.json` (menu → **Import from File**).
3. Clique em **Execute workflow** (ou ative o workflow). O nó **Upload da
   planilha** abre um formulário no navegador — abra a URL que o n8n mostra.
4. Suba o `.xlsx` no formulário. O fluxo:
   - **Upload da planilha** (Form Trigger) — recebe o arquivo como binário `arquivo`.
   - **POST /validar** — envia para a API (`http://localhost:8000/validar`) e
     recebe o resumo em JSON.
   - **Tem rejeitados?** (IF) — ramifica em `resumo.total_rejeitados > 0`
     (ex.: notifica a gestão; senão segue para produção).

Se a API estiver noutra máquina/servidor, troque só a URL do nó **POST /validar**.
Para trocar o formulário por um gatilho real (novo arquivo no SharePoint/Drive),
substitua o nó **Upload da planilha** — o resto continua igual.

## Power Automate

Ver `POWER_AUTOMATE.md` — passo a passo com a ação **HTTP** (POST multipart),
`Parse JSON` do resumo e `Condition` sobre os rejeitados.
