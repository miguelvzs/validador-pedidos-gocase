# Validador de Pedidos — GoCase

Automação em Python para **validação e organização de pedidos de fábrica**.
Lê uma planilha de pedidos, separa os válidos dos rejeitados (registrando o
motivo de cada rejeição), classifica os válidos por prioridade de prazo e gera
relatórios Excel formatados prontos para o chão de fábrica.

Projeto desenvolvido como **business case** para o processo seletivo de Estágio
em RPA na **GoCase (GoGroup)** — varejo digital que fabrica produtos
personalizados sob demanda em Extrema/MG.

Uma lógica de validação, **consumida de forma centralizada** — o núcleo roda num
lugar só e ninguém instala nada na própria máquina:

- **API HTTP (FastAPI)** — núcleo de serviço; consumível por qualquer cliente HTTP.
- **Frontend web (Streamlit)** — o operador sobe a planilha no navegador.
- **Low-code (n8n / Power Automate / Make)** — um fluxo chama a API ao chegar
  um arquivo. n8n é o caminho principal na GoCase (ver `integracoes/`).
- **MCP Server** — chamável por qualquer ferramenta de IA (Claude Desktop, etc.),
  incluindo a correção assistida de rejeitados.

Para desenvolvimento/testes locais ainda existe o modo **terminal**
(`python main.py`), mas o uso real é centralizado pela API.

---

## Índice

