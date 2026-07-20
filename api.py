"""API HTTP do Validador de Pedidos GoCase (FastAPI).

Núcleo de serviço: recebe uma planilha, roda o MESMO pipeline do modo
standalone (leitura → validação → organização → relatórios) e devolve o resumo
em JSON + os relatórios para download.

Elimina a dependência no cliente: quem consome (n8n, navegador ou qualquer
outro cliente HTTP) não instala nada.

Rodar: uvicorn api:app --host 0.0.0.0 --port 8000
Docs interativas: http://localhost:8000/docs
"""

import io
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import httpx

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.agente import NOMES_RELATORIOS, executar_pipeline
from src.assistente_ia import (
    aplicar_correcoes,
    marcar_correcoes,
    montar_contexto_correcao,
)

app = FastAPI(
    title="Validador de Pedidos GoCase",
    description="Valida e organiza pedidos de fábrica. Núcleo reutilizável por "
                "n8n, navegador ou qualquer cliente HTTP.",
    version="1.0.0",
)

# Diretório de trabalho dos jobs: cada requisição gera uma subpasta isolada,
# identificada por um job_id, para que uploads simultâneos não colidam.
JOBS_DIR = Path(tempfile.gettempdir()) / "validador_gocase_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Tempo de vida de um job em segundos. Passado esse prazo, a pasta é apagada
# na próxima requisição (limpeza preguiçosa). Configurável por ambiente.
TTL_JOBS_SEG = int(os.environ.get("JOBS_TTL_SEGUNDOS", "3600"))  # 1 hora

# --- Correção automática por IA (opcional) ---
# A chave fica só no ambiente do servidor, nunca no repositório. Sem ela, o
# endpoint /corrigir-automatico responde 503 e o resto da API segue normal.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODELO_IA = os.environ.get("MODELO_IA", "claude-haiku-4-5-20251001")
# Teto de rejeitados por chamada: limita o tamanho (e o custo) de cada pedido
# à IA, já que a API é pública.
MAX_REJEITADOS_IA = int(os.environ.get("MAX_REJEITADOS_IA", "60"))

INSTRUCAO_IA = (
    "Você corrige pedidos rejeitados de uma fábrica. Responda SOMENTE um objeto "
    "JSON com a chave correcoes: uma lista de objetos, cada um com os campos "
    "id_pedido, campo e valor. Aplique as sugestões mecânicas e infira erros "
    "claros como nome e e-mail. Não invente dado que não dá para deduzir; se um "
    "campo está totalmente vazio e não há como saber, não crie correção para ele."
)


