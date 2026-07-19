# Power Automate — Validador de Pedidos GoCase

Fluxo que valida uma planilha chamando a API. Sem instalar Python: o Power
Automate só faz HTTP.

## Fluxo sugerido

1. **Gatilho** — *Quando um arquivo é criado* (SharePoint/OneDrive), na pasta
   onde a equipe larga as planilhas de pedidos.

2. **Obter conteúdo do arquivo** — *Get file content* (SharePoint), usando o
   identificador do gatilho. Guarda os bytes do `.xlsx`.

3. **HTTP** (ação *HTTP*, conector premium) — use o endpoint **base64**, que
   evita a montagem manual de multipart:
   - **Method:** `POST`
   - **URI:** `http://SEU_SERVIDOR:8000/validar-base64`
   - **Headers:** `Content-Type: application/json`
   - **Body:**

     ```json
     {
       "nome_arquivo": "pedidos.xlsx",
       "conteudo_base64": "@{base64(body('Get_file_content'))}"
     }
     ```

   A função `base64()` do Power Automate converte o conteúdo do arquivo; a API
   decodifica e valida. (n8n usa o endpoint multipart `/validar`; Power Automate
   usa `/validar-base64` — mesma lógica por trás.)

4. **Parse JSON** — sobre o corpo da resposta, para ler o `resumo`. Schema
   principal: `job_id`, `resumo.total_validos`, `resumo.total_rejeitados`,
   `resumo.percentual_validos`.

5. **Condition** — `resumo.total_rejeitados` maior que `0`:
   - **Se sim:** *Post message* no Teams / *Send an email* avisando a gestão,
     com os números do resumo.
   - **Se não:** segue o fluxo de produção.

6. **(Opcional) Baixar relatórios** — *HTTP* `GET`
   `http://SEU_SERVIDOR:8000/download/@{body('Parse_JSON')?['job_id']}` e salve
   o `.zip` de volta no SharePoint.

## Observação

A API é a mesma para n8n, Power Automate e Make — muda só a ferramenta que faz o
HTTP. O contrato está em `integracoes/README.md`.
