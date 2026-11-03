"""Auditoria de OS (substitui o Google Forms): checklist por OS, resultado e indicadores."""
import pandas as pd

ITENS_PADRAO = [
    "Calibração câmera ADAS",
    "Calibração câmeras DSM",
    "Módulos Vbox e VMOV com fixação por abraçadeiras ou parafusos",
    "Pontos de alimentação com as 3 conexões (positivo, negativo e pós-chave) na caixa de fusíveis, "
    "comutador de partida ou chicote principal",
    "Print Easy Check com todas as câmeras OK e posicionamento correto",
    "Instalação e auto teste CAN ou OBD",
    "Foto com ID dos módulos Vbox e VMOV",
    "Auto teste",
]
OPCOES = ["Aprovado", "Reprovado", "Não se aplica"]


def resumo_itens(itens: dict) -> dict:
    vals = list(itens.values())
    ap, rp, na = vals.count("Aprovado"), vals.count("Reprovado"), vals.count("Não se aplica")
    avaliados = ap + rp
    return {
        "aprovados": ap, "reprovados": rp, "nao_aplica": na,
        "conformidade": round(ap / avaliados * 100, 1) if avaliados else None,
        "resultado": "Reprovada" if rp else "Aprovada",
    }


def itens_longos(aud: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por item avaliado (para ranking de itens reprovados)."""
    linhas = []
    for _, a in aud.iterrows():
        for item, res in (a["itens"] or {}).items():
            linhas.append({"os": a["os"], "oficina": a["oficina"], "tecnico": a["tecnico"], "item": item, "res": res})
    return pd.DataFrame(linhas, columns=["os", "oficina", "tecnico", "item", "res"])


def taxa_por(aud: pd.DataFrame, campo: str) -> pd.DataFrame:
    t = aud.groupby(campo).agg(
        Auditadas=("os", "count"),
        Aprovadas=("resultado", lambda s: (s == "Aprovada").sum()),
        Conformidade=("conformidade", "mean"),
    ).reset_index()
    t["% aprovação"] = (t["Aprovadas"] / t["Auditadas"] * 100).round(1)
    t["Conformidade"] = t["Conformidade"].round(1)
    return t.sort_values(["% aprovação", "Auditadas"], ascending=[False, False])