- [Início rápido](#início-rápido)
- [O problema que resolve](#o-problema-que-resolve)
- [Fluxo de execução](#fluxo-de-execução)
- [Arquitetura](#arquitetura)
- [Formato da planilha de entrada](#formato-da-planilha-de-entrada)
- [Regras de validação](#regras-de-validação)
- [Classificação de prioridade](#classificação-de-prioridade)
- [Configuração (config.yaml)](#configuração-configyaml)
- [Relatórios gerados](#relatórios-gerados)
- [Modos de uso](#modos-de-uso)
- [Decisões de design](#decisões-de-design)
- [Testes](#testes)
- [Solução de problemas](#solução-de-problemas)
- [Estrutura de arquivos](#estrutura-de-arquivos)
- [Requisitos](#requisitos)

---

## Início rápido

Execute **de dentro da pasta do projeto** — os comandos falham com
`No such file or directory` se rodados de outro diretório (ex.: `C:\Users\SeuNome`).

```bash
pip install -r requirements.txt --break-system-packages
python main.py
```

Os resultados aparecem na pasta `output/`. É só isso — veja a
[nota sobre geração automática](#nota-geração-automática-de-dados) abaixo para
entender por que funciona sem preparar dados antes.

---

## O problema que resolve

Numa operação de produção sob demanda, pedidos chegam de vários canais (site,
marketplace, B2B, loja física) e nem todos estão prontos para ir à fábrica:
cliente sem nome, email quebrado, quantidade zerada, valor que não fecha, prazo
já vencido, pedido duplicado. Enviar esses pedidos para produção gera
retrabalho, desperdício de material e atraso.

Este agente atua como um **filtro automático antes da produção**:

1. Lê a planilha exportada do e-commerce.
2. **Rejeita** o que está inconsistente, dizendo exatamente o porquê.
3. **Prioriza** o que é válido pelo aperto do prazo.
4. Entrega planilhas prontas para a equipe agir.

---

## Fluxo de execução

```
┌─────────────┐   ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
│  1. Leitura │──▶│ 2. Validar │──▶│ 3. Organizar │──▶│ 4. Relatórios │──▶│ 5. Notificar │
│  (planilha) │   │  (regras)  │   │ (prioridade) │   │    (Excel)    │   │   (resumo)   │
└─────────────┘   └────────────┘   └──────────────┘   └───────────────┘   └──────────────┘
       │                 │                                     │
   leitor.py     validador.py                            relatorio.py
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       df_validos            df_rejeitados
       (organizados)         (+ motivo_rejeicao)
```

Cada etapa é isolada em `try/except`: se uma falha, o erro é logado e as etapas
seguintes que ainda fizerem sentido continuam. O orquestrador é o
`AgenteValidador` (`src/agente.py`).

---

## Arquitetura

Responsabilidade única por módulo — cada arquivo faz uma coisa e é testável
isoladamente.

| Módulo | Responsabilidade |
|---|---|
| `src/config.py` | Carrega `config.yaml` (regras externas) com fallback embutido. |
| `src/gerar_dados.py` | **Fixture de teste/demo.** Gera planilha simulada com erros propositais. *Não é componente de produção.* |
| `src/leitor.py` | Lê o Excel, tipa colunas (datas, números), valida a presença das colunas esperadas. |
| `src/validador.py` | Aplica as 9 regras de negócio; separa válidos de rejeitados; acumula motivos. |
| `src/organizador.py` | Calcula `dias_restantes` e `prioridade`; ordena os válidos para produção. |
| `src/relatorio.py` | Gera os 3 Excel formatados (cores por prioridade, bordas, freeze, larguras). |
| `src/assistente_ia.py` | Camada de IA: prepara rejeitados e aplica correções (via MCP). |
| `src/agente.py` | Orquestra o fluxo completo, configura logging, monta o resumo. |
| `main.py` | Entrada standalone (terminal, dev/testes). |
| `mcp_server.py` | Entrada MCP Server (stdio, 5 tools + prompt). |

### Fonte única de verdade

As métricas do resumo são montadas uma vez pelo `agente` e reusadas pelo
relatório, log e cache MCP. Os nomes, a ordem e as cores das faixas de
prioridade vivem só no `config.yaml` — renomear ou recolorir uma faixa reflete
em todo o sistema, sem código hardcoded.

---

## Formato da planilha de entrada

`data/pedidos_entrada.xlsx` — uma linha por pedido, com estas colunas:

| Coluna | Tipo | Exemplo |
|---|---|---|
| `id_pedido` | texto | `PED-00001` |
| `data_pedido` | data | `2026-07-14` |
| `cliente` | texto | `Ana Carolina` |
| `email` | texto | `ana.carolina@gmail.com` |
| `produto` | texto | `Case iPhone 15` |
| `sku` | texto | `CSE-IPH15-4821` |
| `quantidade` | inteiro | `3` |
| `valor_unitario` | número | `89.90` |
| `valor_total` | número | `269.70` |
| `canal` | texto | `site` |
| `endereco` | texto | `Rua das Flores, 123 - Centro, São Paulo/SP` |
| `prazo_entrega` | data | `2026-07-25` |

Faltar qualquer coluna faz o leitor parar cedo com `ValueError` dizendo qual
coluna faltou.

---

## Regras de validação

Cada pedido é avaliado contra **todas** as regras; um pedido pode acumular
vários motivos, concatenados por `; ` na coluna `motivo_rejeicao`.

| # | Campo | Regra |
|---|---|---|
| 1 | `id_pedido` | Não vazio e não duplicado. Na duplicata, a **2ª ocorrência** é rejeitada. |
| 2 | `cliente` | Não vazio nem só espaços. |
| 3 | `email` | Formato `texto@texto.dominio` (regex `^[^@]+@[^@]+\.[^@]+$`). |
| 4 | `quantidade` | Inteiro positivo (> 0). |
| 5 | `valor_unitario` | Positivo (> 0). |
| 6 | `valor_total` | Bate com `quantidade × valor_unitario` (tolerância R$ 0,02). |
| 7 | `prazo_entrega` | Não pode estar no passado. |
| 8 | `produto` | Não vazio. |
| 9 | `sku` | Não vazio. |

Exemplo de `motivo_rejeicao` com múltiplos erros:
`Cliente vazio; Email inválido: formato incorreto`

---

## Classificação de prioridade

Pedidos válidos ganham `dias_restantes = (prazo_entrega - hoje)` e uma faixa:

| Prioridade | Dias até o prazo | Cor no relatório |
|---|---|---|
| URGENTE | 0–2 | Vermelho claro |
| ALTA | 3–5 | Laranja claro |
| NORMAL | 6–10 | Verde claro |
| BAIXA | 11+ | Sem cor |

Ordenação final: URGENTE primeiro; dentro da mesma faixa, prazo mais apertado
antes (`dias_restantes` crescente).

---

## Configuração (config.yaml)

As regras de negócio ficam **externas ao código**, em `config.yaml` — um gestor
não-técnico ajusta limites sem tocar em Python:

```yaml
validacao:
  tolerancia_valor: 0.02          # diferença aceita em valor_total
  regex_email: '^[^@]+@[^@]+\.[^@]+$'
  mapa_colunas: {}                # renomeia colunas da SUA planilha → canônicas
  colunas_obrigatorias: [ ... ]   # colunas exigidas na planilha
prioridade:
  faixas:                         # dias até o prazo → faixa
    - { nome: URGENTE, min: 0, max: 2 }
    - { nome: ALTA,    min: 3, max: 5 }
    - { nome: NORMAL,  min: 6, max: 10 }
    - { nome: BAIXA,   min: 11, max: null }   # null = sem teto
```

Se o arquivo faltar ou uma chave estiver ausente, o sistema cai nos **padrões
embutidos** (`src/config.py`) — nunca quebra por config incompleta. YAML
inválido é avisado no console (suas mudanças são ignoradas). Muda o
comportamento da validação e da priorização sem redeploy.

**Planilha com outros cabeçalhos?** Preencha `mapa_colunas` para processar um
export real do e-commerce/ERP sem editar código:

```yaml
mapa_colunas:
  "Pedido": id_pedido
  "Nome do Cliente": cliente
  "Qtd": quantidade
```

---

## Relatórios gerados

Todos em `output/`.

**Para o operador** — as 3 planilhas que interessam ao chão de fábrica:

| Arquivo | Conteúdo |
|---|---|
| `pedidos_validados.xlsx` | Pedidos aprovados, linhas coloridas por prioridade, valores formatados, cabeçalho congelado. |
| `pedidos_rejeitados.xlsx` | Pedidos com erro + coluna `motivo_rejeicao` em vermelho/bold. |
| `resumo_execucao.xlsx` | Métricas consolidadas (totais, %, por prioridade, por canal, valores, tempo). |

**Artefatos internos** — isolados em `output/_sistema/`, fora da visão do
operador, gerados automaticamente:

| Arquivo | Uso |
|---|---|
| `_sistema/log_execucao.log` | Diagnóstico técnico da execução (UTF-8). Para o dev, quando algo falha. |
| `_sistema/ultimo_resumo.json` | Cache do último resumo; alimenta a tool MCP `consultar_resumo`. Não é aberto por humano. |

Assim o operador abre `output/` e vê apenas as 3 planilhas que importam.

---

## Modos de uso

### 1. Terminal (avaliação)

```bash
cd C:\Users\kenne\Documents\dev\validador-pedidos-gocase
python main.py
```

<a name="nota-geração-automática-de-dados"></a>
> #### ⚠️ Nota: geração automática de dados
>
> Se `data/pedidos_entrada.xlsx` **não existir**, `main.py` gera
> automaticamente uma planilha de exemplo (50 pedidos: 40 válidos + 10 com
> erros propositais) e a processa.
>
> Isso é **intencional para esta entrega**: o avaliador roda o projeto com um
> único comando, sem preparar dados antes.
>
> **Em produção real**, esse comportamento seria removido — o sistema deveria
> **falhar com mensagem clara** se a planilha estivesse ausente, em vez de
> fabricar dados. Por isso o gerador (`src/gerar_dados.py`) é uma ferramenta de
> teste/demo.

### 2. MCP Server (integração com IA)

```bash
python mcp_server.py
```

Fala **stdio** (JSON-RPC) e expõe 5 tools + 1 prompt:

| Tool | Função |
|---|---|
| `gerar_dados_exemplo` | Gera a planilha simulada (uso de teste/demo). |
| `validar_pedidos` | Executa o fluxo completo e retorna o resumo formatado. |
| `consultar_resumo` | Retorna o resumo da última execução, sem reprocessar. |
| `analisar_rejeitados` | Prepara os rejeitados para a IA corrigir (dados, motivos, sugestões mecânicas). |
| `revalidar_com_correcoes` | Aplica as correções da IA e revalida o lote, mostrando antes → depois. |

Para conectar no Claude Desktop, aponte a config de MCP para o comando
`python mcp_server.py` na raiz do projeto. O usuário então pede em linguagem
natural (ex.: *"valide os pedidos da planilha"*) e a IA chama a tool.

#### Camada de IA — correção assistida de rejeitados

O servidor não embute um modelo próprio nem exige chave de API: a **IA conectada
é o cérebro**. O fluxo (guiado pelo prompt `corrigir_pedidos_rejeitados`) é:

1. `analisar_rejeitados` devolve cada pedido barrado, seus motivos e as
   **sugestões mecânicas** já resolvidas por regra (recalcular `valor_total`,
   remover espaços, normalizar e-mail).
2. A IA propõe as **correções semânticas** — inferir um nome digitado errado,
   completar um e-mail, ajustar uma quantidade implausível. Dados que não dão
   para deduzir (cliente totalmente vazio) são sinalizados para revisão humana,
   não inventados.
3. `revalidar_com_correcoes` aplica as correções à planilha de origem, revalida
   o lote inteiro e relata quantos pedidos foram **recuperados**.

Exemplo real: 2 e-mails inválidos corrigidos → rejeitados 10 → 8, válidos 40 → 42.

### 3. Serviço central (API + web) — zero instalação no cliente

Para uso corporativo, o núcleo roda **num lugar só** e os usuários só falam
HTTP — sem Python, pip ou bibliotecas na máquina de ninguém. Duas peças:

- **`api.py`** — API HTTP (FastAPI) que expõe o mesmo pipeline:
  `POST /validar` (envia a planilha, recebe o resumo em JSON + `job_id`) e
  `GET /download/{job_id}` (baixa os 3 relatórios num `.zip`).
- **`app_streamlit.py`** — frontend web que consome a API. O operador abre no
  navegador, sobe a planilha e baixa o resultado.

```bash
# 1. sobe a API (num servidor/VM/nuvem)
uvicorn api:app --host 0.0.0.0 --port 8000
# 2. sobe o frontend (aponta para a API via API_URL)
API_URL=http://localhost:8000 streamlit run app_streamlit.py
```

A mesma API serve também **Power Automate, n8n ou Make**: um fluxo que observa
uma pasta no SharePoint chama `POST /validar` e devolve o resultado — nenhuma
dependência no cliente. Docs interativas da API em `http://localhost:8000/docs`.

Os relatórios de cada `job_id` vivem 1 hora e são apagados automaticamente
(TTL, via `JOBS_TTL_SEGUNDOS`) — o servidor não acumula arquivos temporários.

Uma lógica de validação, quatro formas de consumo (terminal, MCP, API/web,
low-code) — sem duplicar regra.

---

## Decisões de design

Escolhas que não são óbvias pelo código:

- **Log em `stderr`, não `stdout`.** No modo MCP o `stdout` carrega o protocolo
  JSON-RPC; qualquer log ali corromperia a comunicação e quebraria o cliente.
  O `stderr` fica livre para diagnóstico e o console segue legível.
- **Reconfiguração para UTF-8.** O console Windows usa cp1252 e corrompe acentos
  (`execu��o`). Os streams são reconfigurados para UTF-8; os arquivos de log já
  são gravados em UTF-8 explicitamente.
- **Seed fixa (`random.seed(42)`).** A planilha de exemplo é reproduzível entre
  execuções — essencial para os testes automatizados serem determinísticos.
- **Prazo contado a partir de hoje, não da data do pedido.** Se o prazo fosse
  `data_pedido + N dias`, pedidos antigos cairiam no passado por acidente e
  quebrariam a meta de "40 válidos". Contar de hoje mantém os 40 válidos e ainda
  distribui as faixas de prioridade.
- **Tolerância de R$ 0,02 em `valor_total`.** Soma de floats acumula erro de
  arredondamento; sem a tolerância, pedidos corretos gerariam falso positivo.
- **`errors="coerce"` na tipagem.** Valores inválidos viram `NaN`/`NaT` em vez de
  estourar na leitura — a decisão de rejeitar fica com o validador, não com o
  leitor.

---

## Testes

```bash
python testar.py
```

Roda o fluxo completo e verifica **8 pontos**:

1. Planilha de entrada gerada (50 pedidos).
2. Agente executa sem exceção.
3. `pedidos_validados.xlsx` existe e tem linhas.
4. `pedidos_rejeitados.xlsx` existe e tem linhas.
5. `resumo_execucao.xlsx` existe.
6. `log_execucao.log` existe e não está vazio.
7. Consistência: `válidos + rejeitados == total`.
8. Todos os rejeitados têm `motivo_rejeicao` preenchido.

Saída esperada: `Todos os 8 testes passaram ✓`.

---

## Solução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `Colunas obrigatórias ausentes` | Planilha real com cabeçalhos diferentes. | Preencha `mapa_colunas` no [config.yaml](#configuração-configyaml) mapeando seus nomes para os canônicos. |
| `Não consegui atualizar '...xlsx'` | Relatório aberto no Excel trava a escrita. | Feche o arquivo no Excel; o sistema tenta 3× com aviso antes de falhar. |
| Relatórios com dados que parecem fictícios | Planilha real ausente → `main.py` gerou exemplo. | Aviso em destaque no console indica isso; coloque a planilha real em `data/` e rode de novo. |
| `[AVISO] config.yaml inválido` | Erro de indentação no YAML. | Suas mudanças foram ignoradas (usou padrões); corrija a indentação. |
| Acentos tortos no console (`execu��o`) | Terminal antigo em cp1252. | Já tratado no código; se persistir, rode `chcp 65001` antes. |
| Cliente MCP não responde | Log poluindo `stdout`. | Já tratado (log vai para `stderr`); verifique se não há `print()` solto. |

---

## Estrutura de arquivos

```
validador-pedidos-gocase/
├── data/                    ← planilha de entrada (gerada/fornecida)
├── output/                  ← 3 planilhas do operador
│   └── _sistema/            ← log + cache JSON (artefatos internos)
├── src/
│   ├── config.py            ← carrega config.yaml (com fallback embutido)
│   ├── gerar_dados.py       ← fixture de teste/demo (NÃO é produção)
│   ├── leitor.py            ← leitura e tipagem da planilha
│   ├── validador.py         ← regras de validação
│   ├── organizador.py       ← classificação por prioridade
│   ├── relatorio.py         ← geração dos Excel formatados
│   ├── assistente_ia.py     ← camada de IA: correção assistida via MCP
│   └── agente.py            ← orquestrador do fluxo
├── config.yaml              ← regras de negócio editáveis (sem tocar código)
├── main.py                  ← entrada standalone (terminal)
├── mcp_server.py            ← entrada MCP Server (5 tools + prompt)
├── api.py                   ← API HTTP FastAPI (núcleo de serviço)
├── app_streamlit.py         ← frontend web que consome a API
├── testar.py                ← testes de fumaça
├── requirements.txt
└── README.md
```

---

## Requisitos

- Python 3.10+
- `pandas >= 2.0.0`, `openpyxl >= 3.1.0`, `mcp >= 1.0.0`, `pyyaml >= 6.0`
  (ver `requirements.txt`)

Codificação UTF-8 em toda operação de arquivo. Type hints e docstrings em
português em todo o código.
