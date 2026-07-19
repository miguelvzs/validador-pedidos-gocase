"""Frontend Streamlit do Validador de Pedidos GoCase.

Frente web que consome a API FastAPI. O operador abre no navegador, sobe a
planilha e baixa os relatórios — sem instalar nada na máquina.

Rodar (com a API já no ar):
    streamlit run app_streamlit.py

A URL da API vem da variável de ambiente API_URL (padrão localhost:8000).
"""

import os

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Validador de Pedidos GoCase", page_icon="✅",
                   layout="centered")

st.title("Validador de Pedidos — GoCase")
st.caption("Suba a planilha de pedidos. A validação roda no servidor; nenhuma "
           "instalação é necessária nesta máquina.")

arquivo = st.file_uploader("Planilha de pedidos (.xlsx)", type=["xlsx", "xls"])

if arquivo is not None and st.button("Validar pedidos", type="primary"):
    with st.spinner("Validando no servidor..."):
        try:
            resposta = requests.post(
                f"{API_URL}/validar",
                files={"arquivo": (arquivo.name, arquivo.getvalue())},
                timeout=120,
            )
        except requests.RequestException as exc:
            st.error(f"Não foi possível falar com a API ({API_URL}): {exc}")
            st.stop()

    if resposta.status_code != 200:
        # Erro de dados (ex.: coluna faltando) vem com detalhe legível.
        detalhe = resposta.json().get("detail", resposta.text)
        st.error(f"Falha na validação: {detalhe}")
        st.stop()

    dados = resposta.json()
    resumo = dados["resumo"]

    st.success("Validação concluída.")

    # Métricas principais.
    c1, c2, c3 = st.columns(3)
    c1.metric("Processados", resumo["total_processados"])
    c2.metric("Válidos", f"{resumo['total_validos']} ({resumo['percentual_validos']}%)")
    c3.metric("Rejeitados", resumo["total_rejeitados"])

    # Prioridades e canais.
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Por prioridade")
        st.bar_chart(resumo["por_prioridade"])
    with col_b:
        st.subheader("Por canal")
        if resumo["por_canal"]:
            st.bar_chart(resumo["por_canal"])
        else:
            st.write("—")

    st.write(
        f"**Valor válidos:** R$ {resumo['valor_total_validos']:,.2f}  |  "
        f"**Valor rejeitados:** R$ {resumo['valor_total_rejeitados']:,.2f}"
    )

    # Download dos relatórios (zip) buscado da API.
    try:
        zip_resp = requests.get(f"{API_URL}/download/{dados['job_id']}", timeout=60)
        if zip_resp.status_code == 200:
            st.download_button(
                "Baixar relatórios (.zip)", data=zip_resp.content,
                file_name="relatorios_gocase.zip", mime="application/zip",
            )
    except requests.RequestException as exc:
        st.warning(f"Relatórios gerados, mas o download falhou: {exc}")
