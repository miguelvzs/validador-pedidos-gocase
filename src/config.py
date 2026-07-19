"""Carregamento de configuração externa (config.yaml).

Centraliza os parâmetros de negócio que antes eram hardcoded — tolerância de
valor, regex de e-mail, colunas obrigatórias e faixas de prioridade — para que
um gestor não-técnico ajuste regras editando um YAML, sem tocar no código.

Se o arquivo estiver ausente ou uma chave faltar, o sistema cai nos padrões
embutidos aqui: nunca quebra por config incompleta.
"""

import logging
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("config")

CAMINHO_CONFIG = Path("config.yaml")

# Padrões embutidos: fonte da verdade quando o YAML não cobre algo.
_PADROES: dict[str, Any] = {
    "validacao": {
        "tolerancia_valor": 0.02,
        "regex_email": r"^[^@]+@[^@]+\.[^@]+$",
        "mapa_colunas": {},
        "colunas_obrigatorias": [
            "id_pedido", "data_pedido", "cliente", "email", "produto", "sku",
            "quantidade", "valor_unitario", "valor_total", "canal", "endereco",
            "prazo_entrega",
        ],
    },
    "prioridade": {
        "faixas": [
            {"nome": "URGENTE", "min": 0, "max": 2},
            {"nome": "ALTA", "min": 3, "max": 5},
            {"nome": "NORMAL", "min": 6, "max": 10},
            {"nome": "BAIXA", "min": 11, "max": None},
        ],
    },
}


class Config:
    """Acesso tipado à configuração, com fallback para os padrões embutidos."""

    def __init__(self, dados: dict[str, Any]) -> None:
        self._dados = dados

    # --- Validação ---
    @property
    def tolerancia_valor(self) -> float:
        return float(self._dados["validacao"]["tolerancia_valor"])

    @property
    def regex_email(self) -> str:
        return self._dados["validacao"]["regex_email"]

    @property
    def colunas_obrigatorias(self) -> list[str]:
        return list(self._dados["validacao"]["colunas_obrigatorias"])

    @property
    def mapa_colunas(self) -> dict[str, str]:
        """Renomeação de colunas da planilha de origem para os nomes canônicos."""
        return dict(self._dados["validacao"].get("mapa_colunas") or {})

    # --- Prioridade ---
    @property
    def faixas_prioridade(self) -> list[dict[str, Any]]:
        return list(self._dados["prioridade"]["faixas"])

    @property
    def ordem_prioridade(self) -> list[str]:
        """Nomes das faixas na ordem definida (fila de produção)."""
        return [f["nome"] for f in self.faixas_prioridade]

    def classificar_prioridade(self, dias_restantes: int) -> str:
        """Mapeia dias restantes para o nome da faixa, conforme o YAML.

        max nulo = faixa sem teto. Se nada casar (dias negativos fora das
        faixas), devolve a primeira faixa (mais urgente) por segurança.
        """
        for faixa in self.faixas_prioridade:
            minimo = faixa["min"]
            maximo = faixa["max"]
            if dias_restantes >= minimo and (maximo is None or dias_restantes <= maximo):
                return faixa["nome"]
        return self.faixas_prioridade[0]["nome"]


def _mesclar(padrao: dict, sobre: dict) -> dict:
    """Mescla recursivamente `sobre` sobre `padrao` (sobre vence nas folhas)."""
    resultado = dict(padrao)
    for chave, valor in sobre.items():
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave] = _mesclar(resultado[chave], valor)
        elif valor is not None:
            resultado[chave] = valor
    return resultado


def carregar_config(caminho: Path = CAMINHO_CONFIG) -> Config:
    """Lê o config.yaml e o mescla sobre os padrões embutidos.

    Ausência do arquivo ou YAML inválido não quebra: loga aviso e usa padrões.
    """
    dados = _PADROES
    caminho = Path(caminho)
    if caminho.exists():
        try:
            with open(caminho, encoding="utf-8") as arquivo:
                do_arquivo = yaml.safe_load(arquivo) or {}
            dados = _mesclar(_PADROES, do_arquivo)
            logger.info("Configuração carregada de %s", caminho)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Falha ao ler %s (%s). Usando padrões embutidos.", caminho, exc)
            # Aviso direto no stderr: este código roda no import, antes do
            # logging estar configurado, então o gestor precisa ver que a
            # edição do YAML foi IGNORADA e o sistema voltou aos padrões.
            print(
                f"[AVISO] config.yaml inválido ({exc}). "
                "Suas alterações foram IGNORADAS; usando valores-padrão. "
                "Verifique a indentação do arquivo.",
                file=sys.stderr,
            )
    else:
        logger.info("config.yaml ausente. Usando padrões embutidos.")
    return Config(dados)


# Instância única compartilhada por todos os módulos.
config = carregar_config()
