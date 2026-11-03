"""Scorecard de eficiência das oficinas por mês, nos pilares usados na gestão:
Volume, Disponibilidade/Capacidade, Qualidade e Controle/Execução."""
import pandas as pd

# chave: (rótulo, pilar, tipo, sentido da meta) — na mesma ordem da planilha de gestão
KPIS = {
    "servicos":        ("T. serviços", "Volume de serviços", "n", None),
    "s7":              ("S ≤ 7 dias", "Volume de serviços", "n", None),
    "inst":            ("T. inst./renov./upgrade", "Volume de serviços", "n", None),
    "manut":           ("T. manutenção", "Volume de serviços", "n", None),
    "ret":             ("T. ret./reinst.", "Volume de serviços", "n", None),
    "nivel_servico":   ("Nível de serviço", "Disponibilidade / Capacidade", "pct", "maior"),
    "tme":             ("TME (dias)", "Disponibilidade / Capacidade", "dec", "menor"),
    "improdutividade": ("Improdutividade", "Disponibilidade / Capacidade", "pct", "menor"),
    "capacidade":      ("Capacidade (atend. no período)", "Disponibilidade / Capacidade", "n", None),
    "ocupacao":        ("Ocupação", "Disponibilidade / Capacidade", "pct", "faixa"),
    "retrabalho":      ("Retrabalho", "Qualidade", "pct", "menor"),
    "nao_conf":        ("Não conformidade", "Qualidade", "n", "menor"),
    "sinistro":        ("Mau uso (sinistro)", "Qualidade", "pct", "maior"),
    "auditoria":       ("Auditoria", "Qualidade", "pct", "maior"),
    "sla":             ("Ticket – SLA", "Controle / Execução", "pct", "maior"),
    "tma":             ("Ticket – TMA (horas)", "Controle / Execução", "dec", "menor"),
    "no_show":         ("No show", "Controle / Execução", "n", "menor"),
}
PILARES = ["Volume de serviços", "Disponibilidade / Capacidade", "Qualidade", "Controle / Execução"]
METAS_PADRAO = {"nivel_servico": 70, "tme": 7, "improdutividade": 15, "ocupacao_min": 60, "ocupacao_max": 100,
                "retrabalho": 10, "nao_conf": 0, "sinistro": 15, "auditoria": 80, "no_show": 0, "sla": 80, "tma": 24}
PENDENTES = {"sla": "aguardando dados do Gira", "tma": "aguardando dados do Gira"}


def mes(serie) -> pd.Series:
    return pd.to_datetime(serie, errors="coerce").dt.strftime("%Y-%m")


