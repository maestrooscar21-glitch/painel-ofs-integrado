"""Pré-triagem automática de retrabalho.
Lê a base do administrativo (uma linha por visita: '1ª visita' e 'Retorno' de cada caso),
monta um caso por par de OS e aplica as regras de exclusão e confirmação."""
import re
import unicodedata

import pandas as pd

OBRIGATORIAS = ["Caso", "Protocolo", "Visita", "Placa", "Execução", "Oficina", "Tipo"]

PADRAO = {
    "janela_dias": 90,
    # procurados na observação do técnico (OFS) e na observação de vistoria do retorno → expurga
    "termos_terceiro": ["sinistro", "colisao", "batida", "lacre violado", "violad", "vandalismo", "mau uso",
                        "terceiro", "outra empresa", "cliente desligou", "cliente desconectou",
                        "bateria desligada pelo cliente", "cliente removeu"],
    "termos_equipamento": ["troca de equipamento", "trocado o equipamento", "equipamento trocado", "substituido",
                           "substituicao", "defeito de fabrica", "equipamento com defeito", "equipamento defeituoso",
                           "queimad", "garantia", "bancada", "rma"],
    "termos_peca": ["item pendente", "item faltante", "suporte pendente", "peca complementar",
                    "kit incompleto", "falta de peca", "faltante"],
    "dias_peca": 10,
    # sinais que mandam o caso para análise com destaque (procurados em diagnósticos e observações)
    "termos_revisar": ["camera desconectada", "vistoria solicitada", "nada encontrado", "nao encontrado",
                       "sem defeito", "fusivel", "bateria baixa", "sem ignicao", "camera obstruida", "item pendente"],
}
SERVICO_INICIAL = ("instala", "reinstala", "renova")

