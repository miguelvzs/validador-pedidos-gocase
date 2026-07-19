"""Organização dos pedidos válidos por prioridade de prazo."""

import logging
from datetime import date

import pandas as pd

from src.config import config

logger = logging.getLogger("organizador")


def _classificar(dias_restantes: int) -> str:
    """Mapeia dias restantes até o prazo para uma faixa de prioridade.

    Delega à config: as faixas são definidas em config.yaml, não no código.
    """
    return config.classificar_prioridade(dias_restantes)


def organizar_pedidos(df_validos: pd.DataFrame) -> pd.DataFrame:
    """Classifica pedidos por prioridade de prazo e ordena para produção."""
    df = df_validos.copy()

    # Trabalha vazio sem estourar: um lote sem válidos ainda deve ter as colunas.
    if df.empty:
        df["dias_restantes"] = pd.Series(dtype="int64")
        df["prioridade"] = pd.Series(dtype="object")
        logger.info("Nenhum pedido válido para organizar.")
        return df

    # Ordem lida da config a cada execução (reconfigurável sem reiniciar).
    ordem = config.ordem_prioridade

    hoje = date.today()
    df["dias_restantes"] = df["prazo_entrega"].apply(lambda d: (d.date() - hoje).days)
    df["prioridade"] = df["dias_restantes"].apply(_classificar)

    # Categoria ordenada: permite ordenar por urgência sem mapa numérico à parte.
    df["prioridade"] = pd.Categorical(
        df["prioridade"], categories=ordem, ordered=True
    )

    # Primeira faixa primeiro; dentro da mesma faixa, prazo mais apertado antes.
    df = df.sort_values(
        by=["prioridade", "dias_restantes"], ascending=[True, True]
    ).reset_index(drop=True)

    contagem = df["prioridade"].value_counts()
    for faixa in ordem:
        logger.info("Prioridade %s: %d pedido(s)", faixa, int(contagem.get(faixa, 0)))

    return df
