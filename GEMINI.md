# Projeto PO: Otimização da Tomada de Decisão de Goleiros em Pênaltis (Grupo 11, UFABC)

Regras locais deste repositório (aplicadas a todo código, SQL, teste e documento).

## 1. Fluxo Obrigatório por Entrega (Feature Gate)
1. **Casos de Teste Primeiro:** Toda nova funcionalidade (ETL, modelo, visualização) exige casos de teste explícitos (`TC-*`) em `tests/run_test_suite.py`, divididos entre:
   - Contratos locais/matemáticos sem rede (`--mode fast`);
   - Invariantes reais na nuvem/BigQuery e schema (`--mode full`).
2. **Test Switch Modular:** Registrar o estágio no `STAGE_REGISTRY` e validar antes de consolidar:
   - `.\.venv\Scripts\python tests\run_test_suite.py --stage <STAGE> --mode fast`
   - `.\.venv\Scripts\python tests\run_test_suite.py --stage ALL --mode full`
3. **Git Commit e Push:** Ao concluir e validar cada entrega, commitar e executar `git push origin master`, confirmando `## master...origin/master` limpo.
4. **Formato de Retorno:** Sempre reportar (a) **pontos de observação** técnicos/analíticos (anomalias de dados, invariantes numéricas, tradeoffs) e (b) a **saída observada dos testes** executados após a última edição.

## 2. Regras de BigQuery e Atribuição (GCP)
- **Projeto e Região:** `dev-plataforma-geral` em `southamerica-east1`. Nunca alterar região sem aprovação.
- **Labels Obrigatórios em Jobs E Tabelas:** Incluir `{"datacloud": "antigravity", "domain": "po", "layer": "<bronze|silver|gold>"}`.
  - **Atenção:** `bigquery.LoadJobConfig(labels=...)` etiqueta apenas o *job*, NÃO a tabela. Após `load_job.result()`, executar obrigatoriamente `table = client.get_table(ref); table.labels = LABELS; client.update_table(table, ["labels"])` (ou usar `OPTIONS(labels=[...])` em SQL DDL).
- **Idempotência e Clustering:** Em `CREATE OR REPLACE TABLE ... CLUSTER BY (...)`, manter exatamente as mesmas colunas de clustering da tabela existente (ou recriar explicitamente se a especificação mudar). Preferir lista explícita de colunas em vez de `SELECT * EXCEPT(...)` ao transformar tabelas em cadeia.

## 3. Estilo e Escrita
- **Zero Travessão Longo:** Nunca usar o caractere de travessão longo em comentários de código, docstrings, documentação ou respostas; usar dois pontos, vírgula ou parênteses.
