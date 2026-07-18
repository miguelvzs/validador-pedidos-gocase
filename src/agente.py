"""Agente orquestrador do fluxo de validação de pedidos."""

import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

from src.integracoes import LeitorDados, Notificador
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

        self.leitor = LeitorDados()
        self.notificador = Notificador()

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
            df_original = self.leitor.ler(caminho_entrada)
            self.logger.info("[Etapa 1/5] Leitura concluída.")
        except Exception as exc:
            self.logger.error("[Etapa 1/5] Falha na leitura: %s", exc)
            self.notificador.enviar_alerta(f"Leitura falhou: {exc}", "error")
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
            self.notificador.enviar_alerta(f"Validação falhou: {exc}", "error")

        # Etapa 3: organização dos válidos.
        try:
            self.logger.info("[Etapa 3/5] Organizando por prioridade...")
            df_organizados = organizar_pedidos(df_validos)
            self.logger.info("[Etapa 3/5] Organização concluída.")
        except Exception as exc:
            self.logger.error("[Etapa 3/5] Falha na organização: %s", exc)
            self.notificador.enviar_alerta(f"Organização falhou: {exc}", "error")
            df_organizados = df_validos

        tempo_execucao = time.perf_counter() - inicio

        # Etapa 4: relatórios. Cada arquivo é isolado para que a falha de um
        # não impeça a geração dos demais.
        self.logger.info("[Etapa 4/5] Gerando relatórios Excel...")
        for descricao, funcao in (
            ("validados", lambda: gerar_relatorio_validados(df_organizados, CAMINHO_VALIDADOS)),
            ("rejeitados", lambda: gerar_relatorio_rejeitados(df_rejeitados, CAMINHO_REJEITADOS)),
            ("resumo", lambda: gerar_resumo_execucao(
                df_organizados, df_rejeitados, df_original, tempo_execucao, CAMINHO_RESUMO)),
        ):
            try:
                funcao()
            except Exception as exc:
                self.logger.error("[Etapa 4/5] Falha ao gerar relatório %s: %s", descricao, exc)
                self.notificador.enviar_alerta(f"Relatório {descricao} falhou: {exc}", "error")
        self.logger.info("[Etapa 4/5] Relatórios concluídos.")

        # Etapa 5: resumo e notificação.
        resumo = self._montar_resumo(df_organizados, df_rejeitados, df_original, tempo_execucao)
        try:
            self.logger.info("[Etapa 5/5] Enviando resumo...")
            self.notificador.enviar_resumo(resumo)
            self._salvar_cache_resumo(resumo)
            self.logger.info("[Etapa 5/5] Resumo enviado.")
        except Exception as exc:
            self.logger.error("[Etapa 5/5] Falha ao notificar resumo: %s", exc)

        self.logger.info("Execução finalizada em %.2fs.", resumo["tempo_execucao_segundos"])
        return resumo

    def _montar_resumo(self, df_validos: pd.DataFrame, df_rejeitados: pd.DataFrame,
                       df_original: pd.DataFrame, tempo_execucao: float) -> dict:
        """Consolida as métricas da execução no dict de resumo."""
        total = len(df_original)
        n_validos = len(df_validos)
        n_rejeitados = len(df_rejeitados)

        if "prioridade" in df_validos.columns and not df_validos.empty:
            contagem = df_validos["prioridade"].value_counts()
        else:
            contagem = pd.Series(dtype="int64")

        valor_validos = float(df_validos["valor_total"].sum()) if not df_validos.empty else 0.0
        valor_rejeitados = (
            float(df_rejeitados["valor_total"].sum(min_count=1) or 0.0)
            if not df_rejeitados.empty else 0.0
        )

        return {
            "total_processados": total,
            "total_validos": n_validos,
            "total_rejeitados": n_rejeitados,
            "percentual_validos": round((n_validos / total * 100) if total else 0.0, 1),
            "urgentes": int(contagem.get("URGENTE", 0)),
            "alta": int(contagem.get("ALTA", 0)),
            "normal": int(contagem.get("NORMAL", 0)),
            "baixa": int(contagem.get("BAIXA", 0)),
            "valor_total_validos": round(valor_validos, 2),
            "valor_total_rejeitados": round(valor_rejeitados, 2),
            "tempo_execucao_segundos": round(tempo_execucao, 2),
        }

    def _salvar_cache_resumo(self, resumo: dict) -> None:
        """Persiste o último resumo em JSON para consulta posterior via MCP."""
        with open(CAMINHO_CACHE_RESUMO, "w", encoding="utf-8") as arquivo:
            json.dump(resumo, arquivo, ensure_ascii=False, indent=2)
