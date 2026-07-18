"""Testa o fluxo completo do agente e verifica se os outputs foram gerados corretamente."""

import sys
from pathlib import Path

# Console Windows usa cp1252 por padrão e quebra ao imprimir ✓/✗. Força UTF-8
# na saída para o script rodar igual em qualquer sistema operacional.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from src.agente import AgenteValidador
from src.gerar_dados import gerar_planilha_exemplo

CAMINHO_ENTRADA = Path("data/pedidos_entrada.xlsx")
CAMINHO_VALIDADOS = Path("output/pedidos_validados.xlsx")
CAMINHO_REJEITADOS = Path("output/pedidos_rejeitados.xlsx")
CAMINHO_RESUMO = Path("output/resumo_execucao.xlsx")
CAMINHO_LOG = Path("output/_sistema/log_execucao.log")


def _ok(msg: str) -> None:
    print(f"[✓] {msg}")


def _falha(msg: str) -> None:
    print(f"[✗] {msg}")


def main() -> int:
    passaram = 0
    total_testes = 8

    # 1. Gerar dados de exemplo.
    gerar_planilha_exemplo()
    if CAMINHO_ENTRADA.exists():
        df_entrada = pd.read_excel(CAMINHO_ENTRADA, engine="openpyxl")
        _ok(f"Planilha de entrada gerada ({len(df_entrada)} pedidos)")
        passaram += 1
    else:
        _falha("data/pedidos_entrada.xlsx — arquivo não encontrado")
        return 1

    # 2. Executar o agente.
    try:
        agente = AgenteValidador()
        resumo = agente.executar(str(CAMINHO_ENTRADA))
        _ok("Agente executado sem erros")
        passaram += 1
    except Exception as exc:
        _falha(f"Agente levantou exceção: {exc}")
        return 1

    # 3. Relatório de válidos.
    if CAMINHO_VALIDADOS.exists():
        df_val = pd.read_excel(CAMINHO_VALIDADOS, engine="openpyxl")
        if len(df_val) > 0:
            _ok(f"pedidos_validados.xlsx gerado ({len(df_val)} linhas)")
            passaram += 1
        else:
            _falha("pedidos_validados.xlsx — sem linhas")
    else:
        _falha("pedidos_validados.xlsx — arquivo não encontrado")

    # 4. Relatório de rejeitados.
    if CAMINHO_REJEITADOS.exists():
        df_rej = pd.read_excel(CAMINHO_REJEITADOS, engine="openpyxl")
        if len(df_rej) > 0:
            _ok(f"pedidos_rejeitados.xlsx gerado ({len(df_rej)} linhas)")
            passaram += 1
        else:
            _falha("pedidos_rejeitados.xlsx — sem linhas")
    else:
        _falha("pedidos_rejeitados.xlsx — arquivo não encontrado")
        df_rej = pd.DataFrame()

    # 5. Resumo.
    if CAMINHO_RESUMO.exists():
        _ok("resumo_execucao.xlsx gerado")
        passaram += 1
    else:
        _falha("resumo_execucao.xlsx — arquivo não encontrado")

    # 6. Log.
    if CAMINHO_LOG.exists() and CAMINHO_LOG.stat().st_size > 0:
        _ok("log_execucao.log gerado")
        passaram += 1
    else:
        _falha("log_execucao.log — ausente ou vazio")

    # 7. Consistência: válidos + rejeitados == total da entrada.
    soma = resumo["total_validos"] + resumo["total_rejeitados"]
    if soma == resumo["total_processados"]:
        _ok(f"Consistência: {resumo['total_validos']} + "
            f"{resumo['total_rejeitados']} = {soma} ✓")
        passaram += 1
    else:
        _falha(f"Consistência: {soma} != {resumo['total_processados']}")

    # 8. Todos os rejeitados têm motivo preenchido.
    if not df_rej.empty and "motivo_rejeicao" in df_rej.columns:
        vazios = df_rej["motivo_rejeicao"].isna().sum() + \
            (df_rej["motivo_rejeicao"].astype(str).str.strip() == "").sum()
        if vazios == 0:
            _ok("Todos os rejeitados têm motivo de rejeição")
            passaram += 1
        else:
            _falha(f"{vazios} rejeitado(s) sem motivo de rejeição")
    else:
        _falha("Não foi possível verificar motivos de rejeição")

    print()
    if passaram == total_testes:
        print(f"Todos os {total_testes} testes passaram ✓")
        return 0
    print(f"{passaram}/{total_testes} testes passaram")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