def _pedir_correcoes_ia(contexto: str) -> list[dict]:
    """Pede as correções ao Claude e devolve a lista já parseada.

    Erros de rede/API viram mensagem legível. A resposta do modelo é texto:
    extraímos o primeiro bloco JSON e ignoramos o que não casar com o formato.
    """
    try:
        resposta = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODELO_IA,
                "max_tokens": 1024,
                "system": INSTRUCAO_IA,
                "messages": [{"role": "user", "content": contexto}],
            },
            timeout=90,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar a IA: {exc}")

    if resposta.status_code != 200:
        # Repassa o motivo (ex.: crédito insuficiente) em vez de um 500 opaco.
        raise HTTPException(
            status_code=502,
            detail=f"IA retornou {resposta.status_code}: {resposta.text[:200]}",
        )

    texto = resposta.json()["content"][0]["text"].strip()
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim == -1:
        return []
    try:
        return json.loads(texto[inicio:fim + 1]).get("correcoes", []) or []
    except json.JSONDecodeError:
        return []


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

    O fluxo em si vem de `executar_pipeline` (compartilhado com o modo
    arquivo); aqui cuidamos do que é próprio da API: pasta isolada por
    requisição, cache do resumo e tradução de erro de dados em HTTP 422.
    """
    _limpar_jobs_antigos()  # varre jobs vencidos antes de criar um novo

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    entrada = job_dir / "entrada.xlsx"
    entrada.write_bytes(conteudo)

    try:
        resumo = executar_pipeline(entrada, job_dir)
    except ValueError as exc:
        # Erro de dados (coluna faltando etc.): resposta clara, não 500.
        raise HTTPException(status_code=422, detail=str(exc))

    # Guarda o resumo em JSON no job: permite /analisar-rejeitados e /revalidar
    # recuperarem o estado anterior sem recalcular.
    (job_dir / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False), encoding="utf-8")

    return {"job_id": job_id, "resumo": resumo}


def _resumo_do_job(job_dir: Path) -> dict:
    """Lê o resumo.json salvo no job; dict vazio se não existir."""
    caminho = job_dir / "resumo.json"
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {}


@app.post("/validar")
async def validar(arquivo: UploadFile = File(...)) -> dict:
    """Valida uma planilha (multipart) — usado pelo n8n e por qualquer cliente HTTP.

    Retorna o resumo em JSON com um job_id; os relatórios ficam em
    GET /download/{job_id}.
    """
    if not arquivo.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Envie um arquivo Excel (.xlsx).")
    return _processar(await arquivo.read())


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


class JobRef(BaseModel):
    """Referência a um job já validado."""
    job_id: str


def _aplicar_e_reprocessar(job_dir: Path, correcoes: list[dict]) -> dict:
    """Aplica correções à planilha do job, marca a autoria da IA e revalida."""
    entrada = job_dir / "entrada.xlsx"
    antes = _resumo_do_job(job_dir).get("total_rejeitados")

    # Correções vêm de uma IA: falha na aplicação vira erro legível, não 500.
    try:
        df, log = aplicar_correcoes(correcoes, entrada)
        df = marcar_correcoes(df, log)
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Não foi possível aplicar as correções: {exc}",
        )

    resultado = _processar(buffer.getvalue())
    depois = resultado["resumo"]["total_rejeitados"]
    resultado["rejeitados_antes"] = antes
    resultado["rejeitados_depois"] = depois
    if antes is not None:
        resultado["recuperados"] = antes - depois
    return resultado


class JobRef(BaseModel):
    """Referência a um job já validado."""
    job_id: str


@app.post("/corrigir-automatico")
def corrigir_automatico(ref: JobRef) -> dict:
    """Ciclo completo de correção por IA, sem o cliente precisar de chave.

    O servidor lê os rejeitados, pede as correções ao Claude com a chave
    configurada em ANTHROPIC_API_KEY e revalida o lote. Quem chama (n8n,
    navegador) não precisa de credencial nenhuma.
    """
    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Correção automática indisponível: ANTHROPIC_API_KEY não "
                   "configurada no servidor. Use /revalidar enviando as correções.",
        )

    job_dir = JOBS_DIR / ref.job_id
    rejeitados = job_dir / NOMES_RELATORIOS["rejeitados"]
    if not rejeitados.exists():
        raise HTTPException(status_code=404, detail="job_id não encontrado ou expirado.")

    # Guarda-chuva de custo: lote gigante não vira uma chamada gigante à IA.
    total_rejeitados = _resumo_do_job(job_dir).get("total_rejeitados") or 0
    if total_rejeitados > MAX_REJEITADOS_IA:
        raise HTTPException(
            status_code=413,
            detail=f"Lote com {total_rejeitados} rejeitados excede o limite de "
                   f"{MAX_REJEITADOS_IA} para correção automática.",
        )
    if total_rejeitados == 0:
        raise HTTPException(status_code=400, detail="Este lote não tem rejeitados.")

    correcoes = _pedir_correcoes_ia(montar_contexto_correcao(rejeitados))
    resultado = _aplicar_e_reprocessar(job_dir, correcoes)
    resultado["correcoes_sugeridas"] = len(correcoes)
    return resultado


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
