"""Ponto de entrada principal — modo standalone (terminal)."""

import sys
from pathlib import Path

from src.agente import AgenteValidador
from src.gerar_dados import gerar_planilha_exemplo

# Console Windows usa cp1252 e corrompe os acentos dos avisos ao usuário.
# Reconfigura stdout para UTF-8 para os prints saírem legíveis em qualquer SO.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    caminho_dados = Path("data/pedidos_entrada.xlsx")

    # Gera dados de exemplo se a planilha não existir. Aviso em destaque: sem
    # esta ressalva, o gestor que esquecer de colocar a planilha real acha que
    # os relatórios refletem pedidos verdadeiros, quando são dados fictícios.
    if not caminho_dados.exists():
        print("=" * 60)
        print("  ATENÇÃO: planilha de entrada NÃO encontrada em")
        print(f"  {caminho_dados}")
        print("  Gerando DADOS DE EXEMPLO (fictícios) para demonstração.")
        print("  Os relatórios NÃO refletirão pedidos reais.")
        print("  Para usar dados reais, coloque sua planilha nesse caminho")
        print("  e rode novamente.")
        print("=" * 60)
        gerar_planilha_exemplo()

    agente = AgenteValidador()
    agente.executar(str(caminho_dados))


if __name__ == "__main__":
    main()