def sem_acento(txt) -> str:
    if txt is None or (isinstance(txt, float) and pd.isna(txt)):
        return ""
    txt = unicodedata.normalize("NFKD", str(txt))
    txt = "".join(c for c in txt if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", txt).strip()


def criticidade(dias):
    if pd.isna(dias):
        return "—"
    if dias <= 15:
        return "🔴 0–15 dias"
    if dias >= 60:
        return "🔵 60–90 dias"
    return "🟡 16–59 dias"


def montar_casos(bruto: pd.DataFrame) -> pd.DataFrame:
    faltando = [c for c in OBRIGATORIAS if c not in bruto.columns]
    if faltando:
        raise ValueError("A planilha não tem as colunas: " + ", ".join(faltando))
    df = bruto.copy()
    df["Protocolo"] = df["Protocolo"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df["Visita"] = df["Visita"].map(lambda v: "retorno" if "retorno" in sem_acento(v) else "primeira")
    df["Execução"] = pd.to_datetime(df["Execução"], dayfirst=True, errors="coerce")
    col = lambda c: df[c] if c in df.columns else None
    df["diag_jira"] = col("Diag. previsto (Jira)")
    df["diag_ofs"] = col("Diag. OFS")
    df["obs"] = col("Observação do técnico")  # opcional: se a base passar a trazer
    p = df[df["Visita"] == "primeira"].drop_duplicates("Caso").set_index("Caso")
    r = df[df["Visita"] == "retorno"].drop_duplicates("Caso").set_index("Caso")
    casos = pd.DataFrame({
        "caso": r.index.astype(str),
        "competencia": r.get("Competência"),
        "placa": r["Placa"],
        "cliente": r.get("Cliente"),
        "oficina": r["Oficina"],
        "uf": r.get("UF"),
        "os_1": p["Protocolo"].reindex(r.index),
        "data_1": p["Execução"].reindex(r.index),
        "tipo_1": p["Tipo"].reindex(r.index),
        "tecnico_1": p.get("Técnico", pd.Series(dtype=str)).reindex(r.index),
        "diag_jira_1": p["diag_jira"].reindex(r.index),
        "diag_ofs_1": p["diag_ofs"].reindex(r.index),
        "os_2": r["Protocolo"],
        "data_2": r["Execução"],
        "tipo_2": r["Tipo"],
        "tecnico_2": r.get("Técnico"),
        "diag_jira_2": r["diag_jira"],
        "diag_ofs_2": r["diag_ofs"],
        "obs_2": r["obs"],
        "valor_servico": pd.to_numeric(r.get("R$ Serviço"), errors="coerce"),
    }).reset_index(drop=True)
    casos["dias"] = (casos["data_2"] - casos["data_1"]).dt.days
    casos["id_caso"] = casos["os_1"].astype(str) + "→" + casos["os_2"].astype(str)
    casos = casos.dropna(subset=["os_1", "os_2"]).drop_duplicates("id_caso")
    casos["criticidade"] = casos["dias"].map(criticidade)
    return casos.sort_values("data_2").reset_index(drop=True)


def _tem(texto: str, termos) -> str:
    t = sem_acento(texto)
    for termo in termos:
        if sem_acento(termo) in t:
            return termo
    return ""


def triar(casos: pd.DataFrame, cfg: dict, obs_ofs: dict | None = None) -> pd.DataFrame:
    """Regra da empresa: retorno ao mesmo veículo em até 90 dias = retrabalho, salvo as exceções abaixo.
    obs_ofs: {OS: texto com observação do técnico, vistoria, flags} vindo das bases diárias do sistema."""
    cfg = {**PADRAO, **(cfg or {})}
    obs_ofs = obs_ofs or {}
    primeiras = {}
    for caso, os1 in zip(casos["caso"], casos["os_1"]):
        primeiras.setdefault(os1, caso)
    decisoes, motivos, obs_col = [], [], []
    for _, c in casos.iterrows():
        obs2 = obs_ofs.get(str(c["os_2"]), "")
        obs_col.append(obs2 or None)
        diags = " | ".join(str(x) for x in (c["diag_jira_2"], c["diag_ofs_2"], c["obs_2"]) if pd.notna(x))
        tudo = diags + " | " + obs2
        tipo1, tipo2 = sem_acento(c["tipo_1"]), sem_acento(c["tipo_2"])

        if c["os_2"] in primeiras and primeiras[c["os_2"]] != c["caso"]:
            d, m = "Expurgado", f"Duplicidade: o retorno ({c['os_2']}) é a 1ª visita do caso {primeiras[c['os_2']]}, que é o que conta"
        elif tipo2.startswith("retirada"):
            d, m = "Expurgado", "Retorno é retirada (cancelamento ou troca de veículo), não é retrabalho"
        elif pd.notna(c["dias"]) and c["dias"] > cfg["janela_dias"]:
            d, m = "Expurgado", f"Fora da janela de {cfg['janela_dias']} dias"
        elif "flag_sinistro=sim" in obs2 or (termo := _tem(obs2, cfg["termos_terceiro"])):
            d, m = "Expurgado", "Sinistro / terceiro na observação do técnico" + (f" (\u201c{termo}\u201d)" if termo else " (flag de sinistro)")
        elif "equipamentos_trocados=" in obs2 or (termo := _tem(obs2, cfg["termos_equipamento"])):
            d, m = "Expurgado", "Defeito / troca de equipamento na observação do técnico" + (f" (\u201c{termo}\u201d)" if termo else "")
        elif (tipo1.startswith(SERVICO_INICIAL) and pd.notna(c["dias"]) and c["dias"] <= cfg["dias_peca"]
              and (termo := _tem(tudo, cfg["termos_peca"]))):
            d, m = "Expurgado", f"Peça faltante / kit incompleto após serviço inicial, retorno em {int(c['dias'])} dias (\u201c{termo}\u201d)"
        elif termo := _tem(tudo, cfg["termos_revisar"]):
            d, m = "Para analisar", f"Sinal para revisar: \u201c{termo}\u201d"
        elif not obs2:
            d, m = "Para analisar", f"Retorno em até {cfg['janela_dias']} dias; sem observação do técnico no painel para checar sinistro ou equipamento"
        else:
            d, m = "Retrabalho", f"Retorno em até {cfg['janela_dias']} dias sem nenhuma exceção"
        decisoes.append(d)
        motivos.append(m)
    out = casos.copy()
    out["decisao_auto"] = decisoes
    out["motivo_auto"] = motivos
    out["obs_tecnico_ofs"] = obs_col
    return out
