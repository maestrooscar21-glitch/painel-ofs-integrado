"""Eficiência financeira (interno): planilha de pagamento das oficinas (relatório da auditoria de pagamento)."""
import pandas as pd

import regras

COLUNAS = {
    "Protocolo": "os", "Status OFS": "status_ofs", "Tipo": "tipo", "Oficina": "oficina", "Instalador": "tecnico",
    "Data Execução": "data", "Data Validação": "data_validacao", "Placa": "placa",
    "Placa Repetida (mesmo servico/dia)": "placa_repetida", "Visita Recorrente (30 dias)": "visita_recorrente",
    "Cidade/UF": "cidade_uf", "KM Calculado": "km", "Valor KM": "valor_km", "Serviço Oficina": "valor_servico",
    "Pedágio": "pedagio", "Hotel": "hotel", "Materiais": "materiais", "Outras": "outras",
    "Despesas Viagem (sem comprovante)": "sem_comprovante", "Total a Pagar": "total_pagar",
    "Total a Receber": "total_receber", "Status": "status_pagamento",
}
NUM = ["km", "valor_km", "valor_servico", "pedagio", "hotel", "materiais", "outras", "sem_comprovante",
       "total_pagar", "total_receber"]
OBRIGATORIAS = ["Protocolo", "Oficina", "Data Execução", "Total a Pagar"]

# Planilha "Consolidado" (mês fechado): mesmas informações com outros nomes de coluna
COLUNAS_CONSOLIDADO = {
    "Protocolo": "os", "Tipo_Servico": "tipo", "Oficina": "oficina", "Instalador": "tecnico",
    "Data_Execucao": "data", "Data_Fechamento": "data_validacao", "Placa": "placa",
    "KM_Percorrido": "km", "Valor_KM": "valor_km", "Valor_Servico": "valor_servico",
    "Valor_Despesas": "outras", "Valor_Total": "total_pagar", "Total a Receber": "total_receber",
    "Motivo": "motivo_despesa", "Arquivo_Origem": "arquivo_origem",
}


# Consolidado antigo (2025): oficina vem em "Planilha Origem" e não há instalador
COLUNAS_CONSOLIDADO_ANTIGO = {
    "Planilha Origem": "oficina", "Tipo Servico": "tipo", "Placa": "placa", "KM Percorrido": "km",
    "R$ KM": "valor_km", "R$ Despesas": "outras", "R$ Serviço": "valor_servico", "R$ Total": "total_pagar",
    "Despesas de Viagem": "motivo_despesa",
}


def _datas(serie: pd.Series) -> pd.Series:
    """Datas em formatos misturados: dd/mm/aaaa (dia primeiro) ou aaaa-mm-dd (com ou sem hora)."""
    s = serie.astype(str).str.strip()
    br = s.str.match(r"^\d{1,2}/\d{1,2}/\d{4}")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if br.any():
        out[br] = pd.to_datetime(s[br].str[:10], format="%d/%m/%Y", errors="coerce")
    if (~br).any():
        out[~br] = pd.to_datetime(s[~br].str[:10], format="%Y-%m-%d", errors="coerce")
    return out.dt.date


def tipo_planilha(bruto: pd.DataFrame) -> str:
    if "Planilha Origem" in bruto.columns and "R$ Total" in bruto.columns:
        return "consolidado_antigo"
    if "Valor_Total" in bruto.columns and "Data_Execucao" in bruto.columns:
        return "consolidado"
    if all(c in bruto.columns for c in OBRIGATORIAS):
        return "auditoria"
    raise ValueError("Não reconheci a planilha. Esperava a da auditoria de pagamento (colunas Protocolo, Oficina, "
                     "Data Execução, Total a Pagar), o Consolidado (Protocolo, Data_Execucao, Valor_Total) ou o "
                     "Consolidado antigo (Planilha Origem, Execução Serviço, R$ Total).")


