"""Abstração das fontes de entrada e saída.

Hoje as implementações são locais (arquivo/log). A interface foi desenhada
para que, no futuro, cada implementação possa ser trocada por um conector MCP
(Google Sheets, ERP, Slack, Email) sem alterar o resto do agente.
"""

import logging
from pathlib import Path

import pandas as pd


class LeitorDados:
    """Abstração para leitura de dados de pedidos.

    Hoje: lê arquivo Excel local.
    Futuro: conectável via MCP a Google Sheets, ERP, banco de dados, etc.
    A interface permanece a mesma — só a implementação muda.
    """

    def ler(self, origem: str | Path) -> pd.DataFrame:
        """Lê os pedidos da origem informada e devolve um DataFrame tipado."""
        # Implementação atual: arquivo local.
        from src.leitor import ler_planilha
        return ler_planilha(Path(origem))


class Notificador:
    """Abstração para envio de notificações e alertas.

    Hoje: loga no console e arquivo.
    Futuro: conectável via MCP a Slack, Email, Teams, etc.
    """

    def enviar_resumo(self, resumo: dict) -> None:
        """Publica o resumo consolidado da execução."""
        # Implementação atual: log local.
        logger = logging.getLogger("agente")
        logger.info("=" * 50)
        logger.info("RESUMO DA EXECUÇÃO")
        for chave, valor in resumo.items():
            logger.info("  %s: %s", chave, valor)
        logger.info("=" * 50)

    def enviar_alerta(self, mensagem: str, nivel: str = "info") -> None:
        """Emite um alerta pontual no nível de log informado."""
        # Implementação atual: log local. Futuro: Slack webhook, email, etc.
        logger = logging.getLogger("agente")
        getattr(logger, nivel, logger.info)(f"ALERTA: {mensagem}")
