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

# Caminhos de saída padronizados num só lugar para evitar strings soltas.
DIR_DATA = Path("data")
DIR_OUTPUT = Path("output")
# Artefatos internos (log/cache) ficam numa subpasta separada para que o
# operador veja apenas as 3 planilhas em output/, sem lixo técnico no meio.
DIR_SISTEMA = DIR_OUTPUT / "_sistema"
CAMINHO_VALIDADOS = DIR_OUTPUT / "pedidos_validados.xlsx"
CAMINHO_REJEITADOS = DIR_OUTPUT / "pedidos_rejeitados.xlsx"
CAMINHO_RESUMO = DIR_OUTPUT / "resumo_execucao.xlsx"
CAMINHO_LOG = DIR_SISTEMA / "log_execucao.log"
# Cache do último resumo: permite consultar_resumo sem reexecutar o pipeline.
CAMINHO_CACHE_RESUMO = DIR_SISTEMA / "ultimo_resumo.json"


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
        """Executa o pipeline completo e retorna o dict de resumo.

        Cada etapa é isolada em try/except: uma falha é logada mas não aborta
        as etapas seguintes que ainda fizerem sentido.
        """
        inicio = time.perf_counter()
        self.logger.info("Iniciando execução do agente validador.")

        df_original = pd.DataFrame()
        df_validos = pd.DataFrame()
        df_rejeitados = pd.DataFrame()
        df_organizados = pd.DataFrame()

        # Etapa 1: leitura.
        try:
            self.logger.info("[Etapa 1/5] Lendo planilha de entrada...")
            df_original = ler_planilha(Path(caminho_entrada))
            self.logger.info("[Etapa 1/5] Leitura concluída.")
        except Exception as exc:
            self.logger.error("[Etapa 1/5] Falha na leitura: %s", exc)
            # Sem dados de entrada não há o que validar: encerra com resumo vazio.
            return self._montar_resumo(df_validos, df_rejeitados, df_original,
                                       time.perf_counter() - inicio)

        # Etapa 2: validação.
        try:
            self.logger.info("[Etapa 2/5] Validando pedidos...")
            df_validos, df_rejeitados = validar_pedidos(df_original)
            self.logger.info("[Etapa 2/5] Validação concluída.")
        except Exception as exc:
            self.logger.error("[Etapa 2/5] Falha na validação: %s", exc)

        # Etapa 3: organização dos válidos.
        try:
            self.logger.info("[Etapa 3/5] Organizando por prioridade...")
            df_organizados = organizar_pedidos(df_validos)
            self.logger.info("[Etapa 3/5] Organização concluída.")
        except Exception as exc:
            self.logger.error("[Etapa 3/5] Falha na organização: %s", exc)
            df_organizados = df_validos

        tempo_execucao = time.perf_counter() - inicio

        # Resumo montado uma única vez aqui: fonte de verdade das métricas,
        # consumida tanto pelo relatório quanto pelo log e pelo cache.
        resumo = self._montar_resumo(df_organizados, df_rejeitados, df_original, tempo_execucao)

        # Etapa 4: relatórios. Cada arquivo é isolado para que a falha de um
        # não impeça a geração dos demais.
        self.logger.info("[Etapa 4/5] Gerando relatórios Excel...")
        for descricao, funcao in (
            ("validados", lambda: gerar_relatorio_validados(df_organizados, CAMINHO_VALIDADOS)),
            ("rejeitados", lambda: gerar_relatorio_rejeitados(df_rejeitados, CAMINHO_REJEITADOS)),
            ("resumo", lambda: gerar_resumo_execucao(resumo, CAMINHO_RESUMO)),
        ):
            try:
                funcao()
            except Exception as exc:
                self.logger.error("[Etapa 4/5] Falha ao gerar relatório %s: %s", descricao, exc)
        self.logger.info("[Etapa 4/5] Relatórios concluídos.")

        # Etapa 5: registra o resumo no log e no cache (usado pelo MCP).
        self.logger.info("[Etapa 5/5] Resumo da execução:")
        self._logar_resumo(resumo)
        self._salvar_cache_resumo(resumo)

        self.logger.info("Execução finalizada em %.2fs.", resumo["tempo_execucao_segundos"])
        return resumo

    def _montar_resumo(self, df_validos: pd.DataFrame, df_rejeitados: pd.DataFrame,
                       df_original: pd.DataFrame, tempo_execucao: float) -> dict:
        """Delega para a função de módulo montar_resumo (reutilizável pela API)."""
        return montar_resumo(df_validos, df_rejeitados, df_original, tempo_execucao)

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
