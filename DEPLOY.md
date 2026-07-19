# Deploy da API — Render (host público, URL fixa)

> **AVISO — DEMO SEM AUTENTICAÇÃO.** Esta API sobe **aberta** (sem API key), por
> decisão de escopo do business case. A URL pública deve ser usada **apenas com a
> planilha de exemplo (dados sintéticos)**. **Não envie pedidos reais da GoCase
> (nome, e-mail, endereço = dados pessoais) para esta URL** sem antes adicionar
> autenticação. Para produção, ver "Antes de dados reais" no fim.

## Passo a passo (~2 min)

1. Acesse [render.com](https://render.com) e entre com a conta do GitHub.
2. **New +** → **Blueprint**.
3. Selecione o repositório `validador-pedidos-gocase`.
4. O Render lê o `render.yaml` e configura o serviço sozinho. Clique em
   **Apply / Create**.
5. Aguarde o build (instala `requirements-api.txt` e sobe `uvicorn`). No fim, o
   Render mostra a URL pública.

## URL esperada

Com o nome de serviço `validador-pedidos-gocase`, a URL fica:

```
https://validador-pedidos-gocase.onrender.com
```

Essa URL **já está fixada** no workflow do n8n (`integracoes/n8n_validador_workflow.json`).
Se o Render gerar um nome diferente (nome já em uso), troque a URL no nó
**POST /validar** do workflow — ou me avise que eu corrijo.

## Ativar a correção automática por IA (opcional)

Para que **qualquer pessoa** use a correção por IA sem ter chave própria, a
chave fica no servidor:

1. No Render: serviço → **Environment** → **Add Environment Variable**.
2. `ANTHROPIC_API_KEY` = sua chave `sk-ant-...` → **Save** (o serviço reinicia).

Nunca coloque a chave no repositório — só nessa variável de ambiente.

Controles de custo já embutidos:

| Variável | Padrão | Para que serve |
|---|---|---|
| `MAX_REJEITADOS_IA` | `60` | Recusa lotes maiores, limitando o tamanho da chamada |
| `MODELO_IA` | `claude-haiku-4-5-20251001` | Modelo barato; troque se quiser mais capacidade |

> **Atenção ao custo:** a API é pública e sem autenticação. Com a chave no
> servidor, qualquer um que descubra a URL pode consumir seu crédito da
> Anthropic. Mantenha um saldo baixo (o saldo é o teto do prejuízo) e
> **remova a variável `ANTHROPIC_API_KEY` quando a demonstração terminar**.
> Sem a variável, `/corrigir-automatico` responde 503 e o resto da API continua
> funcionando normalmente.

## Testar depois do deploy

```bash
curl https://validador-pedidos-gocase.onrender.com/
# {"servico":"Validador de Pedidos GoCase","status":"ok"}
```

Docs interativas: `https://validador-pedidos-gocase.onrender.com/docs`

> **Free tier:** o serviço "dorme" após ~15 min sem uso e acorda na primeira
> requisição (demora ~30s). Normal — a próxima chamada já responde rápido.

## Antes de dados reais (produção)

Se algum dia a URL for receber pedidos reais, adicione **autenticação por API
key** (um header verificado na API; ~15 linhas) e configure o n8n/Power Automate
para enviar a chave. Enquanto isso, mantenha o uso restrito à planilha de exemplo.
