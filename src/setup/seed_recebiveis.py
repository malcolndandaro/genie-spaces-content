# Databricks notebook source
# MAGIC %md
# MAGIC # Acme — seed sintético de recebíveis (S01)
# MAGIC Idempotente. Gera dados fictícios em PT na camada **diamond** do catálogo do
# MAGIC target, com **comentários de tabela/coluna e PKs** (o Genie usa isso para
# MAGIC entender o schema e sugerir joins). O nome do catálogo chega por parâmetro —
# MAGIC nada hardcoded (ADR-0004).

# COMMAND ----------
dbutils.widgets.text("catalog", "dev_recebiveis")
dbutils.widgets.text("env", "dev")
dbutils.widgets.text("consumer_group", "account users")
catalog = dbutils.widgets.get("catalog")
env = dbutils.widgets.get("env")
consumer_group = dbutils.widgets.get("consumer_group")
print(f"Seeding catalog={catalog} (env={env}) consumer_group={consumer_group}")

# COMMAND ----------
import datetime
import random

from pyspark.sql.types import (
    DateType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

random.seed(42)  # determinístico → re-runs estáveis

for sch in ["raw", "trusted", "refined", "diamond"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{sch}")

# tabelas recriadas do zero a cada run → idempotente e sem conflito de constraints
for t in ["fato_recebiveis", "dim_cedente", "dim_arranjo"]:
    spark.sql(f"DROP TABLE IF EXISTS {catalog}.diamond.{t}")

# COMMAND ----------
# Grants centralizados no setup job (D10/ADR-0004). Idempotente. SELECT em schema
# cascateia para as tabelas atuais e futuras da diamond.
spark.sql(f"GRANT USE CATALOG ON CATALOG {catalog} TO `{consumer_group}`")
spark.sql(f"GRANT USE SCHEMA ON SCHEMA {catalog}.diamond TO `{consumer_group}`")
spark.sql(f"GRANT SELECT ON SCHEMA {catalog}.diamond TO `{consumer_group}`")
print(f"Grants aplicados a `{consumer_group}` em {catalog}.diamond")

# COMMAND ----------
# Best-effort: isolar o catálogo a este workspace (ISOLATED + binding RW). Não-fatal:
# se a API divergir nesta versão, segue o seed (ADR-0004 mantém tudo reprodutível).
try:
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    try:
        ws_id = w.get_workspace_id()
    except Exception:
        ws_id = int(spark.conf.get("spark.databricks.clusterUsageTags.clusterOwnerOrgId"))
    w.api_client.do("PATCH", f"/api/2.1/unity-catalog/catalogs/{catalog}",
                    body={"isolation_mode": "ISOLATED"})
    w.api_client.do("PATCH", f"/api/2.1/unity-catalog/bindings/catalog/{catalog}",
                    body={"add": [{"workspace_id": ws_id, "binding_type": "BINDING_TYPE_READ_WRITE"}]})
    print(f"Catálogo {catalog} ISOLATED e vinculado ao workspace {ws_id}.")
except Exception as e:  # noqa: BLE001 — binding é best-effort
    print(f"[aviso] isolamento/binding ignorado nesta versão: {e}")

# COMMAND ----------
# dim_arranjo — arranjos de pagamento (bandeiras)
arranjos = [
    ("VCD", "Visa Crédito", "VISA"),
    ("VDB", "Visa Débito", "VISA"),
    ("MCD", "Mastercard Crédito", "MASTERCARD"),
    ("MDB", "Mastercard Débito", "MASTERCARD"),
    ("ELO", "Elo Crédito", "ELO"),
    ("HIP", "Hipercard", "HIPERCARD"),
    ("AMX", "Amex Crédito", "AMEX"),
]
spark.createDataFrame(arranjos, ["arranjo", "descricao", "bandeira"]).write.mode(
    "overwrite"
).option("overwriteSchema", "true").saveAsTable(f"{catalog}.diamond.dim_arranjo")

# COMMAND ----------
# dim_cedente — ~200 cedentes (empresas que registram recebíveis)
ufs = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "PE", "CE", "GO", "DF", "ES"]
ramos = ["Comercial", "Distribuidora", "Atacado", "Varejo", "Serviços", "Indústria",
         "Logística", "Mercado", "Farmácia", "Padaria"]
sufixos = ["Aurora", "Bandeirantes", "Central", "Delta", "Estrela", "Forte",
           "Guará", "Horizonte"]
cedentes = []
for i in range(1, 201):
    cnpj = f"{random.randint(10,99)}.{random.randint(100,999)}.{random.randint(100,999)}/0001-{random.randint(10,99)}"
    nome = f"{random.choice(ramos)} {random.choice(sufixos)} Ltda"
    cedentes.append((i, cnpj, nome, random.choice(ufs)))
spark.createDataFrame(cedentes, ["cedente_id", "cnpj", "nome", "uf"]).write.mode(
    "overwrite"
).option("overwriteSchema", "true").saveAsTable(f"{catalog}.diamond.dim_cedente")

# COMMAND ----------
# fato_recebiveis — ~8000 registros nos últimos 90 dias
arr_codes = [a[0] for a in arranjos]
status_opts = ["REGISTRADO", "LIQUIDADO", "ONERADO", "CANCELADO"]
today = datetime.date.today()
rows = []
for _ in range(8000):
    d = today - datetime.timedelta(days=random.randint(0, 89))
    rows.append(
        (
            d,
            random.randint(1, 200),
            random.choice(arr_codes),
            round(random.uniform(50.0, 50000.0), 2),
            random.choices(status_opts, weights=[60, 25, 10, 5])[0],
        )
    )
schema = StructType(
    [
        StructField("data", DateType()),
        StructField("cedente_id", IntegerType()),
        StructField("arranjo", StringType()),
        StructField("valor", DoubleType()),
        StructField("status", StringType()),
    ]
)
spark.createDataFrame(rows, schema).write.mode("overwrite").option(
    "overwriteSchema", "true"
).saveAsTable(f"{catalog}.diamond.fato_recebiveis")

# COMMAND ----------
# Comentários de tabela/coluna + PKs — o Genie usa isso para entender o schema e
# sugerir joins corretos. Comentários são idempotentes; PKs são best-effort.
def _quiet(sql):
    try:
        spark.sql(sql)
    except Exception as e:  # noqa: BLE001
        print(f"[aviso] ignorado ({sql[:48]}...): {e}")


table_comments = {
    "fato_recebiveis": "Fato de recebíveis registrados (valor, status) por cedente e arranjo",
    "dim_cedente": "Dimensão de cedentes (empresas que registram recebíveis)",
    "dim_arranjo": "Dimensão de arranjos de pagamento / bandeiras de cartão",
}
column_comments = {
    "fato_recebiveis": {
        "data": "Data de registro do recebível",
        "cedente_id": "Identificador do cedente (FK para dim_cedente.cedente_id)",
        "arranjo": "Código do arranjo de pagamento (FK para dim_arranjo.arranjo)",
        "valor": "Valor do recebível em BRL",
        "status": "Situação: REGISTRADO, LIQUIDADO, ONERADO, CANCELADO",
    },
    "dim_cedente": {
        "cedente_id": "Identificador único do cedente (chave primária)",
        "cnpj": "CNPJ do cedente",
        "nome": "Razão social do cedente",
        "uf": "Unidade federativa (estado) do cedente",
    },
    "dim_arranjo": {
        "arranjo": "Código do arranjo de pagamento (chave primária)",
        "descricao": "Descrição do arranjo (ex.: Visa Crédito)",
        "bandeira": "Bandeira do cartão: VISA, MASTERCARD, ELO, HIPERCARD, AMEX",
    },
}
for tbl, tc in table_comments.items():
    spark.sql(f"COMMENT ON TABLE {catalog}.diamond.{tbl} IS '{tc}'")
for tbl, cols in column_comments.items():
    for col, c in cols.items():
        spark.sql(f"ALTER TABLE {catalog}.diamond.{tbl} ALTER COLUMN {col} COMMENT '{c}'")

# PKs informativos → ajudam o Genie a sugerir joins. Best-effort/idempotente.
_quiet(f"ALTER TABLE {catalog}.diamond.dim_cedente ALTER COLUMN cedente_id SET NOT NULL")
_quiet(f"ALTER TABLE {catalog}.diamond.dim_cedente ADD CONSTRAINT pk_cedente PRIMARY KEY(cedente_id)")
_quiet(f"ALTER TABLE {catalog}.diamond.dim_arranjo ALTER COLUMN arranjo SET NOT NULL")
_quiet(f"ALTER TABLE {catalog}.diamond.dim_arranjo ADD CONSTRAINT pk_arranjo PRIMARY KEY(arranjo)")
print("Comentários e PKs aplicados.")

# COMMAND ----------
for t in ["dim_arranjo", "dim_cedente", "fato_recebiveis"]:
    n = spark.table(f"{catalog}.diamond.{t}").count()
    print(f"{catalog}.diamond.{t}: {n} linhas")
print("Seed concluído.")
