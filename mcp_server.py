"""MCP Server — expõe o agente de validação como ferramenta chamável por qualquer IA.

Uso: python mcp_server.py
Qualquer ferramenta compatível com MCP (Claude Desktop, n8n, Cursor, etc.)
pode se conectar e chamar as tools deste servidor.
"""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.agente import CAMINHO_CACHE_RESUMO, AgenteValidador
from src.gerar_dados import gerar_planilha_exemplo

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
    caminho = Path(CAMINHO_CACHE_RESUMO)
    if not caminho.exists():
        return ("Nenhuma execução anterior encontrada. "
                "Rode a tool 'validar_pedidos' primeiro.")
    with open(caminho, encoding="utf-8") as arquivo:
        resumo = json.load(arquivo)
    return _formatar_resumo(resumo)


def _formatar_resumo(resumo: dict) -> str:
    """Formata o dict de resumo como texto legível para o cliente MCP."""
    return (
        "=== Resumo da Execução — Validador GoCase ===\n"
        f"Total processados:    {resumo['total_processados']}\n"
        f"Válidos:              {resumo['total_validos']} "
        f"({resumo['percentual_validos']}%)\n"
        f"Rejeitados:           {resumo['total_rejeitados']}\n"
        "--- Prioridades ---\n"
        f"URGENTE: {resumo['urgentes']} | ALTA: {resumo['alta']} | "
        f"NORMAL: {resumo['normal']} | BAIXA: {resumo['baixa']}\n"
        "--- Valores ---\n"
        f"Válidos:    R$ {resumo['valor_total_validos']:,.2f}\n"
        f"Rejeitados: R$ {resumo['valor_total_rejeitados']:,.2f}\n"
        f"Tempo de execução: {resumo['tempo_execucao_segundos']}s"
    )


if __name__ == "__main__":
    mcp.run()
