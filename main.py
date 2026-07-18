"""Ponto de entrada principal — modo standalone (terminal)."""

from pathlib import Path

from src.agente import AgenteValidador
from src.gerar_dados import gerar_planilha_exemplo


def main() -> None:
    caminho_dados = Path("data/pedidos_entrada.xlsx")

    # Gera dados de exemplo se a planilha não existir.
    if not caminho_dados.exists():
        print("Planilha de entrada não encontrada. Gerando dados de exemplo...")
        gerar_planilha_exemplo()

    agente = AgenteValidador()
    agente.executar(str(caminho_dados))


if __name__ == "__main__":
    main()
