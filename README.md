# Validador de Pedidos — GoCase

Automação que atua como **filtro de qualidade entre a captação de pedidos e o
chão de fábrica**: lê a planilha de pedidos, barra o que está inconsistente
explicando o motivo, prioriza o que é válido pelo aperto do prazo e ainda tenta
**recuperar automaticamente**, com IA, os pedidos que foram barrados.

Business case para o processo seletivo de Estágio em RPA na **GoCase (GoGroup)**.
Área de negócio: Operações de Fábrica.

**Serviço no ar:** `https://validador-pedidos-gocase.onrender.com`

---

## O problema

Na produção sob demanda, cada pedido vira uma ordem de produção física. Um
pedido com dado quebrado não é só um registro errado — é material personalizado
gasto, hora-máquina perdida e cliente sem receber.

Os pedidos chegam de vários canais (site, marketplace, B2B, loja física), cada
um com um nível diferente de validação na origem. O resultado é uma planilha
onde convivem pedidos perfeitos e pedidos com cliente sem nome, e-mail quebrado,
quantidade zerada, valor que não fecha, prazo vencido ou duplicidade.

Conferir isso à mão é lento, cansativo e deixa passar erro sutil — uma diferença
de centavos, uma duplicata separada por dezenas de linhas.

---

## Como o operador usa

1. Abre o formulário do fluxo no navegador.
2. Sobe a planilha `.xlsx`.
3. Recebe de volta um `.zip` com as três planilhas prontas.

Nada é instalado na máquina de ninguém: o processamento roda no servidor e o
resultado volta pelo navegador.

> **Primeira execução do dia.** O serviço está hospedado em plano gratuito e
> hiberna após alguns minutos sem uso. A primeira chamada leva cerca de 50
> segundos para acordar o servidor; as seguintes respondem em menos de 1
> segundo. Se o fluxo acusar tempo esgotado na primeira tentativa, basta repetir.

---

## Resultado medido

Lote de 50 pedidos, com 10 problemas reais:

| Métrica | Valor |
|---|---|
| Pedidos processados | 50 |
| Reprovados na validação | 10 |
| **Recuperados pela IA** | **5** |
| Válidos ao final | 45 (90%) |
| Tempo de processamento | menos de 1 segundo |

---

## Regras de validação

Cada pedido é avaliado contra **todas** as regras. Um pedido pode acumular
vários motivos, concatenados na coluna `motivo_rejeicao` — a gestão vê a lista
completa de problemas de uma vez, não um erro por reprocessamento.

| # | Campo | Regra |
|---|---|---|
| 1 | `id_pedido` | Não vazio e não duplicado. Na duplicata, a 2ª ocorrência é reprovada. |
| 2 | `cliente` | Não vazio. |
| 3 | `email` | Formato `texto@texto.dominio`. |
| 4 | `quantidade` | Inteiro positivo. |
| 5 | `valor_unitario` | Positivo. |
| 6 | `valor_total` | Bate com `quantidade × valor_unitario` (tolerância de R$ 0,02). |
| 7 | `prazo_entrega` | Não pode estar no passado. |
| 8 | `produto` | Não vazio. |
| 9 | `sku` | Não vazio. |

### Prioridade de produção

Os aprovados recebem `dias_restantes` e entram numa fila ordenada por urgência —
os mais apertados primeiro.

| Prioridade | Dias até o prazo | Cor na planilha |
|---|---|---|
| URGENTE | 0 a 2 | Vermelho claro |
| ALTA | 3 a 5 | Laranja claro |
| NORMAL | 6 a 10 | Verde claro |
| BAIXA | 11 ou mais | Sem cor |

---

## O que é entregue

| Planilha | Conteúdo |
|---|---|
| `pedidos_validados.xlsx` | Aprovados, na ordem de produção, coloridos por prioridade. |
| `pedidos_rejeitados.xlsx` | Reprovados, com o motivo exato de cada um. |
| `resumo_execucao.xlsx` | Métricas do lote: totais, percentuais, prioridades, canais, valores. |

---

## Camada de IA — recuperação de pedidos reprovados

Barrar pedido resolve metade do problema. A outra metade é **recuperá-lo**.

A divisão de trabalho é explícita:

- **Erro mecânico** (valor que não fecha, espaço sobrando, e-mail a normalizar)
  → resolvido por regra, sem IA.
- **Erro semântico** (nome faltando, e-mail incompleto) → a IA infere cruzando
  os outros campos do próprio pedido.
- **Dado impossível de deduzir** → sinalizado para revisão humana, nunca inventado.

### O que a IA corrigiu na execução real

| Pedido | Correção | De onde deduziu |
|---|---|---|
| PED-00003 | `cliente: '' → 'Camila Rodrigues'` | do e-mail `camila.rodrigues@...` |
| PED-00016 | `cliente: '' → 'Patricia Gomes'` | do e-mail `patricia.gomes@...` |
| PED-00034 | `cliente: '' → 'Daniel Oliveira'` | do e-mail `daniel.oliveira@...` |
| PED-00022 | `email: 'cliente@' → 'yasmin.monteiro@gmail.com'` | do nome do cliente |
| PED-00008 | `email: 'clientegocase.com' → 'cliente@gocase.com'` | faltava o `@` |

### O que ela corretamente não resolveu

Dos 10 reprovados, 5 permaneceram — e é assim que deve ser:

- **2 duplicatas** — exigem decisão humana sobre qual pedido vale.
- **1 prazo vencido** — não é erro de dado, é problema operacional.
- **2 valores incoerentes** — a IA ajustou a quantidade, mas o `valor_total` não
  fechou, então o pedido **continuou reprovado**. A validação não abre exceção
  para a IA.

### Trilha de auditoria

