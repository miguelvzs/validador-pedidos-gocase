"""MCP Server — expõe o agente de validação como ferramenta chamável por qualquer IA.

Uso: python mcp_server.py
Qualquer ferramenta compatível com MCP (Claude Desktop, n8n, Cursor, etc.)
pode se conectar e chamar as tools deste servidor.
"""

import json
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.agente import CAMINHO_CACHE_RESUMO, CAMINHO_REJEITADOS, AgenteValidador
from src.assistente_ia import aplicar_correcoes, montar_contexto_correcao
from src.gerar_dados import gerar_planilha_exemplo

ENTRADA_PADRAO = "data/pedidos_entrada.xlsx"

mcp = FastMCP("Validador de Pedidos GoCase")


@mcp.tool()
def gerar_dados_exemplo() -> str:
    """Gera uma planilha de pedidos simulada para demonstração, com erros
    propositais para testar a validação."""
    caminho = gerar_planilha_exemplo()
    return f"Planilha gerada com 50 pedidos (incluindo 10 com erros) em: {caminho}"


@mcp.tool()
def validar_pedidos(caminho_entrada: str = "data/pedidos_entrada.xlsx") -> str:
    """Executa o fluxo completo: lê a planilha de pedidos, valida os dados,
    organiza por prioridade, e gera relatórios em Excel."""
    agente = AgenteValidador()
    resumo = agente.executar(caminho_entrada)
    return _formatar_resumo(resumo)


@mcp.tool()
def consultar_resumo() -> str:
    """Retorna o resumo da última execução do agente, sem executar novamente."""
    resumo = _ler_cache()
    if not resumo:
        return ("Nenhuma execução anterior encontrada. "
                "Rode a tool 'validar_pedidos' primeiro.")
    return _formatar_resumo(resumo)


@mcp.tool()
def analisar_rejeitados() -> str:
    """Prepara os pedidos rejeitados da última execução para correção pela IA.

    Retorna, por pedido: dados, motivos e sugestões mecânicas já resolvidas
    (valor_total, espaços). Você (IA) propõe as correções semânticas (nomes,
    e-mails, quantidades) e as envia para a tool 'revalidar_com_correcoes'."""
    try:
        return montar_contexto_correcao(Path(CAMINHO_REJEITADOS))
    except FileNotFoundError as exc:
        return str(exc)


@mcp.tool()
def revalidar_com_correcoes(correcoes: list[dict], caminho_entrada: str = ENTRADA_PADRAO) -> str:
    """Aplica correções aos pedidos e revalida o lote inteiro, fechando o ciclo.

    Parâmetro 'correcoes': lista de {"id_pedido", "campo", "valor"}. As correções
    atualizam a planilha de origem e o fluxo completo roda de novo, regenerando
    os relatórios. Retorna a comparação antes → depois."""
    caminho = Path(caminho_entrada)

    # Guarda o número de rejeitados de antes para mostrar o ganho da correção.
    rejeitados_antes = _ler_cache().get("total_rejeitados")

    df_corrigido = aplicar_correcoes(correcoes, caminho)
    # Backup antes de sobrescrever: a origem é dado real: guarda uma cópia .bak
    # para que uma correção equivocada da IA seja reversível.
    if caminho.exists():
        shutil.copy2(caminho, caminho.with_suffix(caminho.suffix + ".bak"))
    # A planilha de origem passa a refletir as correções (fonte da verdade no
    # ciclo RPA). O fluxo então revalida tudo e regenera os relatórios.
    df_corrigido.to_excel(caminho, index=False, engine="openpyxl")

    agente = AgenteValidador()
    resumo = agente.executar(str(caminho))

    cabecalho = "=== Revalidação após correções ===\n"
    if rejeitados_antes is not None:
        delta = rejeitados_antes - resumo["total_rejeitados"]
        cabecalho += (
            f"Rejeitados antes: {rejeitados_antes} → depois: "
            f"{resumo['total_rejeitados']}  (recuperados: {delta})\n\n"
        )
    return cabecalho + _formatar_resumo(resumo)


@mcp.prompt()
def corrigir_pedidos_rejeitados() -> str:
    """Fluxo guiado: analisar rejeitados, propor correções e revalidar."""
    return (
        "Ajude a recuperar pedidos rejeitados pelo Validador GoCase:\n"
        "1. Chame a tool 'analisar_rejeitados' para ver os pedidos e seus motivos.\n"
        "2. Para cada pedido, proponha correções: aplique as sugestões mecânicas "
        "e infira os erros semânticos (corrija nomes, complete e-mails, ajuste "
        "quantidades para valores plausíveis). NÃO invente dados que não dá para "
        "deduzir — se um cliente está totalmente vazio, sinalize para revisão humana.\n"
        "3. Envie as correções para 'revalidar_com_correcoes' e confirme quantos "
        "pedidos foram recuperados."
    )


def _ler_cache() -> dict:
    """Lê o cache do último resumo; dict vazio se não houver."""
    caminho = Path(CAMINHO_CACHE_RESUMO)
    if not caminho.exists():
        return {}
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _formatar_resumo(resumo: dict) -> str:
    """Formata o dict de resumo como texto legível para o cliente MCP."""
    prioridades = " | ".join(
        f"{nome}: {qtd}" for nome, qtd in resumo["por_prioridade"].items()
    )
    return (
        "=== Resumo da Execução — Validador GoCase ===\n"
        f"Total processados:    {resumo['total_processados']}\n"
        f"Válidos:              {resumo['total_validos']} "
        f"({resumo['percentual_validos']}%)\n"
        f"Rejeitados:           {resumo['total_rejeitados']}\n"
        "--- Prioridades ---\n"
        f"{prioridades}\n"
        "--- Valores ---\n"
        f"Válidos:    R$ {resumo['valor_total_validos']:,.2f}\n"
        f"Rejeitados: R$ {resumo['valor_total_rejeitados']:,.2f}\n"
        f"Tempo de execução: {resumo['tempo_execucao_segundos']}s"
    )


if __name__ == "__main__":
    mcp.run()
