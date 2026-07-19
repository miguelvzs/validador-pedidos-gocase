"""Gera planilha simulada de pedidos da GoCase para demonstração e testes.

Produz `data/pedidos_entrada.xlsx` com 50 pedidos que imitam uma exportação
real do e-commerce, incluindo ~20% de pedidos com erros propositais para
exercitar o validador.
"""

import logging
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger("gerar_dados")

# Seed fixa: garante que a planilha gerada seja reproduzível entre execuções,
# importante para que os testes automatizados tenham resultado determinístico.
random.seed(42)

NOMES = [
    "Ana Carolina", "Bruno Henrique", "Camila Rodrigues", "Daniel Oliveira",
    "Eduardo Santos", "Fernanda Lima", "Gabriel Almeida", "Helena Costa",
    "Igor Ferreira", "Juliana Martins", "Kaique Souza", "Larissa Pereira",
    "Marcos Vinícius", "Natália Ribeiro", "Otávio Nascimento", "Patrícia Gomes",
    "Rafael Barbosa", "Sabrina Araújo", "Thiago Mendes", "Vanessa Cardoso",
    "Wagner Teixeira", "Yasmin Monteiro", "Lucas Batista", "Mariana Correia",
    "Pedro Henrique", "Renata Duarte", "Samuel Moreira", "Tatiane Rocha",
    "Vinícius Carvalho", "Amanda Nogueira"
]

PRODUTOS = {
    "Case iPhone 15": {"sku_prefixo": "CSE-IPH15", "preco_min": 69.90, "preco_max": 129.90},
    "Case Samsung S24": {"sku_prefixo": "CSE-SS24", "preco_min": 69.90, "preco_max": 119.90},
    "Mochila Personalizada": {"sku_prefixo": "MCH-PERS", "preco_min": 189.90, "preco_max": 299.90},
    "Garrafa Térmica": {"sku_prefixo": "GRF-TERM", "preco_min": 99.90, "preco_max": 159.90},
    "Capa MacBook": {"sku_prefixo": "CPA-MCBK", "preco_min": 149.90, "preco_max": 249.90},
    "Case AirPods": {"sku_prefixo": "CSE-APOD", "preco_min": 49.90, "preco_max": 89.90},
}

CANAIS = ["site", "marketplace", "b2b", "loja_fisica"]

DOMINIOS_EMAIL = ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com.br"]

ENDERECOS = [
    "Rua das Flores, 123 - Centro, São Paulo/SP",
    "Av. Brasil, 456 - Aldeota, Fortaleza/CE",
    "Rua Sete de Setembro, 789 - Centro, Belo Horizonte/MG",
    "Av. Paulista, 1000 - Bela Vista, São Paulo/SP",
    "Rua XV de Novembro, 321 - Centro, Curitiba/PR",
    "Av. Atlântica, 654 - Copacabana, Rio de Janeiro/RJ",
    "Rua Augusta, 987 - Consolação, São Paulo/SP",
    "Av. Beira Mar, 111 - Meireles, Fortaleza/CE",
    "Rua Oscar Freire, 222 - Jardins, São Paulo/SP",
    "Av. Fernão Dias, 500 - Centro, Extrema/MG",
]

def _gerar_email(nome: str) -> str:
    """Deriva um email plausível a partir do nome do cliente.

    Formato: nome.sobrenome@dominio (sem acentos, minúsculo).
    """
    # Normaliza acentos comuns para caber num endereço de email válido.
    tabela = str.maketrans("áàâãéêíóôõúüç", "aaaaeeiooouuc")
    partes = nome.lower().translate(tabela).split()
    usuario = ".".join(partes[:2]) if len(partes) >= 2 else partes[0]
    return f"{usuario}@{random.choice(DOMINIOS_EMAIL)}"


def _gerar_pedido_valido(indice: int, hoje: date) -> dict:
    """Monta um único pedido totalmente válido e coerente."""
    nome = NOMES[indice % len(NOMES)]
    produto = random.choice(list(PRODUTOS.keys()))
    info = PRODUTOS[produto]

    quantidade = random.randint(1, 5)
    valor_unitario = round(random.uniform(info["preco_min"], info["preco_max"]), 2)
    # valor_total derivado do unitário: mantém a regra de negócio consistente.
    valor_total = round(quantidade * valor_unitario, 2)

    # Data do pedido nos últimos 7 dias. O prazo é contado a partir de HOJE
    # (1 a 15 dias à frente): assim os 40 pedidos "bons" ficam de fato válidos
    # e distribuídos pelas faixas de prioridade — se contássemos a partir da
    # data do pedido, pedidos antigos cairiam no passado por acidente.
    data_pedido = hoje - timedelta(days=random.randint(0, 7))
    prazo_entrega = hoje + timedelta(days=random.randint(1, 15))

    return {
        "id_pedido": f"PED-{indice + 1:05d}",
        "data_pedido": datetime.combine(data_pedido, datetime.min.time()),
        "cliente": nome,
        "email": _gerar_email(nome),
        "produto": produto,
        "sku": f"{info['sku_prefixo']}-{random.randint(1000, 9999)}",
        "quantidade": quantidade,
        "valor_unitario": valor_unitario,
        "valor_total": valor_total,
        "canal": random.choice(CANAIS),
        "endereco": random.choice(ENDERECOS),
        "prazo_entrega": datetime.combine(prazo_entrega, datetime.min.time()),
    }


def gerar_planilha_exemplo(caminho: Path = Path("data/pedidos_entrada.xlsx")) -> Path:
    """Gera a planilha de 50 pedidos com erros propositais e a salva em disco.

    Retorna o caminho do arquivo gerado.
    """
    # Cria o diretório de dados antes de escrever: evita FileNotFoundError.
    os.makedirs(caminho.parent, exist_ok=True)

    hoje = date.today()
    pedidos = [_gerar_pedido_valido(i, hoje) for i in range(50)]

    # --- Inserção de erros propositais em 10 pedidos (~20%) ---
    # Índices escolhidos de forma espalhada para não concentrar os defeitos.

    # 3 pedidos com cliente vazio.
    for i in (2, 15, 33):
        pedidos[i]["cliente"] = ""

    # 2 emails inválidos: um sem @, outro sem domínio após o @.
    pedidos[7]["email"] = "clientegocase.com"      # falta o @
    pedidos[21]["email"] = "cliente@"              # falta domínio após @

    # 2 quantidades inválidas: zero e negativa. valor_total ajustado para
    # refletir a quantidade quebrada, senão a regra de valor_total mascararia.
    pedidos[11]["quantidade"] = 0
    pedidos[11]["valor_total"] = 0.0
    pedidos[27]["quantidade"] = -5
    pedidos[27]["valor_total"] = round(-5 * pedidos[27]["valor_unitario"], 2)

    # 1 prazo de entrega no passado (ontem).
    pedidos[18]["prazo_entrega"] = datetime.combine(hoje - timedelta(days=1), datetime.min.time())

    # 2 pedidos duplicados: reaproveitam o id_pedido de outro pedido válido.
    # A segunda ocorrência é que será rejeitada pelo validador.
    pedidos[40]["id_pedido"] = pedidos[0]["id_pedido"]
    pedidos[45]["id_pedido"] = pedidos[5]["id_pedido"]

    # Colunas inferidas da ordem de construção dos dicts (sem lista duplicada).
    df = pd.DataFrame(pedidos)
    df.to_excel(caminho, index=False, engine="openpyxl")

    logger.info("Planilha de exemplo gerada: %s (%d pedidos)", caminho, len(df))
    return caminho


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )
    gerar_planilha_exemplo()
