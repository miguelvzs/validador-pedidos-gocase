"""Regras de validação de pedidos.

Cada pedido é avaliado contra todas as regras; um pedido pode acumular vários
motivos de rejeição, concatenados em `motivo_rejeicao`.
"""

import logging
import re
from datetime import date

import pandas as pd

from src.config import config

logger = logging.getLogger("validador")


def _validar_linha(pedido: pd.Series, ids_vistos: set[str], hoje: date,
                   padrao_email: re.Pattern, tolerancia: float) -> list[str]:
    """Aplica todas as regras a um pedido e devolve a lista de motivos de erro.

    `ids_vistos` acumula os ids já processados para detectar duplicatas; a
    primeira ocorrência é aceita e a segunda é a rejeitada. `padrao_email` e
    `tolerancia` vêm da config, lidos a cada execução (permite reconfigurar
    sem reiniciar o processo).
    """
    motivos: list[str] = []

    # 1. id_pedido: não vazio e não duplicado (rejeita a 2ª ocorrência).
    id_pedido = pedido.get("id_pedido")
    if pd.isna(id_pedido) or str(id_pedido).strip() == "":
        motivos.append("ID do pedido vazio")
    elif id_pedido in ids_vistos:
        motivos.append(f"ID duplicado: {id_pedido}")

    # 2. cliente: não vazio nem só espaços.
    cliente = pedido.get("cliente")
    if pd.isna(cliente) or str(cliente).strip() == "":
        motivos.append("Cliente vazio")

    # 3. email: formato mínimo válido.
    email = pedido.get("email")
    if pd.isna(email) or not padrao_email.match(str(email).strip()):
        motivos.append("Email inválido: formato incorreto")

    # 4. quantidade: inteiro positivo.
    quantidade = pedido.get("quantidade")
    if pd.isna(quantidade) or quantidade <= 0 or float(quantidade) != int(quantidade):
        motivos.append("Quantidade inválida: deve ser inteiro positivo")

    # 5. valor_unitario: positivo.
    valor_unitario = pedido.get("valor_unitario")
    if pd.isna(valor_unitario) or valor_unitario <= 0:
        motivos.append("Valor unitário inválido: deve ser positivo")

    # 6. valor_total: coerente com quantidade * valor_unitario (com tolerância).
    # Só checa se os operandos são válidos — senão a mensagem seria redundante.
    valor_total = pedido.get("valor_total")
    if pd.isna(valor_total):
        motivos.append("Valor total ausente")
    elif not (pd.isna(quantidade) or pd.isna(valor_unitario)):
        esperado = quantidade * valor_unitario
        if abs(valor_total - esperado) > tolerancia:
            motivos.append(
                f"Valor total incoerente: esperado {esperado:.2f}, "
                f"encontrado {valor_total:.2f}"
            )

    # 7. prazo_entrega: não pode estar no passado.
    prazo = pedido.get("prazo_entrega")
    if pd.isna(prazo):
        motivos.append("Prazo de entrega ausente")
    elif prazo.date() < hoje:
        motivos.append("Prazo de entrega no passado")

    # 8. produto: não vazio.
    produto = pedido.get("produto")
    if pd.isna(produto) or str(produto).strip() == "":
        motivos.append("Produto vazio")

    # 9. sku: não vazio.
    sku = pedido.get("sku")
    if pd.isna(sku) or str(sku).strip() == "":
        motivos.append("SKU vazio")

    return motivos


def validar_pedidos(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplica as regras de validação e separa válidos de rejeitados.

    Retorna (df_validos, df_rejeitados). O df_rejeitados inclui a coluna
    'motivo_rejeicao' com todos os erros encontrados por pedido.
    """
    hoje = date.today()
    # Lê a config a cada execução: reconfigurar o config.yaml surte efeito na
    # próxima chamada, sem reiniciar o processo. Regex compilada uma vez aqui.
    padrao_email = re.compile(config.regex_email)
    tolerancia = config.tolerancia_valor

    ids_vistos: set[str] = set()
    indices_validos: list[int] = []
    indices_rejeitados: list[int] = []
    motivos_por_indice: dict[int, str] = {}

    # Itera na ordem original: essencial para a regra de duplicata, que precisa
    # saber qual ocorrência veio primeiro.
    for indice, pedido in df.iterrows():
        motivos = _validar_linha(pedido, ids_vistos, hoje, padrao_email, tolerancia)

        # Registra o id só depois de checar duplicata, e apenas se preenchido.
        id_pedido = pedido.get("id_pedido")
        if not (pd.isna(id_pedido) or str(id_pedido).strip() == ""):
            ids_vistos.add(id_pedido)

        if motivos:
            indices_rejeitados.append(indice)
            motivos_por_indice[indice] = "; ".join(motivos)
        else:
            indices_validos.append(indice)

    df_validos = df.loc[indices_validos].copy()
    df_rejeitados = df.loc[indices_rejeitados].copy()
    df_rejeitados["motivo_rejeicao"] = [
        motivos_por_indice[i] for i in indices_rejeitados
    ]

    # Resumo dos tipos de erro para dar visibilidade operacional no log.
    contagem_erros: dict[str, int] = {}
    for motivo_texto in motivos_por_indice.values():
        for motivo in motivo_texto.split("; "):
            chave = motivo.split(":")[0]
            contagem_erros[chave] = contagem_erros.get(chave, 0) + 1

    logger.info(
        "Validação concluída: %d válidos, %d rejeitados",
        len(df_validos), len(df_rejeitados),
    )
    for tipo, qtd in sorted(contagem_erros.items(), key=lambda x: -x[1]):
        logger.info("  Erro '%s': %d ocorrência(s)", tipo, qtd)

    return df_validos, df_rejeitados
