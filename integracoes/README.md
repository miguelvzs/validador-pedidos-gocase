# Integrações low-code — Validador de Pedidos GoCase

A API HTTP (`api.py`) é o ponto único de integração: **HTTP + JSON padrão**, sem
SDK e sem amarração a ferramenta. Qualquer plataforma que faça uma requisição
HTTP consome o validador sem instalar nada — n8n, Make, Power Automate, Zapier,
Apps Script, código próprio.

Aqui o caminho documentado e testado é o **n8n** (workflow pronto para importar,
abaixo). Para as demais, use o contrato da API a seguir: o formato do arquivo de
workflow é específico do n8n, mas as chamadas são as mesmas em qualquer lugar.

## Contrato da API

Base (já no ar): `https://validador-pedidos-gocase.onrender.com`

| Método | Rota | Entrada | Saída |
|---|---|---|---|
| `POST` | `/validar` | multipart/form-data, campo **`arquivo`** = .xlsx (n8n, web) | JSON `{ job_id, resumo }` |
| `GET` | `/download/{job_id}` | — | `.zip` com os 3 relatórios |
| `GET` | `/download/{job_id}/{tipo}` | tipo = validados\|rejeitados\|resumo | 1 relatório .xlsx |
| `POST` | `/analisar-rejeitados` | JSON `{ job_id }` | contexto (dados+motivos+sugestões) para a IA corrigir |
| `POST` | `/revalidar` | JSON `{ job_id, correcoes:[{id_pedido,campo,valor}] }` | novo resumo + `recuperados` (antes→depois) |
| `POST` | `/corrigir-automatico` | JSON `{ job_id }` | ciclo completo de IA no servidor (sem credencial no cliente) |

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

A API é a única peça que precisa de Python — e roda **num lugar só**, já
publicada. Ninguém instala nada na própria máquina.

O workflow entregue aponta para essa **URL pública fixa**, então **importa e
roda em qualquer máquina sem editar nada**. Para apontar a outro servidor,
basta trocar a URL dos nós HTTP.

> **Demo sem autenticação:** a URL pública é aberta. Use apenas com a planilha de
> exemplo (dados sintéticos); não envie pedidos reais sem adicionar API key.

O workflow **não lê arquivo de disco** (nada de caminho fixo tipo `C:\...`, que
quebraria em outra máquina): a planilha entra por um **formulário de upload** do
próprio n8n. Portável por construção.

## n8n (caminho principal na GoCase)

A API já está publicada — nada para instalar ou implantar.

1. Importe `n8n_validador_workflow.json` (menu → **Import from File**).
2. Clique em **Execute workflow**. O nó **Upload da planilha** abre um
   formulário no navegador — abra a URL que o n8n mostra.
3. Suba o `.xlsx` no formulário. O fluxo (**um único workflow**, 6 nós):
   - **Upload da planilha** (Form Trigger) — recebe o arquivo como binário `arquivo`.
   - **POST /validar** — envia para a API e recebe o resumo em JSON.
   - **Tem rejeitados?** (IF) — se houver, tenta a correção por IA; se não, vai
     direto ao download.
   - **IA corrige rejeitados** — chama `/corrigir-automatico`. A chave da IA fica
     no servidor, então **nenhuma credencial é necessária no n8n**.
   - **Baixar relatórios (.zip)** — puxa o `.zip` da API.
   - **Baixar no navegador** (Form completion) — devolve o `.zip` para o
     navegador de quem enviou. Download **automático e universal**: não grava em
     disco (sem caminho fixo nem permissão), funciona em qualquer máquina.

### Degradação graciosa

O nó de IA está marcado como *continue on fail* e o download usa
`{{ $json.job_id || $('POST /validar').item.json.job_id }}`. Consequência: se o
servidor estiver **sem** a chave da IA (endpoint responde 503), o fluxo **não
quebra** — segue e entrega os relatórios da validação normal. Com a chave, entrega
as planilhas já corrigidas. Um workflow cobre os dois cenários.

Se a API estiver noutra máquina/servidor, troque só a URL dos nós HTTP. Para
trocar o formulário por um gatilho real (novo arquivo no SharePoint/Drive),
substitua o nó **Upload da planilha** — o resto continua igual.