def preparar(bruto: pd.DataFrame) -> pd.DataFrame:
    fonte = tipo_planilha(bruto)
    if fonte == "consolidado_antigo":
        df = pd.DataFrame({novo: bruto[orig] if orig in bruto.columns else None
                           for orig, novo in COLUNAS_CONSOLIDADO_ANTIGO.items()})
        exe = pd.to_datetime(_datas(bruto["Execução Serviço"]))
        fech = pd.to_datetime(_datas(bruto["Fechamento O.S"])) if "Fechamento O.S" in bruto else exe
        df["data"] = exe.where(exe.dt.year >= 2000, fech)  # datas 1900 (erro de planilha): usa o fechamento
        df["status_ofs"] = bruto["Improdutiva"].fillna("").astype(str).str.upper().map(
            lambda s: "não concluído" if s.startswith("SIM") else "concluído")
        cid = bruto["Cidade"].fillna("").astype(str)
        df["cidade_uf"] = cid.str.rsplit(" - ", n=1).str[0] + "/" + cid.str.rsplit(" - ", n=1).str[-1]
        # o protocolo vem truncado pelo Excel: cria uma chave estável a partir dos dados da linha
        chave = (bruto["Planilha Origem"].fillna("") + "|" + df["data"].astype(str) + "|" + bruto["Placa"].fillna("")
                 + "|" + bruto["Modulo"].fillna("").astype(str) + "|" + bruto["Tipo Servico"].fillna(""))
        df["os"] = "H25-" + pd.util.hash_pandas_object(chave, index=False).astype(str)
        df["os"] = df["os"] + "-" + df.groupby("os").cumcount().astype(str)
        df["status_pagamento"] = "fechado"
        for c in COLUNAS.values():
            if c not in df.columns:
                df[c] = None
        fonte = "consolidado"
    elif fonte == "consolidado":
        df = pd.DataFrame({novo: bruto[orig] if orig in bruto.columns else None
                           for orig, novo in COLUNAS_CONSOLIDADO.items()})
        imp = bruto.get("Visita_Improdutiva", pd.Series(index=bruto.index, dtype=str)).fillna("").astype(str).str.upper()
        df["status_ofs"] = imp.map(lambda s: "não concluído" if s.startswith("SIM") else "concluído")
        df["cidade_uf"] = bruto.get("Cidade", "").fillna("").astype(str) + "/" + bruto.get("UF", "").fillna("").astype(str)
        df["status_pagamento"] = "fechado"
        for c in COLUNAS.values():
            if c not in df.columns:
                df[c] = None
    else:
        df = pd.DataFrame({novo: bruto[orig] if orig in bruto.columns else None for orig, novo in COLUNAS.items()})
    df["fonte"] = fonte
    df["os"] = df["os"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df = df[df["os"].ne("") & df["os"].ne("nan")].drop_duplicates("os", keep="last")
    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["data"] = _datas(df["data"])
    df = df.dropna(subset=["data"])
    df["mes"] = pd.to_datetime(df["data"]).dt.strftime("%Y-%m")
    df["familia"] = df["tipo"].map(regras.familia_servico)
    df["extras"] = df[["pedagio", "hotel", "materiais", "outras", "sem_comprovante"]].sum(axis=1)
    df["com_km"] = df["km"] > 0
    df["alerta_placa"] = df["placa_repetida"].fillna("").astype(str).str.upper().str.startswith("SIM")
    df["alerta_visita"] = df["visita_recorrente"].fillna("").astype(str).str.upper().str.startswith("SIM")
    df["status_ofs"] = df["status_ofs"].fillna("sem status").astype(str).str.lower()
    return df.reset_index(drop=True)


def resumo(df: pd.DataFrame, por: str) -> pd.DataFrame:
    g = df.groupby(por)
    t = pd.DataFrame({
        "OS": g.size(),
        "Total pago": g["total_pagar"].sum(),
        "Serviço": g["valor_servico"].sum(),
        "Deslocamento (KM)": g["valor_km"].sum(),
        "Despesas extras": g["extras"].sum(),
        "Sem comprovante": g["sem_comprovante"].sum(),
        "KM rodado": g["km"].sum(),
        "OS com deslocamento": g["com_km"].sum(),
        "Cobrado de clientes": g["total_receber"].sum(),
        "Alertas": g.apply(lambda x: int((x["alerta_placa"] | x["alerta_visita"]).sum()), include_groups=False),
    })
    t["Custo médio por OS"] = t["Total pago"] / t["OS"]
    t["% com deslocamento"] = t["OS com deslocamento"] / t["OS"] * 100
    t["KM médio (OS com desloc.)"] = t["KM rodado"] / t["OS com deslocamento"].replace(0, float("nan"))
    t["% do custo em deslocamento"] = t["Deslocamento (KM)"] / t["Total pago"].replace(0, float("nan")) * 100
    return t.reset_index()


def cidade(cidade_uf) -> str:
    import unicodedata
    c = str(cidade_uf or "").split("/")[0]
    c = unicodedata.normalize("NFKD", c)
    return "".join(ch for ch in c if not unicodedata.combining(ch)).upper().strip()


def simular_tabela(of: pd.DataFrame, regiao: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Para as OS de preço fixo de uma oficina, estima quanto custariam no modelo de tabela.
    Referências tiradas do histórico da própria oficina quando era tabela (com fallback na região):
    - valor do serviço por tipo = mediana paga por tipo;
    - KM por cidade = média de KM pago por OS naquela cidade (inclui as OS sem KM, como visitas com mais de um serviço);
    - tarifa = R$ pago de KM ÷ KM pago."""
    hist = of[(of["modelo"] == "Tabela") & (of["status_ofs"] == "concluído")]
    reg = regiao[(regiao["modelo"] == "Tabela") & (regiao["status_ofs"] == "concluído")]
    preco = hist[hist["valor_servico"] > 0].groupby("familia")["valor_servico"].median()
    preco_reg = reg[reg["valor_servico"] > 0].groupby("familia")["valor_servico"].median()
    pagos = hist[(hist["km"] > 0) & (hist["valor_km"] > 0)]
    tarifa = pagos["valor_km"].sum() / pagos["km"].sum() if pagos["km"].sum() else None
    if not tarifa:
        p = reg[(reg["km"] > 0) & (reg["valor_km"] > 0)]
        tarifa = p["valor_km"].sum() / p["km"].sum() if p["km"].sum() else 0
    km_cid = hist.assign(cid=hist["cidade_uf"].map(cidade)).groupby("cid")["km"].mean()
    fx = of[(of["modelo"] == "Preço fixo") & (of["status_ofs"] == "concluído")].copy()
    fx["cid"] = fx["cidade_uf"].map(cidade)
    fx["preco_tabela"] = fx["familia"].map(lambda f: preco.get(f, preco_reg.get(f)))
    fx["km_estimado"] = fx["cid"].map(km_cid)
    fx["sem_historico_cidade"] = fx["km_estimado"].isna()
    fx["km_estimado"] = fx["km_estimado"].fillna(0)
    # KM que o contrato fixo já pagou à parte (fora da área) não entra na estimativa
    fx["custaria_tabela"] = fx["preco_tabela"].fillna(0) + fx["km_estimado"] * tarifa + fx["extras"]
    fx["diferenca"] = fx["total_pagar"] - fx["custaria_tabela"]
    ref = {"tarifa": tarifa, "precos": preco.combine_first(preco_reg).to_dict(),
           "cidades_sem_historico": sorted(fx.loc[fx["sem_historico_cidade"], "cid"].unique())}
    return fx, ref
