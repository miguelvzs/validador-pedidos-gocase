"""Agente orquestrador do fluxo de validação de pedidos."""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config import config
from src.leitor import ler_planilha
from src.organizador import organizar_pedidos
from src.relatorio import (
    gerar_relatorio_rejeitados,
    gerar_relatorio_validados,
    gerar_resumo_execucao,
)
from src.validador import validar_pedidos

# Nomes dos relatórios: fonte única, usada tanto pelo modo arquivo quanto pela
# API (que grava os mesmos arquivos na pasta do job).
NOMES_RELATORIOS = {
    "validados": "pedidos_validados.xlsx",
    "rejeitados": "pedidos_rejeitados.xlsx",
    "resumo": "resumo_execucao.xlsx",
}

# Caminhos de saída padronizados num só lugar para evitar strings soltas.
DIR_DATA = Path("data")
DIR_OUTPUT = Path("output")
# Artefatos internos (log/cache) ficam numa subpasta separada para que o
# operador veja apenas as 3 planilhas em output/, sem lixo técnico no meio.
DIR_SISTEMA = DIR_OUTPUT / "_sistema"
CAMINHO_VALIDADOS = DIR_OUTPUT / NOMES_RELATORIOS["validados"]
CAMINHO_REJEITADOS = DIR_OUTPUT / NOMES_RELATORIOS["rejeitados"]
CAMINHO_RESUMO = DIR_OUTPUT / NOMES_RELATORIOS["resumo"]
CAMINHO_LOG = DIR_SISTEMA / "log_execucao.log"
# Cache do último resumo: permite consultar_resumo sem reexecutar o pipeline.
CAMINHO_CACHE_RESUMO = DIR_SISTEMA / "ultimo_resumo.json"


def executar_pipeline(caminho_entrada: Path, dir_saida: Path) -> dict:
    """Executa o fluxo completo e grava os 3 relatórios em `dir_saida`.

    Fonte única do pipeline: leitura → validação → organização → resumo →
    relatórios. Usada tanto pelo modo arquivo (AgenteValidador, saída fixa em
    output/) quanto pela API (saída na pasta do job), evitando duas
    implementações da mesma sequência.

    Retorna o dict de resumo. Propaga exceções para quem chama decidir como
    reportá-las (log no modo arquivo, HTTP 422 na API).
    """
    inicio = time.perf_counter()

    df_original = ler_planilha(caminho_entrada)
    df_validos, df_rejeitados = validar_pedidos(df_original)
    df_organizados = organizar_pedidos(df_validos)

    resumo = montar_resumo(df_organizados, df_rejeitados, df_original,
                           time.perf_counter() - inicio)

    os.makedirs(dir_saida, exist_ok=True)
    gerar_relatorio_validados(df_organizados, dir_saida / NOMES_RELATORIOS["validados"])
    gerar_relatorio_rejeitados(df_rejeitados, dir_saida / NOMES_RELATORIOS["rejeitados"])
    gerar_resumo_execucao(resumo, dir_saida / NOMES_RELATORIOS["resumo"])

    return resumo


def montar_resumo(df_validos: pd.DataFrame, df_rejeitados: pd.DataFrame,
                  df_original: pd.DataFrame, tempo_execucao: float) -> dict:
    """Consolida TODAS as métricas da execução num único dict.

    Fonte de verdade: log, planilha de resumo, cache MCP e API consomem este
    dict, sem recalcular. As faixas de prioridade seguem a ordem da config,
    então renomear/reordenar no config.yaml reflete aqui.
    """
    total = len(df_original)
    n_validos = len(df_validos)
    n_rejeitados = len(df_rejeitados)

    # Contagem por faixa, na ordem da config (0 quando a faixa não tem itens).
    if "prioridade" in df_validos.columns and not df_validos.empty:
        contagem = df_validos["prioridade"].value_counts()
    else:
        contagem = pd.Series(dtype="int64")
    por_prioridade = {
        faixa: int(contagem.get(faixa, 0)) for faixa in config.ordem_prioridade
    }

    # Pedidos por canal, a partir da base original.
    if "canal" in df_original.columns and not df_original.empty:
        por_canal = {c: int(q) for c, q in df_original["canal"].value_counts().items()}
    else:
        por_canal = {}

    # Quantos dos válidos foram recuperados pela IA (coluna só existe quando o
    # lote passou pelo ciclo de correção assistida).
    if "corrigido_por_ia" in df_validos.columns and not df_validos.empty:
        corrigidos_por_ia = int((df_validos["corrigido_por_ia"] == "Sim").sum())
    else:
        corrigidos_por_ia = 0

    valor_validos = float(df_validos["valor_total"].sum()) if not df_validos.empty else 0.0
    valor_rejeitados = (
        float(df_rejeitados["valor_total"].sum(min_count=1) or 0.0)
        if not df_rejeitados.empty else 0.0
    )

    return {
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "total_processados": total,
        "total_validos": n_validos,
        "total_rejeitados": n_rejeitados,
        "percentual_validos": round((n_validos / total * 100) if total else 0.0, 1),
        "percentual_rejeitados": round((n_rejeitados / total * 100) if total else 0.0, 1),
        "por_prioridade": por_prioridade,
        "por_canal": por_canal,
        "corrigidos_por_ia": corrigidos_por_ia,
        "valor_total_validos": round(valor_validos, 2),
        "valor_total_rejeitados": round(valor_rejeitados, 2),
        "tempo_execucao_segundos": round(tempo_execucao, 2),
    }


