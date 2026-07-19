"""Camada de assistência por IA, exposta via MCP.

Filosofia: o servidor MCP não embute um modelo próprio nem exige chave de API.
Ele prepara os pedidos rejeitados num formato que a IA conectada (Claude
Desktop, Cursor, etc.) consegue raciocinar, e aceita de volta as correções
propostas para revalidar — fechando o ciclo rejeição → correção → aprovação.

Divisão de trabalho:
- Erros MECÂNICOS (valor_total que não fecha, espaços sobrando) recebem uma
  sugestão determinística aqui, sem IA — são resolvíveis por regra.
- Erros SEMÂNTICOS (nome digitado errado, e-mail com domínio faltando) ficam
  para a IA, que infere a intenção. O servidor só entrega o contexto.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("assistente_ia")


def carregar_rejeitados(caminho: Path) -> pd.DataFrame:
    """Lê o relatório de rejeitados gerado pela última execução."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(
            f"Relatório de rejeitados não encontrado: {caminho}. "
            "Execute a validação primeiro."
        )
    return pd.read_excel(caminho, engine="openpyxl")


def sugerir_correcoes_mecanicas(pedido: pd.Series) -> list[dict]:
    """Gera sugestões determinísticas para os erros resolvíveis por regra.

    Retorna lista de {campo, valor_atual, valor_sugerido, justificativa}.
    Só entra aqui o que dá para corrigir com certeza — o resto é da IA.
    """
    sugestoes: list[dict] = []

    # valor_total que não fecha: se quantidade e valor_unitario são válidos,
    # o total correto é aritmético — sugestão segura.
    qtd = pedido.get("quantidade")
    vu = pedido.get("valor_unitario")
    vt = pedido.get("valor_total")
    if not (pd.isna(qtd) or pd.isna(vu)) and qtd > 0 and vu > 0:
        esperado = round(float(qtd) * float(vu), 2)
        if pd.isna(vt) or abs(float(vt) - esperado) > 0.02:
            sugestoes.append({
                "campo": "valor_total",
                "valor_atual": None if pd.isna(vt) else float(vt),
                "valor_sugerido": esperado,
                "justificativa": "quantidade × valor_unitario",
            })

    # Espaços sobrando em campos de texto: trim é correção segura.
    for campo in ("cliente", "email", "produto", "sku"):
        valor = pedido.get(campo)
        if isinstance(valor, str) and valor != valor.strip() and valor.strip() != "":
            sugestoes.append({
                "campo": campo,
                "valor_atual": valor,
                "valor_sugerido": valor.strip(),
                "justificativa": "remover espaços nas bordas",
            })

    # E-mail com espaços internos ou maiúsculas: normalização segura.
    email = pedido.get("email")
    if isinstance(email, str) and email.strip() != "":
        normalizado = email.strip().lower().replace(" ", "")
        if normalizado != email and "@" in normalizado:
            sugestoes.append({
                "campo": "email",
                "valor_atual": email,
                "valor_sugerido": normalizado,
                "justificativa": "normalizar (minúsculas, sem espaços)",
            })

    return sugestoes


def montar_contexto_correcao(caminho_rejeitados: Path) -> str:
    """Monta o texto que a IA conectada usa para propor correções.

    Entrega, por pedido rejeitado: os dados, os motivos e as sugestões
    mecânicas já resolvidas. A IA cuida do que sobrar (erros semânticos).
    """
    df = carregar_rejeitados(caminho_rejeitados)
    if df.empty:
        return "Nenhum pedido rejeitado na última execução. Nada a corrigir."

    campos_mostrar = [
        "id_pedido", "cliente", "email", "produto", "sku",
        "quantidade", "valor_unitario", "valor_total", "prazo_entrega",
    ]

    linhas: list[str] = [
        f"{len(df)} pedido(s) rejeitado(s) na última execução.",
        "",
        "Para cada um: proponha correções para os motivos que exigem "
        "interpretação (nomes, e-mails, quantidades plausíveis). As correções "
        "mecânicas já vêm sugeridas. Devolva as correções para a tool "
        "'revalidar_com_correcoes' no formato:",
        '  [{"id_pedido": "...", "campo": "...", "valor": "..."}]',
        "=" * 60,
    ]

    for _, pedido in df.iterrows():
        linhas.append(f"\nPedido {pedido.get('id_pedido')}")
        linhas.append(f"  Motivo(s): {pedido.get('motivo_rejeicao')}")
        dados = {c: pedido.get(c) for c in campos_mostrar if c in df.columns}
        linhas.append(f"  Dados: {dados}")

        mecanicas = sugerir_correcoes_mecanicas(pedido)
        if mecanicas:
            linhas.append("  Sugestões mecânicas (aplicáveis direto):")
            for s in mecanicas:
                linhas.append(
                    f"    - {s['campo']}: {s['valor_atual']!r} → "
                    f"{s['valor_sugerido']!r} ({s['justificativa']})"
                )
        else:
            linhas.append("  Sem sugestão mecânica — requer interpretação da IA.")

    return "\n".join(linhas)


def aplicar_correcoes(correcoes: list[dict], caminho_entrada: Path) -> pd.DataFrame:
    """Aplica as correções sobre a planilha original e devolve o DataFrame.

    Cada correção: {id_pedido, campo, valor}. Casa pela PRIMEIRA linha com o
    id_pedido informado (a original; a duplicata é tratada corrigindo o id).
    Não escreve em disco — quem chama decide revalidar/persistir.
    """
    df = pd.read_excel(caminho_entrada, engine="openpyxl")

    aplicadas = 0
    for correcao in correcoes:
        # A correção vem de uma IA: nunca confie no formato. Qualquer item fora
        # do padrão é ignorado com log, em vez de derrubar a requisição.
        if not isinstance(correcao, dict):
            logger.warning("Correção ignorada: item não é objeto (%r)", correcao)
            continue

        id_pedido = correcao.get("id_pedido")
        campo = correcao.get("campo")
        valor = correcao.get("valor")

        if campo not in df.columns:
            logger.warning("Correção ignorada: campo inexistente '%s'", campo)
            continue

        # Só escalares: uma lista/dict em df.at levanta ValueError e quebraria
        # o lote inteiro por causa de uma sugestão malformada da IA.
        if not isinstance(valor, (str, int, float, bool, type(None))):
            logger.warning(
                "Correção ignorada: valor não escalar em '%s' do pedido %s (%r)",
                campo, id_pedido, valor,
            )
            continue
        mascara = df["id_pedido"] == id_pedido
        if not mascara.any():
            logger.warning("Correção ignorada: id_pedido '%s' não encontrado", id_pedido)
            continue
        # Corrige só a primeira ocorrência daquele id.
        idx = df.index[mascara][0]

        # O dtype da coluna pode rejeitar o valor (ex.: a IA manda a quantidade
        # como "2" numa coluna int). Convertemos para object antes de escrever:
        # o tipo definitivo é reconstruído na releitura da planilha, que já faz
        # a coerção de datas e números.
        if df[campo].dtype != object:
            df[campo] = df[campo].astype(object)

        df.at[idx, campo] = valor
        aplicadas += 1

    logger.info("Correções aplicadas: %d de %d", aplicadas, len(correcoes))
    return df
