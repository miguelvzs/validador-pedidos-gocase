"""API HTTP do Validador de Pedidos GoCase (FastAPI).

Núcleo de serviço: recebe uma planilha, roda o MESMO pipeline do modo
standalone (leitura → validação → organização → relatórios) e devolve o resumo
em JSON + os relatórios para download.

Elimina a dependência no cliente: quem consome (frontend Streamlit, Power
Automate, n8n, ou um navegador) só precisa falar HTTP.

Rodar: uvicorn api:app --host 0.0.0.0 --port 8000
Docs interativas: http://localhost:8000/docs
"""

import base64
import binascii
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.agente import montar_resumo
from src.leitor import ler_planilha
from src.organizador import organizar_pedidos
from src.relatorio import (
    gerar_relatorio_rejeitados,
    gerar_relatorio_validados,
    gerar_resumo_execucao,
)
from src.validador import validar_pedidos

app = FastAPI(
    title="Validador de Pedidos GoCase",
    description="Valida e organiza pedidos de fábrica. Núcleo reutilizável por "
                "frontend, Power Automate, n8n ou navegador.",
    version="1.0.0",
)

# Diretório de trabalho dos jobs: cada requisição gera uma subpasta isolada,
# identificada por um job_id, para que uploads simultâneos não colidam.
JOBS_DIR = Path(tempfile.gettempdir()) / "validador_gocase_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Tempo de vida de um job em segundos. Passado esse prazo, a pasta é apagada
# na próxima requisição (limpeza preguiçosa). Configurável por ambiente.
TTL_JOBS_SEG = int(os.environ.get("JOBS_TTL_SEGUNDOS", "3600"))  # 1 hora

NOMES_RELATORIOS = {
    "validados": "pedidos_validados.xlsx",
    "rejeitados": "pedidos_rejeitados.xlsx",
    "resumo": "resumo_execucao.xlsx",
}


def _limpar_jobs_antigos() -> None:
    """Remove pastas de jobs mais velhas que o TTL.

    Limpeza preguiçosa: roda a cada nova validação, sem thread nem agendador.
    Usa o mtime da pasta (atualizado quando os relatórios são escritos) para
    decidir a idade. Falha em apagar um job (ex.: em uso) é ignorada — a
    próxima requisição tenta de novo.
    """
    limite = time.time() - TTL_JOBS_SEG
    for pasta in JOBS_DIR.iterdir():
        if pasta.is_dir() and pasta.stat().st_mtime < limite:
            shutil.rmtree(pasta, ignore_errors=True)


@app.get("/")
def raiz() -> dict:
    """Health check simples."""
    return {"servico": "Validador de Pedidos GoCase", "status": "ok"}


def _processar(conteudo: bytes) -> dict:
    """Roda o pipeline sobre os bytes de um .xlsx e devolve {job_id, resumo}.

    Núcleo compartilhado pelos endpoints multipart (/validar) e base64
    (/validar-base64), para não duplicar a lógica.
    """
    _limpar_jobs_antigos()  # varre jobs vencidos antes de criar um novo

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    entrada = job_dir / "entrada.xlsx"
    entrada.write_bytes(conteudo)

    inicio = time.perf_counter()
    try:
        df_original = ler_planilha(entrada)
        df_validos, df_rejeitados = validar_pedidos(df_original)
        df_organizados = organizar_pedidos(df_validos)
    except ValueError as exc:
        # Erro de dados (coluna faltando etc.): resposta clara, não 500.
        raise HTTPException(status_code=422, detail=str(exc))

    tempo = time.perf_counter() - inicio
    resumo = montar_resumo(df_organizados, df_rejeitados, df_original, tempo)

    gerar_relatorio_validados(df_organizados, job_dir / NOMES_RELATORIOS["validados"])
    gerar_relatorio_rejeitados(df_rejeitados, job_dir / NOMES_RELATORIOS["rejeitados"])
    gerar_resumo_execucao(resumo, job_dir / NOMES_RELATORIOS["resumo"])

    return {"job_id": job_id, "resumo": resumo}


@app.post("/validar")
async def validar(arquivo: UploadFile = File(...)) -> dict:
    """Valida uma planilha (multipart) — usado por n8n, Streamlit, navegador.

    Retorna o resumo em JSON com um job_id; os relatórios ficam em
    GET /download/{job_id}.
    """
    if not arquivo.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Envie um arquivo Excel (.xlsx).")
    return _processar(await arquivo.read())


class EntradaBase64(BaseModel):
    """Corpo JSON do endpoint base64 (fácil de montar no Power Automate)."""
    nome_arquivo: str = "pedidos.xlsx"
    conteudo_base64: str


@app.post("/validar-base64")
def validar_base64(entrada: EntradaBase64) -> dict:
    """Valida uma planilha enviada como base64 num corpo JSON.

    Alternativa ao multipart para ferramentas onde montar multipart é
    trabalhoso (ex.: Power Automate): envie {nome_arquivo, conteudo_base64}.
    """
    try:
        conteudo = base64.b64decode(entrada.conteudo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="conteudo_base64 inválido.")
    return _processar(conteudo)


@app.get("/download/{job_id}")
def download(job_id: str) -> FileResponse:
    """Baixa os 3 relatórios de um job como um único .zip."""
    job_dir = JOBS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="job_id não encontrado.")

    zip_path = job_dir / "relatorios.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome in NOMES_RELATORIOS.values():
            arquivo = job_dir / nome
            if arquivo.exists():
                zf.write(arquivo, arcname=nome)

    return FileResponse(zip_path, filename="relatorios_gocase.zip",
                        media_type="application/zip")


@app.get("/download/{job_id}/{tipo}")
def download_um(job_id: str, tipo: str) -> FileResponse:
    """Baixa um relatório específico (validados | rejeitados | resumo)."""
    if tipo not in NOMES_RELATORIOS:
        raise HTTPException(status_code=400,
                            detail=f"tipo inválido. Use: {', '.join(NOMES_RELATORIOS)}")
    arquivo = JOBS_DIR / job_id / NOMES_RELATORIOS[tipo]
    if not arquivo.exists():
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    return FileResponse(
        arquivo, filename=NOMES_RELATORIOS[tipo],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
