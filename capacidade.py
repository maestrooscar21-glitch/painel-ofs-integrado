"""Capacidade × agenda × realizado, por oficina e por dia."""
from datetime import timedelta

import pandas as pd

PADRAO = {"os_por_tecnico_dia": 3, "dias_trabalho": [0, 1, 2, 3, 4], "faixa_atencao": 80, "faixa_sobrecarga": 100}
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def tecnicos_por_oficina(ativ: pd.DataFrame, oficinas: pd.DataFrame, janela_dias: int = 60) -> pd.DataFrame:
    """Nº de técnicos: o do cadastro, se preenchido; senão, os técnicos distintos que executaram nos últimos 60 dias."""
    res = ativ[(ativ["tipo_base"] == "resultado") & ativ["tecnico"].notna()] if not ativ.empty else ativ
    if not res.empty:
        corte = max(res["data"]) - timedelta(days=janela_dias)
        vistos = res[res["data"] >= corte].groupby("id_oficina")["tecnico"].nunique()
    else:
        vistos = pd.Series(dtype=int)
    t = oficinas[["id", "oficina", "tecnicos"]].copy()
    t["vistos"] = t["id"].map(vistos).fillna(0).astype(int)
    t["n_tecnicos"] = t["tecnicos"].where(t["tecnicos"] > 0, t["vistos"]).fillna(0).astype(int)
    t["origem_tecnicos"] = t["tecnicos"].map(lambda v: "Cadastro" if pd.notna(v) and v > 0 else "Estimado pelos dados")
    return t.rename(columns={"id": "id_oficina"})


def diario(ativ: pd.DataFrame, base: pd.DataFrame, tec: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Uma linha por oficina × dia: agenda (planejado vigente), realizado (executados + encaixes + improdutivas)
    e capacidade (técnicos × OS por técnico, só nos dias de trabalho)."""
    cfg = {**PADRAO, **(cfg or {})}
    pla = ativ[(ativ["tipo_base"] == "planejado") & (ativ["status"] != "cancelado")] if not ativ.empty else ativ
    linhas = []
    if not pla.empty:
        for dia in sorted(pla["data"].unique()):
            cand = pla[(pla["data"] == dia) & (pla["data_ref"] <= dia)]
            if cand.empty:  # dia futuro: usa o planejado mais recente que o cobre
                cand = pla[pla["data"] == dia]
            vig = cand[cand["data_ref"] == cand["data_ref"].max()].drop_duplicates("os")
            for id_of, n in vig.groupby("id_oficina")["os"].count().items():
                linhas.append({"data": dia, "id_oficina": str(id_of), "agenda": int(n)})
    agenda = pd.DataFrame(linhas, columns=["data", "id_oficina", "agenda"])
    if not base.empty:
        feitos = base[base["classificacao"].isin(["Atendimento executado", "Encaixe", "Improdutiva"])]
        real = feitos.groupby(["data_operacional", "id_oficina"])["os"].count().rename("realizado").reset_index()
        real = real.rename(columns={"data_operacional": "data"})
        real["id_oficina"] = real["id_oficina"].astype(str)
    else:
        real = pd.DataFrame(columns=["data", "id_oficina", "realizado"])
    d = agenda.merge(real, on=["data", "id_oficina"], how="outer").fillna({"agenda": 0, "realizado": 0})
    if d.empty:
        return d
    # completa todos os dias de trabalho do intervalo para todas as oficinas (capacidade existe mesmo sem OS)
    dias = pd.date_range(min(d["data"]), max(d["data"])).date
    grade = pd.MultiIndex.from_product([dias, tec["id_oficina"].astype(str)], names=["data", "id_oficina"]).to_frame(index=False)
    d = grade.merge(d, on=["data", "id_oficina"], how="left").fillna({"agenda": 0, "realizado": 0})
    d = d.merge(tec[["id_oficina", "oficina", "n_tecnicos"]], on="id_oficina", how="left")
    d["dia_trabalho"] = d["data"].map(lambda x: x.weekday() in cfg["dias_trabalho"])
    d["capacidade"] = (d["n_tecnicos"] * cfg["os_por_tecnico_dia"]).where(d["dia_trabalho"], 0)
    return d


def status_ocupacao(pct, cfg) -> str:
    cfg = {**PADRAO, **(cfg or {})}
    if pct is None or pd.isna(pct):
        return "—"
    if pct > cfg["faixa_sobrecarga"]:
        return "🔴 Acima da capacidade"
    if pct >= cfg["faixa_atencao"]:
        return "🟡 Perto do limite"
    return "🟢 Com folga"
