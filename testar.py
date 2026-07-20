"""Testa o fluxo completo do agente e verifica se os outputs foram gerados corretamente."""

import io
import json
import subprocess
import sys
import threading
import zipfile
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
    total_testes = 13

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

    # 9-11. API HTTP — o caminho realmente usado em produção.
    passaram += _testar_api(CAMINHO_ENTRADA.read_bytes())

    # 12-13. MCP Server — a superfície para clientes de IA.
    passaram += _testar_mcp()

    print()
    if passaram == total_testes:
        print(f"Todos os {total_testes} testes passaram ✓")
        return 0
    print(f"{passaram}/{total_testes} testes passaram")
    return 1


def _testar_api(planilha: bytes) -> int:
    """Exercita a API em memória (sem subir servidor) e devolve quantos passaram.

    Cobre o caminho que o n8n e o navegador usam de verdade: validar, baixar o
    pacote de relatórios e recusar planilha fora do formato.
    """
    from fastapi.testclient import TestClient

    import api

    cliente = TestClient(api.app)
    passaram = 0

    # 9. POST /validar devolve job_id e resumo coerente.
    resposta = cliente.post("/validar", files={"arquivo": ("pedidos.xlsx", planilha)})
    if resposta.status_code == 200:
        corpo = resposta.json()
        resumo = corpo["resumo"]
        if resumo["total_validos"] + resumo["total_rejeitados"] == resumo["total_processados"]:
            _ok(f"API POST /validar ({resumo['total_validos']} válidos, "
                f"{resumo['total_rejeitados']} rejeitados)")
            passaram += 1
        else:
            _falha("API POST /validar — resumo inconsistente")
        job_id = corpo["job_id"]
    else:
        _falha(f"API POST /validar — HTTP {resposta.status_code}")
        job_id = None

    # 10. GET /download devolve o .zip com os 3 relatórios.
    if job_id:
        zip_resp = cliente.get(f"/download/{job_id}")
        nomes = []
        if zip_resp.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as pacote:
                nomes = pacote.namelist()
        if len(nomes) == 3:
            _ok(f"API GET /download — .zip com {len(nomes)} relatórios")
            passaram += 1
        else:
            _falha(f"API GET /download — esperado 3 relatórios, veio {len(nomes)}")
    else:
        _falha("API GET /download — sem job_id para consultar")

    # 11. Planilha fora do formato é recusada com erro legível (não 500).
    invalida = io.BytesIO()
    pd.DataFrame({"coluna_errada": [1]}).to_excel(invalida, index=False, engine="openpyxl")
    erro = cliente.post("/validar", files={"arquivo": ("ruim.xlsx", invalida.getvalue())})
    if erro.status_code == 422:
        _ok("API recusa planilha fora do formato (HTTP 422)")
        passaram += 1
    else:
        _falha(f"API deveria responder 422 para planilha inválida, veio {erro.status_code}")

    return passaram


def _testar_mcp() -> int:
    """Conversa com o MCP Server pelo protocolo real e devolve quantos passaram.

    Sobe `mcp_server.py` como subprocesso, faz o handshake JSON-RPC por stdio e
    confere que as ferramentas existem e respondem — a mesma coisa que um
    cliente de IA faz ao se conectar.
    """
    pedidos = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "testar", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "validar_pedidos", "arguments": {}}},
    ]
    processo = subprocess.Popen(
        [sys.executable, "mcp_server.py"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )

    # Rede de segurança: se o servidor travar, encerra em vez de pendurar o teste.
    vigia = threading.Timer(120, processo.kill)
    vigia.start()

    respostas = {}
    try:
        for pedido in pedidos:
            processo.stdin.write(json.dumps(pedido) + "\n")
        processo.stdin.flush()

        # Lê até a resposta da última chamada. O stdin fica aberto: fechá-lo
        # antes encerraria o servidor e a resposta se perderia.
        for linha in processo.stdout:
            linha = linha.strip()
            if not linha:
                continue
            try:
                msg = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if msg.get("id") is not None:
                respostas[msg["id"]] = msg
            if 3 in respostas:
                break
    except (BrokenPipeError, OSError):
        pass
    finally:
        vigia.cancel()
        processo.kill()
        processo.wait()

    passaram = 0

    # 12. Handshake e catálogo de ferramentas.
    ferramentas = respostas.get(2, {}).get("result", {}).get("tools", [])
    if len(ferramentas) == 5:
        _ok(f"MCP responde com {len(ferramentas)} ferramentas")
        passaram += 1
    else:
        _falha(f"MCP — esperado 5 ferramentas, veio {len(ferramentas)}")

    # 13. Uma ferramenta executada de verdade, ponta a ponta.
    conteudo = respostas.get(3, {}).get("result", {}).get("content", [])
    texto = conteudo[0]["text"] if conteudo else ""
    if "Total processados" in texto:
        _ok("MCP executa validar_pedidos e devolve o resumo")
        passaram += 1
    else:
        _falha("MCP — validar_pedidos não devolveu o resumo esperado")

    return passaram


if __name__ == "__main__":
    raise SystemExit(main())
