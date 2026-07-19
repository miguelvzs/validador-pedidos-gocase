"""Leitura e tipagem da planilha de pedidos."""

import logging
from pathlib import Path

import pandas as pd

from src.config import config

logger = logging.getLogger("leitor")

# Colunas de data/numéricas são estruturais do domínio (não configuráveis).
COLUNAS_DATA = ["data_pedido", "prazo_entrega"]
COLUNAS_NUMERICAS = ["quantidade", "valor_unitario", "valor_total"]


def ler_planilha(caminho: Path) -> pd.DataFrame:
    """Lê a planilha de pedidos e retorna um DataFrame tipado.

    Converte datas para datetime e valores para float. Levanta ValueError se
    alguma coluna esperada estiver ausente.
    """
    caminho = Path(caminho)
    try:
        df = pd.read_excel(caminho, engine="openpyxl")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Arquivo não encontrado: {caminho}. "
            "Execute primeiro: python -m src.gerar_dados"
        ) from exc

    # Renomeia colunas da planilha de origem para os nomes canônicos ANTES da
    # checagem: permite processar um export real (cabeçalhos diferentes) sem
    # editar código — basta preencher mapa_colunas no config.yaml.
    mapa = config.mapa_colunas
    if mapa:
        df = df.rename(columns=mapa)
        logger.info("Mapa de colunas aplicado: %s", mapa)

    # Colunas obrigatórias lidas da config a cada execução (reconfigurável).
    faltantes = [c for c in config.colunas_obrigatorias if c not in df.columns]
    if faltantes:
        raise ValueError(
            "Colunas obrigatórias ausentes na planilha: "
            + ", ".join(faltantes)
            + ". Se sua planilha usa outros nomes, configure 'mapa_colunas' "
            "no config.yaml."
        )

    # Datas: coerce transforma valores inválidos em NaT em vez de estourar,
    # deixando a decisão de rejeição para o validador.
    for coluna in COLUNAS_DATA:
        df[coluna] = pd.to_datetime(df[coluna], errors="coerce")

    # Numéricos: idem — texto/branco vira NaN e é tratado na validação.
    for coluna in COLUNAS_NUMERICAS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    logger.info(
        "Planilha lida: %d linhas, %d colunas (%s)",
        len(df), df.shape[1], caminho,
    )
    return df