Correção automática só é confiável se for auditável. A IA **assina** o que fez,
dentro das planilhas entregues:

- Coluna `corrigido_por_ia` marca os pedidos recuperados.
- Coluna `correcao_ia` registra o antes → depois de cada campo alterado.
- O resumo traz a linha **"Pedidos recuperados pela IA"**.

Deduzir o nome a partir do e-mail é uma **inferência plausível, não um dado
confirmado**. Por isso a trilha existe: a IA acelera a recuperação e a decisão
final continua conferível por uma pessoa.

---

## Arquitetura

Responsabilidade única por módulo — cada arquivo faz uma coisa e é testável
isoladamente.

| Módulo | Responsabilidade |
|---|---|
| `src/leitor.py` | Lê o Excel, tipa colunas e confere o schema esperado. |
| `src/validador.py` | Aplica as 9 regras; separa aprovados de reprovados; acumula motivos. |
| `src/organizador.py` | Calcula `dias_restantes` e prioridade; ordena a fila. |
| `src/relatorio.py` | Gera as 3 planilhas formatadas. |
| `src/assistente_ia.py` | Prepara os reprovados para a IA, aplica as correções e marca a autoria. |
| `src/config.py` | Carrega `config.yaml` com fallback embutido. |
| `src/agente.py` | `executar_pipeline`: o fluxo completo, em uma função só. |
| `src/gerar_dados.py` | Gera a planilha de demonstração. Ferramenta de teste, não de produção. |
| `api.py` | Superfície HTTP: validação, download e correção por IA. |
| `mcp_server.py` | Superfície MCP: 5 ferramentas + 1 prompt para clientes de IA. |
| `main.py` | Execução por terminal, para desenvolvimento. |

**Fonte única de verdade.** O fluxo vive em `executar_pipeline`; as métricas são
montadas uma vez e reaproveitadas pelo relatório, pelo log e pela API. Nomes,
ordem e cores das faixas de prioridade existem apenas no `config.yaml`.

### Tecnologias

Python 3.10+ · pandas e openpyxl (planilhas) · FastAPI e uvicorn (API HTTP) ·
PyYAML (configuração externa) · httpx (chamada à IA) · MCP (integração com
clientes de IA) · Anthropic Claude (correção assistida) · n8n (orquestração
low-code) · Render (hospedagem).

---

## Formas de consumo

Uma lógica de validação, três superfícies — sem regra duplicada.

| Superfície | Para quem | Como |
|---|---|---|
| **n8n** | Operação | Formulário de upload; devolve o `.zip` no navegador. Workflow pronto em `integracoes/`. |
| **API HTTP** | Qualquer sistema | HTTP + JSON padrão, sem SDK. Contrato em `integracoes/README.md`. |
| **MCP** | Ferramentas de IA | 5 ferramentas chamáveis por linguagem natural (ex.: Claude Desktop). |

### Conectando o MCP a um cliente de IA

O n8n executa a automação em lote; o MCP permite **interrogá-la** em linguagem
natural — *"quantos pedidos foram barrados e por quê?"*. Para habilitar num
cliente compatível (Claude Desktop, por exemplo), aponte-o para o servidor:

```json
{
  "mcpServers": {
    "validador-gocase": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "caminho/para/validador-pedidos-gocase"
    }
  }
}
```

Ferramentas expostas: `validar_pedidos`, `consultar_resumo`,
`analisar_rejeitados`, `revalidar_com_correcoes` e `gerar_dados_exemplo`, mais
um prompt guia. As duas do meio formam o ciclo de correção assistida: o modelo
do próprio cliente propõe as correções e o servidor revalida.

A integração não amarra a ferramenta: por ser HTTP puro, Make, Power Automate ou
código próprio consomem a mesma API. O n8n é o caminho documentado e testado,
por ser o padrão na GoCase.

---

## Configuração sem código

Regras de negócio ficam fora do código, em `config.yaml`: tolerância de valor,
padrão de e-mail, colunas obrigatórias e as faixas de prioridade (nomes,
intervalos e cores). Um gestor ajusta limites sem abrir Python.

Há ainda o `mapa_colunas`, que traduz os cabeçalhos de um export real do
e-commerce/ERP para os nomes esperados — planilha diferente não exige código
novo.

Configuração ausente ou inválida não derruba nada: o sistema avisa e usa os
padrões embutidos.

---

## Qualidade

`testar.py` executa **13 verificações** de ponta a ponta: geração da planilha,
execução do fluxo, existência e conteúdo das 3 planilhas e do log, consistência
(`aprovados + reprovados = total`), presença de motivo em todos os reprovados e
o comportamento da API — validação, download do pacote e recusa de planilha fora
do formato com erro legível em vez de falha genérica — e o MCP Server, que é
exercitado pelo protocolo real: handshake, catálogo de ferramentas e uma
ferramenta executada de ponta a ponta.

Outras salvaguardas embutidas: relatório aberto no Excel é tratado com novas
tentativas e mensagem clara; correção malformada vinda da IA é descartada sem
derrubar o lote; arquivos temporários do servidor expiram sozinhos em 1 hora.

---

## Escopo e evolução

**Escopo desta entrega.** A API está publicada **sem autenticação**, por decisão
de escopo do business case. A URL deve ser usada apenas com a planilha de
demonstração (dados sintéticos); pedidos reais contêm dados pessoais e exigem
autenticação por chave antes de trafegar por uma URL aberta. É um passo
consciente do roadmap, não um esquecimento.

**Evolução natural.** Ler os pedidos direto do ERP em vez de planilha; escrever
o status de volta no sistema de origem; notificação ativa para a gestão quando
o índice de reprovação subir; histórico entre lotes para detectar duplicidade
que atravessa execuções.