class AgenteValidador:
    """Agente que orquestra o fluxo completo de validação de pedidos.

    Fluxo: Leitura → Validação → Organização → Relatórios → Notificação

    Pode ser executado via terminal (main.py) ou chamado via MCP Server.
    """

    def __init__(self) -> None:
        # Diretórios primeiro: logging em arquivo exige a subpasta _sistema/
        # pronta (makedirs cria output/ junto, por ser o pai).
        os.makedirs(DIR_DATA, exist_ok=True)
        os.makedirs(DIR_SISTEMA, exist_ok=True)

        self._configurar_logging()
        self.logger = logging.getLogger("agente")

    def _configurar_logging(self) -> None:
        """Configura logging para console e arquivo, ambos em UTF-8."""
        logger_raiz = logging.getLogger()
        logger_raiz.setLevel(logging.INFO)

        # Evita handlers duplicados quando o agente é instanciado mais de uma
        # vez no mesmo processo (ex.: MCP Server chamando várias vezes).
        for handler in list(logger_raiz.handlers):
            logger_raiz.removeHandler(handler)

        formato = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

        # Log vai para stderr, não stdout: no modo MCP (stdio) o stdout carrega
        # o protocolo JSON-RPC e qualquer log ali corromperia as mensagens.
        # stderr fica livre para diagnóstico e o console continua legível.
        # Reconfigura para UTF-8 porque o console Windows (cp1252) corrompe acentos.
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")

        handler_console = logging.StreamHandler(sys.stderr)
        handler_console.setFormatter(formato)

        # encoding UTF-8 explícito: mensagens têm acentos e caracteres BR.
        handler_arquivo = logging.FileHandler(CAMINHO_LOG, encoding="utf-8")
        handler_arquivo.setFormatter(formato)

        logger_raiz.addHandler(handler_console)
        logger_raiz.addHandler(handler_arquivo)

    def executar(self, caminho_entrada: str = "data/pedidos_entrada.xlsx") -> dict:
        """Executa o pipeline sobre a planilha e grava os relatórios em output/.

        Delega o fluxo para `executar_pipeline` (fonte única, compartilhada com
        a API) e cuida do que é próprio do modo arquivo: log, cache do resumo e
        tratamento de falha sem derrubar o processo.
        """
        self.logger.info("Iniciando execução do agente validador.")

        try:
            resumo = executar_pipeline(Path(caminho_entrada), DIR_OUTPUT)
        except Exception as exc:
            # Modo arquivo não propaga exceção: registra e devolve resumo vazio,
            # para que quem chamou (terminal, MCP) siga com uma resposta útil.
            self.logger.error("Falha na execução: %s", exc)
            vazio = pd.DataFrame()
            return montar_resumo(vazio, vazio, vazio, 0.0)

        self.logger.info("Resumo da execução:")
        self._logar_resumo(resumo)
        self._salvar_cache_resumo(resumo)

        self.logger.info("Execução finalizada em %.2fs.", resumo["tempo_execucao_segundos"])
        return resumo

    def _logar_resumo(self, resumo: dict) -> None:
        """Escreve o resumo no log, de forma legível."""
        self.logger.info("  Processados: %d | Válidos: %d (%.1f%%) | Rejeitados: %d",
                         resumo["total_processados"], resumo["total_validos"],
                         resumo["percentual_validos"], resumo["total_rejeitados"])
        prioridades = " | ".join(f"{k}: {v}" for k, v in resumo["por_prioridade"].items())
        self.logger.info("  Prioridades: %s", prioridades)
        self.logger.info("  Valores: válidos R$ %.2f | rejeitados R$ %.2f",
                         resumo["valor_total_validos"], resumo["valor_total_rejeitados"])

    def _salvar_cache_resumo(self, resumo: dict) -> None:
        """Persiste o último resumo em JSON para consulta posterior via MCP."""
        with open(CAMINHO_CACHE_RESUMO, "w", encoding="utf-8") as arquivo:
            json.dump(resumo, arquivo, ensure_ascii=False, indent=2)