def montar(base, casos_rt, auds, cap_diario, manuais, sinistro_fn) -> pd.DataFrame:
    """Uma linha por oficina × mês com o valor de cada KPI (None = sem dado)."""
    partes = []
    if not base.empty:
        b = base.assign(mes=mes(base["data_operacional"]), id_oficina=base["id_oficina"].astype(str))
        real = b[b["classificacao"].isin(["Atendimento executado", "Encaixe"])]
        g = real.groupby(["id_oficina", "mes"])
        v = pd.DataFrame({
            "servicos": g.size(),
            "inst": g["familia"].apply(lambda s: s.isin(["Instalação", "Renovação", "Upgrade"]).sum()),
            "manut": g["familia"].apply(lambda s: (s == "Manutenção").sum()),
            "ret": g["familia"].apply(lambda s: s.isin(["Retirada", "Reinstalação"]).sum()),
            "sinistros_n": real.assign(s=real.apply(lambda r: bool(sinistro_fn(r)), axis=1)).groupby(["id_oficina", "mes"])["s"].sum(),
        })
        if "data_portal" in real.columns:
            dias = (pd.to_datetime(real["data_operacional"]) - pd.to_datetime(real["data_portal"], errors="coerce")).dt.days
            real = real.assign(_dias=dias.where(dias >= 0))
            gd = real.groupby(["id_oficina", "mes"])["_dias"]
            v["s7"] = gd.apply(lambda s: (s <= 7).sum())
            v["tme"] = gd.mean()
            v["nivel_servico"] = gd.apply(lambda s: (s <= 7).sum() / s.notna().sum() * 100 if s.notna().sum() else None)
        imp = b[b["classificacao"] == "Improdutiva"].groupby(["id_oficina", "mes"]).size().rename("improd_n")
        v = v.join(imp, how="outer").fillna(0)
        v["improdutividade"] = v["improd_n"] / (v["servicos"] + v["improd_n"]).replace(0, float("nan")) * 100
        v["sinistro"] = v["sinistros_n"] / v["servicos"].replace(0, float("nan")) * 100
        partes.append(v)
    if cap_diario is not None and not cap_diario.empty:
        c = cap_diario.assign(mes=mes(cap_diario["data"]))
        c = c[c["data"].isin(set(base["data_operacional"]))] if not base.empty else c.iloc[0:0]
        cc = c.groupby(["id_oficina", "mes"])[["realizado", "capacidade"]].sum()
        partes.append(pd.DataFrame({"capacidade": cc["capacidade"],
                                    "ocupacao": cc["realizado"] / cc["capacidade"].replace(0, float("nan")) * 100}))
    if casos_rt is not None and not casos_rt.empty:
        r = casos_rt[casos_rt["status"].isin(["Retrabalho", "Pendente"])]
        # só retornos em dias que têm resultado importado, para a taxa usar o mesmo período dos serviços
        dias_base = set(base["data_operacional"]) if not base.empty else set()
        r = r[pd.to_datetime(r["data_2"]).dt.date.isin(dias_base)]
        r = r.assign(mes=mes(r["data_2"]), id_oficina=r["id_oficina"].astype(str))
        partes.append(r.groupby(["id_oficina", "mes"]).size().rename("retrab_n").to_frame())
    if auds is not None and not auds.empty:
        a = auds.assign(mes=mes(auds["data_execucao"]), id_oficina=auds["id_oficina"].astype(str))
        ga = a.groupby(["id_oficina", "mes"])
        partes.append(pd.DataFrame({"auditoria": ga["resultado"].apply(lambda s: (s == "Aprovada").mean() * 100),
                                    "auditadas": ga.size()}))
    if manuais is not None and not manuais.empty:
        m = manuais.assign(id_oficina=manuais["id_oficina"].astype(str)).set_index(["id_oficina", "mes"])
        partes.append(m[["nao_conf", "no_show"]].apply(pd.to_numeric, errors="coerce"))
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, axis=1).reset_index()
    if "servicos" in df:
        n = df["retrab_n"] if "retrab_n" in df else pd.Series(float("nan"), index=df.index)
        df["retrab_n"] = n.where(n.notna() | df["servicos"].isna(), 0)
        df["retrabalho"] = df["retrab_n"] / df["servicos"].replace(0, float("nan")) * 100
    for k in KPIS:
        if k not in df.columns:
            df[k] = None
    return df


def semaforo(chave, valor, metas) -> str:
    sentido = KPIS[chave][3]
    if sentido is None:
        return ""
    if chave in PENDENTES or valor is None or pd.isna(valor):
        return "⚪"
    if sentido == "faixa":
        lo, hi = metas["ocupacao_min"], metas["ocupacao_max"]
        if lo <= valor <= hi:
            return "🟢"
        return "🟡" if (lo - 15) <= valor <= (hi + 15) else "🔴"
    meta = metas[chave]
    if sentido == "maior":
        return "🟢" if valor >= meta else ("🟡" if valor >= meta * 0.85 else "🔴")
    folga = max(meta * 0.3, 1 if KPIS[chave][2] == "n" else 3)
    return "🟢" if valor <= meta else ("🟡" if valor <= meta + folga else "🔴")


def nota(linha, metas) -> float | None:
    """0 a 100: verde vale 1, amarelo 0,5, vermelho 0, entre os KPIs que têm meta e dado."""
    pts = []
    for k, (_, _, _, sentido) in KPIS.items():
        if sentido is None or k in PENDENTES:
            continue
        s = semaforo(k, linha.get(k), metas)
        if s in ("🟢", "🟡", "🔴"):
            pts.append({"🟢": 1, "🟡": 0.5, "🔴": 0}[s])
    return round(sum(pts) / len(pts) * 100) if pts else None


def formatar(chave, valor) -> str:
    if chave in PENDENTES:
        return "—"
    if valor is None or pd.isna(valor):
        return "—"
    tipo = KPIS[chave][2]
    if tipo == "pct":
        return f"{valor:.0f}%"
    if tipo == "dec":
        return f"{valor:.1f}".replace(".", ",")
    return f"{int(valor)}"


def texto_meta(chave, metas) -> str:
    sentido = KPIS[chave][3]
    if sentido is None:
        return ""
    if chave in PENDENTES:
        return PENDENTES[chave]
    if sentido == "faixa":
        return f"entre {metas['ocupacao_min']}% e {metas['ocupacao_max']}%"
    unid = {"pct": "%", "dec": (" h" if chave == "tma" else " dias")}.get(KPIS[chave][2], "")
    return ("mín. " if sentido == "maior" else "máx. ") + f"{metas[chave]}{unid}"
