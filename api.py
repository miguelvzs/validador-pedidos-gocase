"""API HTTP do Validador de Pedidos GoCase (FastAPI).

Núcleo de serviço: recebe uma planilha, roda o MESMO pipeline do modo
standalone (leitura → validação → organização → relatórios) e devolve o resumo
em JSON + os relatórios para download.

Elimina a dependência no cliente: quem consome (frontend Streamlit, Power
Automate, n8n, ou um navegador) só precisa falar HTTP. Nada de Python instalado
na máquina do usuário.

Rodar: uvicorn api:app --host 0.0.0.0 --port 8000
Docs interativas: http://localhost:8000/docs
"""

import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

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

NOMES_RELATORIOS = {
    "validados": "pedidos_validados.xlsx",
    "rejeitados": "pedidos_rejeitados.xlsx",
    "resumo": "resumo_execucao.xlsx",
}


@app.get("/")
def raiz() -> dict:
    """Health check simples."""
    return {"servico": "Validador de Pedidos GoCase", "status": "ok"}


@app.post("/validar")
async def validar(arquivo: UploadFile = File(...)) -> dict:
    """Valida uma planilha de pedidos e gera os relatórios.

    Recebe o .xlsx via multipart, roda o pipeline completo e retorna o resumo
    em JSON com um job_id. Os relatórios ficam disponíveis em
    GET /download/{job_id}.
    """
    if not arquivo.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Envie um arquivo Excel (.xlsx).")

    # Pasta isolada por requisição.
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Salva o upload em disco: o leitor trabalha com caminho de arquivo.
    entrada = job_dir / "entrada.xlsx"
    with open(entrada, "wb") as destino:
        shutil.copyfileobj(arquivo.file, destino)

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

    # Gera os 3 relatórios na pasta do job.
    gerar_relatorio_validados(df_organizados, job_dir / NOMES_RELATORIOS["validados"])
    gerar_relatorio_rejeitados(df_rejeitados, job_dir / NOMES_RELATORIOS["rejeitados"])
    gerar_resumo_execucao(resumo, job_dir / NOMES_RELATORIOS["resumo"])

    return {"job_id": job_id, "resumo": resumo}


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
