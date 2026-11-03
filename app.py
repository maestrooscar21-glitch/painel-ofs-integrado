"""Painel Operacional OFS — todos os serviços (instalação, retirada, renovação,
reinstalação e manutenção). Rode com:  streamlit run app.py"""
import io
import unicodedata
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import banco
import regras
import retrabalho as rt
import auditoria as aud
import capacidade as cap
import eficiencia as ef
import financeiro as fin
import extrato as ext
import random

st.set_page_config(page_title="Painel OFS", page_icon="🛠️", layout="wide")

PCT = ["Execução da agenda", "Improdutividade", "Improdutividade dos encaixes", "Cancelamento", "Perda de OS",
       "Participação de encaixes"]
AJUDA = {
    "Atendimentos agendados": "OS que estavam no planejamento vigente do dia e já tinham aparecido num planejado "
                              "exportado antes do dia (prova de agendamento). Todos os tipos de serviço.",
    "Atendimentos executados": "Atendimentos da agenda que foram concluídos.",
    "Encaixes": "OS concluídas no dia sem prova de agendamento antes do dia: o técnico já estava no local e "
                "fez um serviço a mais, ou a OS foi criada no próprio dia.",
    "Improdutivas": "Total de OS não concluídas no dia: as da agenda + as de encaixe.",
    "Improdutivas da agenda": "Atendimentos agendados que terminaram não concluídos.",
    "Improdutivas de encaixe": "OS abertas fora da agenda (encaixe) que terminaram não concluídas. Ex.: o técnico "
                               "pediu a OS no local e não conseguiu concluir.",
    "Total realizado": "Todos os atendimentos concluídos no dia: os da agenda + os encaixes.",
    "Improdutividade dos encaixes": "Improdutivas de encaixe ÷ (encaixes + improdutivas de encaixe): de cada OS "
                                    "aberta fora da agenda, quantas não foram concluídas.",
    "Canceladas": "Atendimentos agendados que apareceram cancelados no resultado.",
    "OS perdidas": "Atendimentos agendados que não apareceram no resultado (nem trocados por outra OS com o "
                   "mesmo ticket + placa).",
    "Execução da agenda": "Atendimentos executados ÷ atendimentos agendados.",
    "Improdutividade": "Improdutivas ÷ (executados + encaixes + improdutivas).",
    "Cancelamento": "Canceladas ÷ atendimentos agendados.",
    "Perda de OS": "OS perdidas ÷ atendimentos agendados.",
    "Participação de encaixes": "Encaixes ÷ (executados + encaixes).",
}
COLS_OS = ["data_operacional", "classificacao", "origem", "familia", "tipo_atividade", "ticket", "placa", "os",
           "os_planejada", "troca_os", "oficina", "tecnico", "uf_base", "primeira_aparicao", "data_planejada",
           "status_planejado", "status_resultado", "razao_improdutiva", "obs_improdutiva", "obs_tecnico", "motivo"]
NOMES_OS = {"data_operacional": "Data", "classificacao": "Classificação", "origem": "Origem", "familia": "Família",
            "tipo_atividade": "Tipo de atividade", "ticket": "Ticket", "placa": "Placa", "os": "OS",
            "os_planejada": "OS planejada", "troca_os": "Troca de OS", "oficina": "Oficina", "tecnico": "Técnico",
            "uf_base": "UF-base", "primeira_aparicao": "Primeira aparição", "data_planejada": "Data planejada",
            "status_planejado": "Status planejado", "status_resultado": "Status resultado",
            "razao_improdutiva": "Razão da improdutiva", "obs_improdutiva": "Obs. do técnico (improdutiva)",
            "obs_tecnico": "Observações do técnico", "motivo": "Motivo da classificação"}


# ---------------------------------------------------------------- acesso
def checar_senha():
    try:
        senha = st.secrets["senha_app"]
    except Exception:
        return
    if st.session_state.get("liberado"):
        return
    st.title("Painel OFS")
    digitada = st.text_input("Senha de acesso", type="password")
    if digitada and digitada == senha:
        st.session_state["liberado"] = True
        st.rerun()
    elif digitada:
        st.error("Senha incorreta.")
    st.stop()


checar_senha()


def senha_admin():
    try:
        return str(st.secrets["senha_admin"])
    except Exception:
        return None


def eh_admin() -> bool:
    """Administrador: quem digitou a senha_admin nesta sessão. Sem senha_admin nos Secrets (uso local), todos são admin."""
    return senha_admin() is None or bool(st.session_state.get("admin"))


def pedir_admin(onde: str):
    st.info(f"🔒 **{onde}** é restrito ao administrador do painel.")
    s_ = st.text_input("Senha de administrador", type="password", key=f"adm_{onde}")
    if s_:
        if s_ == senha_admin():
            st.session_state["admin"] = True
            st.rerun()
        else:
            st.error("Senha de administrador incorreta.")


# ---------------------------------------------------------------- dados
@st.cache_data(ttl=300)
def montar_classificacao(ativ: pd.DataFrame, oficinas: pd.DataFrame) -> pd.DataFrame:
    if ativ.empty:
        return pd.DataFrame()
    res = ativ[ativ["tipo_base"] == "resultado"]
    pla = ativ[ativ["tipo_base"] == "planejado"]
    partes = []
    for dia in sorted(res["data"].unique()):
        parte = regras.classificar_dia(dia, pla, res)
        if not parte.empty:
            parte["tem_planejamento"] = parte["plano_vigente"].notna()
            partes.append(parte)
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, ignore_index=True)
    for c in COLS_OS:
        if c not in df.columns:
            df[c] = None
    of = oficinas[["id", "consultor", "uf_base", "cidade_base"]].rename(columns={"id": "id_oficina"})
    df = df.drop(columns=[c for c in ("consultor", "uf_base", "cidade_base") if c in df.columns]).merge(of, on="id_oficina", how="left")
    df["consultor"] = df["consultor"].fillna("Sem cadastro")
    df["tecnico"] = df["tecnico"].fillna("Não informado")
    df["semana"] = pd.to_datetime(df["data_operacional"]).dt.to_period("W-SUN").map(
        lambda p: f"{p.start_time:%d/%m} a {p.end_time:%d/%m}")
    df["semana_ini"] = pd.to_datetime(df["data_operacional"]).dt.to_period("W-SUN").map(lambda p: p.start_time.date())
    return df


ativ = banco.carregar_atividades()
oficinas_todas = banco.carregar_oficinas()
# os indicadores da rede usam só as credenciadas; as próprias têm a área 🏠 Oficinas próprias
oficinas = oficinas_todas[oficinas_todas["tipo"] == "Credenciada"]
# filtro geral por consultor: todas as telas passam a mostrar só as oficinas dele
CONSULTORES = sorted(oficinas_todas["consultor"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique())
consultor_ver = st.session_state.get("consultor_global", "Todos")
if consultor_ver not in ["Todos"] + CONSULTORES:
    consultor_ver = "Todos"
if consultor_ver != "Todos":
    oficinas = oficinas[oficinas["consultor"].astype(str).str.strip() == consultor_ver]
ufs_regiao = banco.ler_config("ufs_regiao", regras.UFS_PADRAO)
ativ_todas = ativ
ativ = regras.filtrar_regiao(ativ, oficinas, ufs_regiao)
base = montar_classificacao(ativ, oficinas)
cfg_rt = {**rt.PADRAO, **banco.ler_config("regras_retrabalho", {})}
rt_causas = ["Serviço mal executado", "Equipamento com defeito", "Equipamento mal configurado", "Cabeamento / conexão",
             "Diagnóstico incorreto", "Peça ou material faltante", "Defeito de fabricação", "Mau uso do cliente",
             "Sinistro / dano externo", "Problema novo / sem relação", "Outro"]


def id_por_nome() -> dict:
    """Liga o nome da oficina (como vem na base de retrabalho) ao ID do sistema."""
    mapa = {}
    if not ativ_todas.empty:
        for n, i in ativ_todas.dropna(subset=["oficina", "id_oficina"])[["oficina", "id_oficina"]].drop_duplicates().values:
            mapa[rt.sem_acento(n)] = str(i)
    for n, i in oficinas[["oficina", "id"]].dropna().values:
        mapa.setdefault(rt.sem_acento(n), str(i))
    for i, apelidos in oficinas[["id", "outros_nomes"]].dropna().values:  # outros nomes da mesma oficina
        for ap in str(apelidos).split(";"):
            if ap.strip():
                mapa[rt.sem_acento(ap)] = str(i)
    return mapa


def compacto(nome) -> str:
    n = rt.sem_acento(nome)
    for sufixo in (" ltda", " me", " eireli", " s/a", " sa", " epp"):
        n = n.replace(sufixo, " ")
    return "".join(ch for ch in n if ch.isalnum())


def achar_id_fn():
    """Função que liga o nome da oficina (como vem em planilhas sem ID) ao ID do cadastro."""
    mapa = id_por_nome()
    cad_compacto = {compacto(n): str(i) for n, i in oficinas[["oficina", "id"]].dropna().values}
    for i, apelidos in oficinas[["id", "outros_nomes"]].dropna().values:
        for ap in str(apelidos).split(";"):
            if ap.strip():
                cad_compacto[compacto(ap)] = str(i)

    def achar(nome):
        if rt.sem_acento(nome) in mapa:
            return mapa[rt.sem_acento(nome)]
        c = compacto(nome)
        if c in cad_compacto:
            return cad_compacto[c]
        for k, v in cad_compacto.items():
            if len(k) >= 5 and len(c) >= 5 and (c.startswith(k) or k.startswith(c)):
                return v
        return None
    return achar


def na_regiao(df: pd.DataFrame, col_nome: str = "oficina") -> pd.DataFrame:
    """Liga cada linha à oficina do cadastro pelo nome e mantém só as da região."""
    if df.empty:
        return df
    achar = achar_id_fn()
    df = df.copy()
    df["id_oficina"] = df[col_nome].map(achar)
    uf_cad = dict(zip(oficinas["id"].astype(str), oficinas["uf_base"].fillna("").str.upper()))
    df["uf_base"] = df["id_oficina"].map(uf_cad).fillna("")
    df = df[df["id_oficina"].astype(str).isin(set(oficinas["id"].astype(str)))]  # só oficinas do cadastro (e do consultor escolhido)
    if ufs_regiao:
        df = df[df["uf_base"].isin([u.upper() for u in ufs_regiao])]
    nomes_cad = dict(zip(oficinas["id"].astype(str), oficinas["oficina"]))
    df["oficina_cad"] = df["id_oficina"].map(nomes_cad)
    return df


def bloco_proprias(sug: pd.DataFrame, chave: str):
    """Mostra as oficinas próprias sugeridas e permite incluí-las no cadastro."""
    ja = set(oficinas_todas["oficina"].map(compacto))
    sug = sug[~sug["oficina"].map(compacto).isin(ja)]
    if sug.empty:
        return
    with st.container(border=True):
        st.markdown("**🏠 Possíveis oficinas próprias** (mesmo nome do cliente que atendem)")
        st.caption("Confirme as que são oficinas próprias: elas entram no cadastro com Tipo = Própria e ficam fora dos "
                   "indicadores da rede (veja-as em 🏠 Oficinas próprias).")
        st.dataframe(sug.assign(**{"% OS com cliente de mesmo nome": (sug["mesmo_nome"] * 100).round(0)})
                     [["oficina", "OS", "uf", "% OS com cliente de mesmo nome"]]
                     .rename(columns={"oficina": "Oficina", "uf": "UF"}), hide_index=True, width="stretch")
        marcar = st.multiselect("Confirmar como oficinas próprias", sug["oficina"].tolist(), default=sug["oficina"].tolist(),
                                key=f"prop_{chave}")
        if marcar and st.button("Adicionar ao cadastro como próprias", key=f"btn_prop_{chave}"):
            consultor_pad = oficinas_todas["consultor"].dropna().mode().iat[0] if oficinas_todas["consultor"].notna().any() else None
            novas = pd.DataFrame([{"id": "PROP-" + compacto(n)[:30], "oficina": n, "tipo": "Própria",
                                   "uf_base": sug.set_index("oficina").loc[n, "uf"], "consultor": consultor_pad,
                                   "ativa": "Sim", "contrato": "Tabela", "observacao": "Oficina própria do cliente"}
                                  for n in marcar])
            banco.salvar_oficinas(pd.concat([oficinas_todas, novas], ignore_index=True))
            st.success(f"{len(marcar)} oficina(s) própria(s) incluída(s). Importe o arquivo de novo para gravar as OS delas.")
            st.rerun()


def regiao_retrabalho(casos: pd.DataFrame) -> pd.DataFrame:
    """Só entram oficinas do cadastro com UF-base da região. A base de retrabalho vem só com o nome da oficina,
    então o nome é ligado ao ID pelas bases diárias e pelo cadastro (aceitando variações como 'VXTECH CONECTA LTDA')."""
    if casos.empty:
        return casos
    mapa = id_por_nome()
    cad_compacto = {compacto(n): str(i) for n, i in oficinas[["oficina", "id"]].dropna().values}

    def achar_id(nome):
        if rt.sem_acento(nome) in mapa:
            return mapa[rt.sem_acento(nome)]
        c = compacto(nome)
        if c in cad_compacto:
            return cad_compacto[c]
        for k, v in cad_compacto.items():
            if len(k) >= 5 and len(c) >= 5 and (c.startswith(k) or k.startswith(c)):
                return v
        return None

    casos = casos.copy()
    casos["id_oficina"] = casos["oficina"].map(achar_id)
    uf_cad = dict(zip(oficinas["id"].astype(str), oficinas["uf_base"].fillna("").str.upper()))
    casos["uf_base"] = casos["id_oficina"].map(uf_cad).fillna("")
    casos = casos[casos["id_oficina"].astype(str).isin(set(oficinas["id"].astype(str)))]  # só oficinas do cadastro (e do consultor escolhido)
    if ufs_regiao:
        casos = casos[casos["uf_base"].isin([u.upper() for u in ufs_regiao])]
    return casos


def status_final(row):
    if isinstance(row.get("decisao_final"), str) and row["decisao_final"]:
        return row["decisao_final"]
    return {"Retrabalho": "Retrabalho", "Expurgado": "Não é retrabalho"}.get(row["decisao_auto"], "Pendente")


def obs_por_os() -> dict:
    """Observação do técnico, vistoria e flags de cada OS, vindas das bases diárias do sistema."""
    if ativ_todas.empty:
        return {}
    cols = [c for c in ("obs_tecnico", "obs_os_tecnico", "obs_vistoria", "diag_real") if c in ativ_todas.columns]
    d = ativ_todas.sort_values("data_ref").drop_duplicates("os", keep="last")
    saida = {}
    for _, r in d.iterrows():
        partes = [str(r[c]) for c in cols if pd.notna(r[c]) and str(r[c]).strip()]
        if "flag_sinistro" in d.columns and rt.sem_acento(r.get("flag_sinistro")) == "sim":
            partes.append("flag_sinistro=sim")
        if "equip_trocados" in d.columns and pd.notna(r.get("equip_trocados")) and str(r["equip_trocados"]).strip():
            partes.append(f"equipamentos_trocados={r['equip_trocados']}")
        if partes:
            saida[str(r["os"])] = " | ".join(partes)
    return saida


obs_ofs = obs_por_os()
sin_confirmados = set()
casos_rt = banco.carregar_retrabalho()
if not casos_rt.empty:
    casos_rt = regiao_retrabalho(rt.triar(casos_rt, cfg_rt, obs_ofs))
    casos_rt["criticidade"] = casos_rt["dias"].map(rt.criticidade)  # recalcula (bases antigas guardaram outra cor)
    casos_rt["status"] = casos_rt.apply(status_final, axis=1)
    casos_rt["origem"] = casos_rt["decisao_final"].map(lambda v: "Manual" if isinstance(v, str) and v else "Automática")
    # OS de retorno em que a análise de retrabalho identificou sinistro: contam como sinistro apontado
    sin_confirmados = set(casos_rt.loc[casos_rt["sinistro_conf"] == "Sim", "os_2"].astype(str))


# ---------------------------------------------------------------- utilidades
def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%".replace(".", ",")


def tabela_indicadores(df: pd.DataFrame, coluna: str, rotulo: str, ordenar_por_valor: bool = False):
    t = regras.tabela_por(df, coluna)
    if t.empty:
        st.info("Nada a mostrar no recorte selecionado.")
        return
    t = t[(t["Atendimentos agendados"] + t["Encaixes"] + t["Improdutivas"]) > 0]
    for c in PCT:
        t[c] = pd.to_numeric(t[c], errors="coerce").mul(100).round(1)
    cols = [coluna, "Atendimentos agendados", "Atendimentos executados", "Encaixes", "Total realizado",
            "Improdutivas da agenda", "Improdutivas de encaixe", "Improdutivas", "Canceladas", "OS perdidas",
            "Execução da agenda", "Improdutividade", "Improdutividade dos encaixes", "Cancelamento", "Perda de OS"]
    cfg = {c: st.column_config.NumberColumn(c, format="%.1f%%", help=AJUDA.get(c)) for c in PCT}
    cfg[coluna] = st.column_config.TextColumn(rotulo)
    if coluna == "data_operacional":
        cfg[coluna] = st.column_config.DateColumn(rotulo, format="ddd DD/MM")
    t = t[cols].sort_values(coluna if ordenar_por_valor else "Total realizado", ascending=ordenar_por_valor)
    st.dataframe(t, hide_index=True, width="stretch", column_config=cfg)


def para_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def datas_do_nome(nome: str):
    """Datas no nome do arquivo: 'Spot_21_10_26-23_10_26' → (21/10/26, 23/10/26); 'Spot_22_10_26' → (22/10/26, None)."""
    import re
    achados = re.findall(r"(\d{2})_(\d{2})_(\d{2})", nome or "")
    datas = []
    for d_, m_, a_ in achados[:2]:
        try:
            datas.append(date(2000 + int(a_), int(m_), int(d_)))
        except ValueError:
            pass
    return (datas[0] if datas else None, datas[1] if len(datas) > 1 else None)


def norm(txt):
    txt = unicodedata.normalize("NFKD", str(txt))
    return "".join(c for c in txt if c.isalnum() and not unicodedata.combining(c)).lower()


COR = "#0E6E6B"
CORES_CRIT = {"🔴 0–15 dias": "#D64545", "🟡 16–59 dias": "#E8B73A", "🔵 60–90 dias": "#3B7DD8"}


def barras(df: pd.DataFrame, campo: str, titulo: str, top: int = 8):
    """Ranking horizontal com rótulo de quantidade e % do total."""
    if df.empty or df[campo].dropna().empty:
        st.caption(f"{titulo}: sem dados no recorte.")
        return
    cont = df[campo].fillna("Não informado").value_counts()
    total = cont.sum()
    t = cont.head(top).rename_axis("item").reset_index(name="qtd")
    t["pct"] = (t["qtd"] / total * 100).round(0).astype(int).astype(str) + "%"
    t["rotulo"] = t["qtd"].astype(str) + " · " + t["pct"]
    t["destaque"] = ["sim" if i < 2 else "não" for i in range(len(t))]
    base = alt.Chart(t).encode(y=alt.Y("item:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                               x=alt.X("qtd:Q", title=None, axis=None))
    graf = base.mark_bar(cornerRadiusEnd=3).encode(
        color=alt.Color("destaque:N", scale=alt.Scale(domain=["sim", "não"], range=[COR, "#9DBDBA"]), legend=None),
        tooltip=[alt.Tooltip("item:N", title=campo), alt.Tooltip("qtd:Q", title="Casos"), alt.Tooltip("pct:N", title="% do total")])
    texto = base.mark_text(align="left", dx=4, fontSize=12).encode(text="rotulo:N")
    st.markdown(f"**{titulo}**")
    st.altair_chart((graf + texto).properties(height=max(120, 30 * len(t))), width="stretch")


def visao_geral_retrabalho(cr: pd.DataFrame):
    incluir = st.toggle("Contar os pendentes como retrabalho (regra dos 90 dias)", value=True,
                        help="Pela regra da empresa, todo retorno em até 90 dias é retrabalho até ser expurgado. "
                             "Desligue para ver só o que já foi confirmado.")
    alvo = cr[cr["status"].isin(["Retrabalho", "Pendente"] if incluir else ["Retrabalho"])].copy()
    if alvo.empty:
        st.info("Nenhum retrabalho no recorte. Ajuste os filtros acima ou ligue a opção dos pendentes.")
        return
    alvo["motivo"] = alvo["diag_jira_2"].fillna(alvo["diag_ofs_2"]).fillna("Sem diagnóstico")
    alvo["motivo"] = alvo["motivo"].astype(str).str.split(r"[,.\n]").str[0].str.strip().str.capitalize()
    total = len(alvo)

    # destaques em texto
    def lider(serie):
        c = serie.fillna("Não informado").value_counts()
        return c.index[0], int(c.iloc[0]), c.iloc[0] / c.sum() * 100

    of, of_n, of_p = lider(alvo["oficina"])
    mo, mo_n, mo_p = lider(alvo["motivo"])
    fx, fx_n, fx_p = lider(alvo["criticidade"])
    d = st.columns(3)
    for col, rotulo, nome, n, p in ((d[0], "Oficina com mais retrabalho", of, of_n, of_p),
                                    (d[1], "Principal motivo", mo, mo_n, mo_p),
                                    (d[2], "Faixa de dias mais comum", fx, fx_n, fx_p)):
        with col.container(border=True):
            st.caption(rotulo)
            st.markdown(f"#### {nome}")
            st.markdown(f"**{n} casos** · {p:.0f}% do total")
    st.caption(f"{total} retrabalho(s) no recorte" + (" (confirmados + pendentes)." if incluir else " confirmados."))

    c1, c2 = st.columns(2)
    with c1:
        barras(alvo, "oficina", "Retrabalho por oficina")
    with c2:
        barras(alvo, "motivo", "Principais motivos (diagnóstico do retorno)")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Em quanto tempo o veículo voltou**")
        fx_t = alvo["criticidade"].value_counts().rename_axis("faixa").reset_index(name="qtd")
        fx_t["pct"] = (fx_t["qtd"] / total * 100).round(0).astype(int).astype(str) + "%"
        rosca = alt.Chart(fx_t).encode(
            theta=alt.Theta("qtd:Q", stack=True),
            color=alt.Color("faixa:N", scale=alt.Scale(domain=list(CORES_CRIT), range=list(CORES_CRIT.values())),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=[alt.Tooltip("faixa:N", title="Faixa"), alt.Tooltip("qtd:Q", title="Casos"), alt.Tooltip("pct:N", title="%")])
        graf = rosca.mark_arc(innerRadius=55, outerRadius=110, stroke="white")
        rot = rosca.mark_text(radius=82, fontSize=13, fontWeight="bold", color="white").encode(text="pct:N")
        st.altair_chart((graf + rot).properties(height=290), width="stretch")
    with c4:
        if "cliente" in alvo.columns and alvo["cliente"].notna().any():
            barras(alvo, "cliente", "Clientes com mais retrabalho", top=6)
        else:
            st.caption("Para ver os clientes, reimporte a base de retrabalho em Dados → Retrabalho.")
        barras(alvo, "tecnico_1", "Técnicos da 1ª visita com mais retornos", top=6)

    st.markdown("**Evolução mês a mês**")
    meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro",
             "outubro", "novembro", "dezembro"]
    ev = alvo.groupby(["competencia", "oficina"]).size().rename("qtd").reset_index()
    ev["ordem"] = ev["competencia"].map(lambda s: str(s).split("/")[-1] + "-" +
                                        f"{meses.index(rt.sem_acento(str(s).split('/')[0])) + 1:02d}"
                                        if rt.sem_acento(str(s).split("/")[0]) in meses else str(s))
    ordem = ev.sort_values("ordem")["competencia"].drop_duplicates().tolist()
    top_of = alvo["oficina"].value_counts().head(5).index
    ev["oficina"] = ev["oficina"].where(ev["oficina"].isin(top_of), "Outras")
    ev = ev.groupby(["competencia", "oficina"], as_index=False)["qtd"].sum()
    st.altair_chart(alt.Chart(ev).mark_bar().encode(
        x=alt.X("competencia:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=-30)),
        y=alt.Y("qtd:Q", title="Retrabalhos"),
        color=alt.Color("oficina:N", legend=alt.Legend(title=None, orient="bottom")),
        tooltip=["competencia", "oficina", "qtd"]).properties(height=300), width="stretch")



def ranking_taxa(t: pd.DataFrame, campo: str, titulo: str, meta: float, altura_min: int = 120):
    """Barras de % de aprovação, coloridas pela meta (verde-petróleo ≥ meta, amarelo até 15 p.p. abaixo, vermelho)."""
    if t.empty:
        st.caption(f"{titulo}: sem auditorias no recorte.")
        return
    t = t.copy()
    t["faixa"] = t["% aprovação"].map(lambda v: "Na meta" if v >= meta else ("Atenção" if v >= meta - 15 else "Crítico"))
    t["rotulo"] = t["% aprovação"].map(lambda v: f"{v:.0f}%") + " · " + t["Auditadas"].astype(str) + " OS"
    base = alt.Chart(t).encode(y=alt.Y(f"{campo}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=280)),
                               x=alt.X("% aprovação:Q", title=None, scale=alt.Scale(domain=[0, 115]), axis=None))
    barras_ = base.mark_bar(cornerRadiusEnd=3).encode(
        color=alt.Color("faixa:N", scale=alt.Scale(domain=["Na meta", "Atenção", "Crítico"],
                                                   range=[COR, "#E8B73A", "#D64545"]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=[alt.Tooltip(f"{campo}:N", title=""), "Auditadas", "Aprovadas", "% aprovação", "Conformidade"])
    regra = alt.Chart(pd.DataFrame({"m": [meta]})).mark_rule(strokeDash=[4, 4], color="#555").encode(x="m:Q")
    texto = base.mark_text(align="left", dx=4, fontSize=12).encode(text="rotulo:N")
    st.markdown(f"**{titulo}**")
    st.altair_chart((barras_ + texto + regra).properties(height=max(altura_min, 30 * len(t))), width="stretch")


def indica_sinistro(r) -> str:
    if rt.sem_acento(r.get("flag_sinistro")) == "sim":
        return "flag de sinistro na OS"
    if str(r.get("os")) in sin_confirmados:
        return "sinistro confirmado na análise de retrabalho"
    texto = " ".join(str(r.get(c) or "") for c in ("obs_tecnico", "obs_os_tecnico", "obs_vistoria"))
    termo = rt._tem(texto, cfg_rt["termos_terceiro"])
    return f"\u201c{termo}\u201d na observação do técnico" if termo else ""

# ---------------------------------------------------------------- navegação
with st.sidebar:
    if len(CONSULTORES) > 1:
        st.selectbox("👤 Consultor", ["Todos"] + CONSULTORES, key="consultor_global",
                     help="Mostra em todas as telas só as oficinas deste consultor (pelo campo Consultor do cadastro).")
    st.header("Navegação")
    st.caption("Versão 6.0 — consolidado até setembro")
    # menu agrupado pelos pilares da gestão: um grupo por pilar, só uma opção marcada no total
    MENU = [
        ("nav_prop", "Oficinas próprias", ["🏠 Oficinas próprias"]),
        ("nav_vol", "Volume de serviços", ["📊 Painel"]),
        ("nav_disp", "Disponibilidade / Capacidade", ["📈 Capacidade", "🔧 Improdutividade"]),
        ("nav_qual", "Qualidade", ["🔁 Retrabalho", "✅ Auditoria", "⚠️ Mau uso (sinistro)", "📝 Não conformidade", "🏆 Eficiência"]),
        ("nav_fin", "Financeiro", ["💰 Financeiro", "📅 Comparativo anual"]),
        ("nav_setup", "Setup", ["📥 Dados", "⚙️ Configurações"]),
    ]
    if "area" not in st.session_state:
        st.session_state["area"] = "📊 Painel"

    def _nav(chave):
        valor = st.session_state.get(chave)
        if valor:
            st.session_state["area"] = valor
            for k_, _, _ in MENU:
                if k_ != chave:
                    st.session_state[k_] = None

    for k_, titulo, opcoes in MENU:
        if k_ not in st.session_state:
            st.session_state[k_] = st.session_state["area"] if st.session_state["area"] in opcoes else None
        if k_ == "nav_vol":
            st.markdown("<div style='margin-top:0.6rem;font-weight:700'>Oficinas parceiras</div>", unsafe_allow_html=True)
        st.radio(titulo, opcoes, key=k_, on_change=_nav, args=(k_,),
                 label_visibility="collapsed" if k_ == "nav_prop" else "visible")
        if k_ == "nav_qual":
            st.markdown("<div style='font-size:0.85rem;font-weight:600;margin-top:0.3rem'>Controle / Execução</div>"
                        "<div style='font-size:0.78rem;color:gray'>Em breve: SLA, TMA, aceite/rejeição e estoque</div>",
                        unsafe_allow_html=True)
    area = st.session_state["area"]
    if senha_admin() is not None:
        st.divider()
        if st.session_state.get("admin"):
            st.caption("🔓 Modo administrador ativo")
            if st.button("Sair do modo administrador"):
                st.session_state["admin"] = False
                st.rerun()
        else:
            st.caption("🔒 Configurações e exclusões: só administrador")

filtrado = pd.DataFrame()
contexto = ""
modo = "Período"
if area in ("📊 Painel", "🔧 Improdutividade") and not base.empty:
    with st.sidebar:
        st.divider()
        st.subheader("Filtros")
        dias = sorted(base["data_operacional"].unique())
        modo = st.radio("Ver por", ["Semana", "Dia", "Período"], horizontal=True)
        if modo == "Semana":
            semanas = sorted(base["semana_ini"].unique(), reverse=True)
            sem = st.selectbox("Semana (segunda a domingo)", semanas,
                               format_func=lambda d: f"{d:%d/%m} a {d + timedelta(days=6):%d/%m/%Y}")
            ini, fim = sem, sem + timedelta(days=6)
        elif modo == "Dia":
            dia_sel = st.selectbox("Dia", list(reversed(dias)), format_func=lambda d: f"{d:%a %d/%m/%Y}")
            ini = fim = dia_sel
        else:
            ini_padrao = max(dias[0], dias[-1] - timedelta(days=29))
            periodo = st.date_input("Período", (ini_padrao, dias[-1]), min_value=dias[0], max_value=dias[-1],
                                    format="DD/MM/YYYY")
            ini, fim = (periodo if len(periodo) == 2 else (periodo[0], periodo[0]))
        consultores = sorted(base["consultor"].unique())
        consultor = st.selectbox("Consultor", ["Todos"] + consultores)
        recorte = base[(base["data_operacional"] >= ini) & (base["data_operacional"] <= fim)]
        if consultor != "Todos":
            recorte = recorte[recorte["consultor"] == consultor]
        sel_of = st.multiselect("Oficina", sorted(recorte["oficina"].dropna().unique()), placeholder="Todas")
        if sel_of:
            recorte = recorte[recorte["oficina"].isin(sel_of)]
        sel_tec = st.multiselect("Técnico", sorted(recorte["tecnico"].dropna().unique()), placeholder="Todos")
        if sel_tec:
            recorte = recorte[recorte["tecnico"].isin(sel_tec)]
        sel_fam = st.multiselect("Família de serviço", regras.FAMILIAS, placeholder="Todas")
    if sel_fam:
        recorte = recorte[recorte["familia"].isin(sel_fam)]
    filtrado = recorte
    quem = ", ".join(sel_tec) if sel_tec else (", ".join(sel_of) if sel_of else
                                                (consultor if consultor != "Todos" else "Região toda"))
    contexto = (f"{quem} — {', '.join(sel_fam) if sel_fam else 'todos os serviços'} — "
                f"{'semana de ' if modo == 'Semana' else ''}{ini:%d/%m/%Y}"
                + (f" a {fim:%d/%m/%Y}" if fim != ini else "") + ".")


def sem_dados():
    st.info("Ainda não há resultado importado. Vá em **📥 Dados** e importe o cadastro de oficinas, "
            "o planejado e pelo menos um resultado.")


# ---------------------------------------------------------------- painel
if area == "📊 Painel":
    st.title({"Semana": "Visão semanal", "Dia": "Visão diária"}.get(modo, "Painel operacional"))
    if base.empty:
        sem_dados()
        st.stop()
    st.caption(contexto)
    sem_plano = filtrado[~filtrado["tem_planejamento"]]["data_operacional"].unique()
    if len(sem_plano):
        st.warning("Sem planejado importado para " + ", ".join(f"{d:%d/%m}" for d in sorted(sem_plano))
                   + ". Nesses dias tudo que foi executado aparece como encaixe.")

    ind = regras.indicadores(filtrado)
    FILTROS_VER = {
        "realizado": lambda d: d[d["classificacao"].isin([regras.EXECUTADO, regras.ENCAIXE])],
        "improd_total": lambda d: d[d["classificacao"] == regras.IMPRODUTIVA],
        "agendada": lambda d: d[d["agendada"]],
        "executado": lambda d: d[d["classificacao"] == regras.EXECUTADO],
        "encaixe": lambda d: d[d["classificacao"] == regras.ENCAIXE],
        "improd_agenda": lambda d: d[(d["classificacao"] == regras.IMPRODUTIVA) & (d["origem"] == "Agendada")],
        "improd_encaixe": lambda d: d[(d["classificacao"] == regras.IMPRODUTIVA) & (d["origem"] == "Encaixe")],
        "cancelada": lambda d: d[d["classificacao"] == regras.CANCELADA],
        "perdida": lambda d: d[d["classificacao"] == regras.PERDIDA],
    }

    def cartao(col, rotulo, chave, valor=None, nome=None):
        col.metric(nome or rotulo, ind[rotulo] if valor is None else valor, help=AJUDA.get(rotulo))
        if col.button("🔎 Ver OS", key=f"ver_{chave}", width="stretch"):
            st.session_state["ver"] = (rotulo, chave)

    d1, d2 = st.columns(2)
    with d1.container(border=True):
        st.markdown("##### ✅ Total de atendimentos realizados")
        c = st.columns([1.2, 1, 1])
        cartao(c[0], "Total realizado", "realizado", nome="Total")
        c[1].metric("Da agenda", ind["Atendimentos executados"])
        c[2].metric("Encaixes", ind["Encaixes"])
    with d2.container(border=True):
        st.markdown("##### ⚠️ Total de improdutivas")
        c = st.columns([1.2, 1, 1])
        cartao(c[0], "Improdutivas", "improd_total", nome="Total")
        c[1].metric("Da agenda", ind["Improdutivas da agenda"])
        c[2].metric("De encaixe", ind["Improdutivas de encaixe"])

    st.markdown("**Detalhamento dos atendimentos**")
    cols = st.columns(7)
    for col, (rotulo, chave, nome) in zip(cols, [
            ("Atendimentos agendados", "agendada", "Agendados"),
            ("Atendimentos executados", "executado", "Executados"),
            ("Encaixes", "encaixe", "Encaixes"),
            ("Improdutivas da agenda", "improd_agenda", "Improd. agenda"),
            ("Improdutivas de encaixe", "improd_encaixe", "Improd. encaixe"),
            ("Canceladas", "cancelada", "Canceladas"),
            ("OS perdidas", "perdida", "OS perdidas")]):
        cartao(col, rotulo, chave, nome=nome)
    if ind["Status intermediário"]:
        st.caption(f"{ind['Status intermediário']} OS em status intermediário (pendente/iniciado no resultado).")

    st.subheader("Indicadores")
    curtos = {"Execução da agenda": "Execução agenda", "Improdutividade": "Improdutividade",
              "Improdutividade dos encaixes": "Improd. encaixes", "Cancelamento": "Cancelamento",
              "Perda de OS": "Perda de OS", "Participação de encaixes": "% de encaixes"}
    cols = st.columns(len(PCT))
    for col, rotulo in zip(cols, PCT):
        col.metric(curtos[rotulo], pct(ind[rotulo]), help=AJUDA[rotulo])

    if "ver" in st.session_state:
        rotulo, chave = st.session_state["ver"]
        lista = FILTROS_VER.get(chave, lambda d: d.iloc[0:0])(filtrado)
        lista = lista[COLS_OS].rename(columns=NOMES_OS).sort_values(["Data", "Oficina"])
        st.divider()
        st.subheader(f"🔎 Conferência das OS — {rotulo}")
        st.caption(f"{contexto} {len(lista)} atendimento(s).")
        st.dataframe(lista, hide_index=True, width="stretch", column_config={
            "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Primeira aparição": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Data planejada": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Motivo da classificação": st.column_config.TextColumn(width="large")})
        c1, c2 = st.columns([1, 3])
        if c1.button("✕ Fechar", width="stretch"):
            del st.session_state["ver"]
            st.rerun()
        c2.download_button("⬇️ Baixar estas OS em Excel", para_excel(lista), "os_conferencia.xlsx", width="stretch")

    st.divider()
    nomes_abas = (["Dia a dia", "Por oficina", "Por técnico", "Por família de serviço"] if modo == "Semana" else
                  ["Por oficina", "Por técnico", "Por família de serviço"] if modo == "Dia" else
                  ["Por oficina", "Por técnico", "Por família de serviço", "Semanal", "Dia a dia"])
    abas = dict(zip(nomes_abas, st.tabs(nomes_abas)))
    with abas["Por oficina"]:
        tabela_indicadores(filtrado, "oficina", "Oficina")
    with abas["Por técnico"]:
        tabela_indicadores(filtrado.assign(tec=filtrado["tecnico"] + " (" + filtrado["oficina"].fillna("") + ")"),
                           "tec", "Técnico (oficina)")
    with abas["Por família de serviço"]:
        tabela_indicadores(filtrado, "familia", "Família")
    if "Semanal" in abas:
        with abas["Semanal"]:
            st.caption("Semanas de segunda a domingo.")
            tabela_indicadores(filtrado, "semana", "Semana")
    if "Dia a dia" in abas:
        with abas["Dia a dia"]:
            diario = regras.tabela_por(filtrado, "data_operacional")
            if not diario.empty:
                g = diario.melt(id_vars="data_operacional", value_vars=["Atendimentos executados", "Encaixes", "Improdutivas"],
                                var_name="Tipo", value_name="Qtd")
                g["Dia"] = pd.to_datetime(g["data_operacional"]).dt.strftime("%a %d/%m")
                ordem = pd.to_datetime(diario.sort_values("data_operacional")["data_operacional"]).dt.strftime("%a %d/%m").tolist()
                st.altair_chart(alt.Chart(g).mark_bar().encode(
                    x=alt.X("Dia:N", sort=ordem, title=None), y=alt.Y("Qtd:Q", title="Atendimentos"),
                    color=alt.Color("Tipo:N", scale=alt.Scale(domain=["Atendimentos executados", "Encaixes", "Improdutivas"],
                                                               range=[COR, "#7FB8B3", "#D64545"]),
                                    legend=alt.Legend(title=None, orient="bottom")),
                    tooltip=["Dia", "Tipo", "Qtd"]).properties(height=260), width="stretch")
            tabela_indicadores(filtrado, "data_operacional", "Dia", ordenar_por_valor=True)

    outros = filtrado[filtrado["classificacao"] == regras.OUTROS]
    if not outros.empty:
        with st.expander(f"OS fora da agenda que ficaram canceladas ou pendentes ({len(outros)}) — não entram nos indicadores"):
            st.dataframe(outros[COLS_OS].rename(columns=NOMES_OS), hide_index=True, width="stretch")


# ---------------------------------------------------------------- eficiência
elif area == "🏆 Eficiência":
    st.title("Eficiência das oficinas")
    metas = {**ef.METAS_PADRAO, **banco.ler_config("metas_eficiencia", {})}
    cfg_cap = {**cap.PADRAO, **banco.ler_config("capacidade", {})}
    ofs_reg = oficinas[oficinas["uf_base"].fillna("").str.upper().isin([u.upper() for u in ufs_regiao])] if ufs_regiao else oficinas
    tec = cap.tecnicos_por_oficina(ativ, ofs_reg)
    cap_d = cap.diario(ativ, base, tec, cfg_cap) if not ativ.empty else pd.DataFrame()
    auds_e = banco.carregar_auditorias()
    manuais = banco.carregar_manuais()
    manuais_ef = manuais
    ncs_e = banco.carregar_nc()
    if not ncs_e.empty:  # não conformidades registradas (procedentes) substituem o lançamento manual do mês
        proc = ncs_e[ncs_e["status"] == "Procedente"].assign(mes=lambda d: d["data"].dt.strftime("%Y-%m"))
        cont = proc.groupby(["id_oficina", "mes"]).size().rename("nc_reg").reset_index()
        manuais_ef = manuais.astype({"id_oficina": str}) if not manuais.empty else pd.DataFrame(columns=["id_oficina", "mes", "nao_conf", "no_show"])
        manuais_ef = manuais_ef.merge(cont.astype({"id_oficina": str}), on=["id_oficina", "mes"], how="outer")
        manuais_ef["nao_conf"] = manuais_ef["nc_reg"].combine_first(pd.to_numeric(manuais_ef["nao_conf"], errors="coerce"))
    dfe = ef.montar(base, casos_rt, auds_e, cap_d, manuais_ef, indica_sinistro)
    nomes = dict(zip(ofs_reg["id"].astype(str), ofs_reg["oficina"]))
    if dfe.empty:
        sem_dados()
        st.stop()
    dfe = dfe[dfe["id_oficina"].astype(str).isin(nomes)]
    dfe["oficina"] = dfe["id_oficina"].astype(str).map(nomes)
    # oficina com dois IDs (ex.: VX Tech): fica a linha com mais dados
    dfe = (dfe.assign(_n=dfe[list(ef.KPIS)].notna().sum(axis=1)).sort_values("_n")
              .drop_duplicates(["oficina", "mes"], keep="last").drop(columns="_n"))
    meses = sorted(dfe["mes"].dropna().unique(), reverse=True)
    meses_base = sorted(pd.to_datetime(base["data_operacional"]).dt.strftime("%Y-%m").unique(), reverse=True) if not base.empty else meses
    fmt_mes = lambda m: f"{m[5:]}/{m[:4]}"
    c1, c2, c3 = st.columns([1, 1.6, 1.2])
    mes_sel = c1.selectbox("Mês", meses, index=meses.index(meses_base[0]) if meses_base and meses_base[0] in meses else 0,
                           format_func=fmt_mes)
    modo_ef = c3.radio("Ver", ["Uma oficina", "Ranking"], horizontal=True)
    dm = dfe[dfe["mes"] == mes_sel].copy()
    dm["nota"] = dm.apply(lambda r: ef.nota(r, metas), axis=1)
    st.caption("🟢 dentro da meta · 🟡 perto do limite · 🔴 fora da meta · ⚪ sem dado. Retrabalho inclui os casos "
               "ainda pendentes de análise (regra dos 90 dias) e é calculado só nos dias com resultado importado. Nível de serviço e TME usam a "
               "\u201cData Portal\u201d do chamado até a execução. Ticket SLA/TMA entram com os dados do Gira. Metas em ⚙️ Configurações.")

    if modo_ef == "Uma oficina":
        of_sel = c2.selectbox("Oficina", sorted(dfe["oficina"].dropna().unique()))
        linha = dm[dm["oficina"] == of_sel]
        linha = linha.iloc[0] if not linha.empty else pd.Series(dtype=object)
        nt = ef.nota(linha, metas) if not linha.empty else None
        h1, h2 = st.columns([1, 3])
        with h1.container(border=True):
            st.caption(f"Nota de eficiência · {fmt_mes(mes_sel)}")
            st.markdown(f"## {nt if nt is not None else '—'}" + ("/100" if nt is not None else ""))
            st.caption("Média dos semáforos: 🟢 = 1, 🟡 = ½, 🔴 = 0.")
        with h2:
            mix = pd.DataFrame({"Tipo": ["Instalação / Renov. / Upgrade", "Manutenção", "Retirada / Reinstalação"],
                                "qtd": [linha.get(k) or 0 for k in ("inst", "manut", "ret")]})
            if mix["qtd"].sum():
                mix["pct"] = (mix["qtd"] / mix["qtd"].sum() * 100).round(0).astype(int).astype(str) + "%"
                st.markdown(f"**Mix de serviços** · {int(mix['qtd'].sum())} serviços no mês")
                st.altair_chart(alt.Chart(mix).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("Tipo:N", title=None, sort="-x"), x=alt.X("qtd:Q", title=None, axis=None),
                    color=alt.Color("Tipo:N", legend=None, scale=alt.Scale(range=[COR, "#E8B73A", "#9DBDBA"])),
                    tooltip=["Tipo", "qtd", "pct"]).properties(height=120)
                    + alt.Chart(mix).mark_text(align="left", dx=4).encode(
                    y=alt.Y("Tipo:N", sort="-x"), x="qtd:Q", text=alt.Text("pct:N")), width="stretch")
            else:
                st.info("Sem serviços realizados importados para este mês.")
        cols = st.columns(4)
        for col, pilar in zip(cols, ef.PILARES):  # mesmos pilares da planilha de gestão
            with col.container(border=True):
                st.markdown(f"**{pilar}**")
                for k, (rot, pl, _, _) in ef.KPIS.items():
                    if pl != pilar:
                        continue
                    v = linha.get(k) if not linha.empty else None
                    s = ef.semaforo(k, v, metas)
                    st.markdown(f"{s} {rot}  \n**{ef.formatar(k, v)}**"
                                + (f" <span style='color:gray;font-size:0.8em'>({ef.texto_meta(k, metas)})</span>"
                                   if ef.texto_meta(k, metas) else ""), unsafe_allow_html=True)
        st.subheader("Evolução mês a mês")
        hist = dfe[dfe["oficina"] == of_sel].set_index("mes").sort_index().tail(6)
        tabela = pd.DataFrame({fmt_mes(m): {f"{ef.KPIS[k][1]} · {ef.KPIS[k][0]}":
                               (ef.formatar(k, hist.loc[m, k]) + " " + ef.semaforo(k, hist.loc[m, k], metas)).strip()
                               for k in ef.KPIS} for m in hist.index})
        st.dataframe(tabela, width="stretch")
    else:
        rk = dm.sort_values("nota", ascending=False)
        tab = pd.DataFrame({"Oficina": rk["oficina"], "Nota": rk["nota"]})
        for k, (rot, _, _, sentido) in ef.KPIS.items():
            if k in ef.PENDENTES:
                continue
            tab[rot] = [(ef.formatar(k, v) + " " + ef.semaforo(k, v, metas)).strip() for v in rk[k]]
        st.dataframe(tab, hide_index=True, width="stretch",
                     column_config={"Nota": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=100)})

    # ---------------- extrato mensal em PDF
    st.subheader("📄 Extrato mensal da oficina")
    st.caption("PDF para enviar à oficina (WhatsApp/e-mail): nota, indicadores com meta e situação, volume, evolução, "
               "retrabalhos **confirmados**, auditoria e reclamações (**procedentes** com relato e análise; improcedentes só "
               "a quantidade). Sem dados de cliente e sem valores financeiros.")
    ofs_ext = st.multiselect("Oficinas", sorted(dm["oficina"].dropna().unique()), default=sorted(dm["oficina"].dropna().unique()),
                             key=f"ext_of_{mes_sel}")
    if st.button("Gerar extrato" + ("s" if len(ofs_ext) > 1 else ""), type="primary", disabled=not ofs_ext):
        ncs_all = banco.carregar_nc()
        ids_por_nome = ofs_reg.groupby("oficina")["id"].apply(lambda s: set(s.astype(str))).to_dict()
        dias_base = set(base["data_operacional"]) if not base.empty else set()
        rank = dm.dropna(subset=["nota"]).sort_values("nota", ascending=False)["oficina"].tolist()
        arquivos = {}
        for of_ in ofs_ext:
            ids_ = ids_por_nome.get(of_, set())
            lin = dm[dm["oficina"] == of_]
            lin = lin.iloc[0].copy() if not lin.empty else pd.Series(dtype=object)
            # retrabalho do extrato: só casos confirmados
            rconf = pd.DataFrame()
            if not casos_rt.empty:
                rconf = casos_rt[(casos_rt["status"] == "Retrabalho") & casos_rt["id_oficina"].astype(str).isin(ids_)
                                 & (pd.to_datetime(casos_rt["data_2"]).dt.strftime("%Y-%m") == mes_sel)]
                if not lin.empty and pd.notna(lin.get("servicos")) and lin.get("servicos"):
                    n_ = rconf[pd.to_datetime(rconf["data_2"]).dt.date.isin(dias_base)] if dias_base else rconf
                    lin["retrabalho"] = len(n_) / lin["servicos"] * 100
            au = auds_e[auds_e["id_oficina"].astype(str).isin(ids_) &
                        (pd.to_datetime(auds_e["data_execucao"]).dt.strftime("%Y-%m") == mes_sel)] if not auds_e.empty else pd.DataFrame()
            nc_ = ncs_all[ncs_all["id_oficina"].astype(str).isin(ids_) & (ncs_all["data"].dt.strftime("%Y-%m") == mes_sel)
                          & ncs_all["status"].isin(["Procedente", "Improcedente"])] if not ncs_all.empty else pd.DataFrame()
            pos = (rank.index(of_) + 1, len(rank)) if of_ in rank else None
            arquivos[of_] = ext.gerar(of_, mes_sel, lin, dfe[dfe["oficina"] == of_], metas, pos, rconf, au, nc_)
        st.session_state["extratos"] = (mes_sel, arquivos)
    if "extratos" in st.session_state and st.session_state["extratos"][0] == mes_sel:
        _, arqs = st.session_state["extratos"]
        nome_arq = lambda o: f"Extrato_{compacto(o)[:30]}_{mes_sel}.pdf"
        if len(arqs) == 1:
            o_, b_ = next(iter(arqs.items()))
            st.download_button(f"⬇️ Baixar extrato — {o_}", b_, nome_arq(o_), mime="application/pdf")
        else:
            import zipfile
            zbuf = io.BytesIO()
            with zipfile.ZipFile(zbuf, "w") as z:
                for o_, b_ in arqs.items():
                    z.writestr(nome_arq(o_), b_)
            st.download_button(f"⬇️ Baixar {len(arqs)} extratos (.zip)", zbuf.getvalue(), f"Extratos_{mes_sel}.zip", mime="application/zip")

    with st.expander(f"✏️ Lançamentos manuais de {fmt_mes(mes_sel)} (reclamações / não conformidades e no show)"):
        st.caption("Informações que não vêm do sistema. Preencha a quantidade do mês por oficina e salve. As não "
                   "conformidades registradas em 📝 Não conformidade (procedentes) já entram sozinhas e têm prioridade.")
        ids_unicos = ofs_reg.drop_duplicates("oficina")[["id", "oficina"]].astype(str)
        atual = manuais[manuais["mes"] == mes_sel] if not manuais.empty else manuais
        grade = ids_unicos.rename(columns={"id": "id_oficina"}).merge(
            atual[["id_oficina", "nao_conf", "no_show", "observacao"]].astype({"id_oficina": str}) if not atual.empty
            else pd.DataFrame(columns=["id_oficina", "nao_conf", "no_show", "observacao"]), on="id_oficina", how="left")
        for c_ in ("nao_conf", "no_show"):
            grade[c_] = pd.to_numeric(grade[c_], errors="coerce")
        ed = st.data_editor(grade, hide_index=True, width="stretch", disabled=["oficina"], key=f"man_{mes_sel}",
                            column_config={"id_oficina": None, "oficina": "Oficina",
                                           "nao_conf": st.column_config.NumberColumn("Não conformidades / reclamações", min_value=0, step=1),
                                           "no_show": st.column_config.NumberColumn("No show", min_value=0, step=1),
                                           "observacao": "Observação"})
        if st.button("Salvar lançamentos do mês", type="primary"):
            banco.salvar_manuais(ed.drop(columns=["oficina"]).assign(mes=mes_sel))
            st.success("Lançamentos salvos.")
            st.rerun()


# ---------------------------------------------------------------- capacidade
elif area == "📈 Capacidade":
    st.title("Capacidade × agenda")
    cfg_cap = {**cap.PADRAO, **banco.ler_config("capacidade", {})}
    ofs_reg = oficinas[oficinas["uf_base"].fillna("").str.upper().isin([u.upper() for u in ufs_regiao])] if ufs_regiao else oficinas
    tec = cap.tecnicos_por_oficina(ativ, ofs_reg)
    d = cap.diario(ativ, base, tec, cfg_cap) if not ativ.empty else pd.DataFrame()
    if d.empty:
        sem_dados()
        st.stop()
    hoje = date.today()
    st.caption(f"Capacidade = nº de técnicos × {cfg_cap['os_por_tecnico_dia']} atendimentos por técnico por dia, nos dias de "
               "trabalho. Agenda = OS do planejado vigente de cada dia. Realizado = executados + encaixes + improdutivas "
               "(o técnico foi até o local). Ajuste os parâmetros em ⚙️ Configurações e o nº de técnicos no cadastro.")
    c1, c2, c3 = st.columns([1.4, 1.6, 1])
    dmin, dmax = min(d["data"]), max(d["data"])
    per = c1.date_input("Período", (max(dmin, hoje - timedelta(days=30)), dmax), min_value=dmin, max_value=dmax,
                        format="DD/MM/YYYY")
    ini, fim = per if len(per) == 2 else (per[0], per[0])
    sel_of = c2.multiselect("Oficina", sorted(tec["oficina"].dropna().unique()), placeholder="Região toda", key="cap_of")
    gran = c3.radio("Agrupar por", ["Dia", "Semana", "Mês"], horizontal=True)
    v = d[(d["data"] >= ini) & (d["data"] <= fim)]
    if sel_of:
        v = v[v["oficina"].isin(sel_of)]
    dias_res = set(base["data_operacional"]) if not base.empty else set()
    passado = v[v["data"].isin(dias_res)]          # só dias com resultado importado
    futuro = v[(v["data"] >= hoje) & ~v["data"].isin(dias_res)]

    def ocup(num, den):
        return num / den * 100 if den else None

    cap_p, real_p = passado["capacidade"].sum(), passado["realizado"].sum()
    dias_trab = passado.loc[passado["dia_trabalho"], "data"].nunique()
    m = st.columns(4)
    m[0].metric("Capacidade por dia útil", int(v.groupby("data")["capacidade"].sum().max() or 0),
                help="Soma da capacidade das oficinas selecionadas em um dia de trabalho.")
    m[1].metric("Média realizada por dia útil", f"{real_p / dias_trab:.1f}".replace(".", ",") if dias_trab else "—")
    o = ocup(real_p, cap_p)
    m[2].metric("Ocupação no período", "—" if o is None else f"{o:.0f}%", help="Realizado ÷ capacidade, dias já passados.")
    cap_f, ag_f = futuro["capacidade"].sum(), futuro["agenda"].sum()
    of_ = ocup(ag_f, cap_f)
    m[3].metric("Agenda dos próximos dias", "—" if of_ is None else f"{of_:.0f}% da capacidade",
                f"{int(ag_f)} OS agendadas" if len(futuro) else None, delta_color="off",
                help="OS já no planejado de hoje em diante ÷ capacidade desses dias.")
    if o is not None:
        st.markdown(f"Situação no período: **{cap.status_ocupacao(o, cfg_cap)}**")

    # gráfico
    g = v.groupby("data")[["agenda", "realizado", "capacidade"]].sum().reset_index()
    g["data"] = pd.to_datetime(g["data"])
    if gran == "Semana":
        g["periodo"] = g["data"].dt.to_period("W-SUN").map(lambda p: p.start_time)
    elif gran == "Mês":
        g["periodo"] = g["data"].dt.to_period("M").map(lambda p: p.start_time)
    else:
        g["periodo"] = g["data"]
    g = g.groupby("periodo")[["agenda", "realizado", "capacidade"]].sum().reset_index()
    if gran == "Dia":
        g["realizado"] = g.apply(lambda r: r["realizado"] if r["periodo"].date() in dias_res else None, axis=1)
    g["rotulo"] = g["periodo"].dt.strftime({"Dia": "%a %d/%m", "Semana": "sem %d/%m", "Mês": "%m/%Y"}[gran])
    ordem = g["rotulo"].tolist()
    longo = g.melt(id_vars=["rotulo"], value_vars=["agenda", "realizado"], var_name="serie", value_name="qtd").dropna()
    longo["serie"] = longo["serie"].map({"agenda": "Agendado", "realizado": "Realizado"})
    barras_ = alt.Chart(longo).mark_bar().encode(
        x=alt.X("rotulo:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=-40)),
        xOffset="serie:N", y=alt.Y("qtd:Q", title="Atendimentos"),
        color=alt.Color("serie:N", scale=alt.Scale(domain=["Agendado", "Realizado"], range=["#9DBDBA", COR]),
                        legend=alt.Legend(title=None, orient="bottom")),
        tooltip=[alt.Tooltip("rotulo:N", title="Período"), alt.Tooltip("serie:N", title=""), alt.Tooltip("qtd:Q", title="OS")])
    linha = alt.Chart(g).mark_line(color="#D64545", strokeDash=[6, 4], point=True).encode(
        x=alt.X("rotulo:N", sort=ordem), y="capacidade:Q",
        tooltip=[alt.Tooltip("rotulo:N", title="Período"), alt.Tooltip("capacidade:Q", title="Capacidade")])
    st.altair_chart((barras_ + linha).properties(height=320), width="stretch")
    st.caption("Barras: agendado e realizado. Linha vermelha tracejada: capacidade. Dias sem resultado importado "
               "(como os próximos dias) mostram só a agenda.")

    # tabela por oficina
    st.subheader("Por oficina")
    t = tec[tec["id_oficina"].isin(v["id_oficina"].unique())][["id_oficina", "oficina", "n_tecnicos", "origem_tecnicos"]].copy()
    pp = passado.groupby("id_oficina").agg(cap=("capacidade", "sum"), real=("realizado", "sum"),
                                           dias=("dia_trabalho", "sum")).reset_index()
    ff = futuro.groupby("id_oficina").agg(cap_f=("capacidade", "sum"), ag_f=("agenda", "sum")).reset_index()
    t = t.merge(pp, on="id_oficina", how="left").merge(ff, on="id_oficina", how="left").fillna(0)
    t["Capacidade/dia"] = t["n_tecnicos"] * cfg_cap["os_por_tecnico_dia"]
    t["Média realizada/dia útil"] = (t["real"] / t["dias"].replace(0, float("nan"))).round(1)
    t["Ocupação %"] = (t["real"] / t["cap"].replace(0, float("nan")) * 100).round(0)
    t["Agenda próximos dias %"] = (t["ag_f"] / t["cap_f"].replace(0, float("nan")) * 100).round(0)
    t["Situação"] = t["Ocupação %"].map(lambda x: cap.status_ocupacao(x, cfg_cap))
    t = t.rename(columns={"oficina": "Oficina", "n_tecnicos": "Técnicos", "origem_tecnicos": "Nº de técnicos vem do",
                          "real": "Realizado", "ag_f": "Agendado próximos dias"})
    st.dataframe(t[["Oficina", "Técnicos", "Nº de técnicos vem do", "Capacidade/dia", "Média realizada/dia útil",
                    "Realizado", "Ocupação %", "Situação", "Agendado próximos dias", "Agenda próximos dias %"]]
                 .sort_values("Ocupação %", ascending=False),
                 hide_index=True, width="stretch",
                 column_config={"Ocupação %": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=150),
                                "Agenda próximos dias %": st.column_config.NumberColumn(format="%d%%")})
    if (tec["origem_tecnicos"] == "Estimado pelos dados").any():
        st.info("Algumas oficinas estão com o nº de técnicos estimado pelos técnicos que aparecem nas OS dos últimos "
                "60 dias. Para ficar exato, preencha a coluna **Nº de técnicos** em 📥 Dados → Oficinas.")


# ---------------------------------------------------------------- improdutividade
elif area == "🔧 Improdutividade":
    st.title("Improdutividade")
    if base.empty:
        sem_dados()
        st.stop()
    st.caption(contexto)
    imp = filtrado[filtrado["classificacao"] == regras.IMPRODUTIVA].copy()
    if imp.empty:
        st.success("Nenhuma improdutiva no recorte selecionado.")
        st.stop()
    ind = regras.indicadores(filtrado)
    c = st.columns(5)
    c[0].metric("Improdutivas", len(imp), help=AJUDA["Improdutivas"])
    c[1].metric("Da agenda", ind["Improdutivas da agenda"], help=AJUDA["Improdutivas da agenda"])
    c[2].metric("De encaixe", ind["Improdutivas de encaixe"], help=AJUDA["Improdutivas de encaixe"])
    c[3].metric("Improdutividade", pct(ind["Improdutividade"]), help=AJUDA["Improdutividade"])
    c[4].metric("Improdutividade dos encaixes", pct(ind["Improdutividade dos encaixes"]),
                help=AJUDA["Improdutividade dos encaixes"])
    so = st.radio("Mostrar", ["Todas", "Só da agenda", "Só de encaixe"], horizontal=True)
    if so != "Todas":
        imp = imp[imp["origem"] == ("Agendada" if so == "Só da agenda" else "Encaixe")]
    c1, c2 = st.columns(2)
    with c1:
        barras(imp.assign(razao=imp["razao_improdutiva"].fillna("Sem razão informada")), "razao", "Por razão")
    with c2:
        barras(imp, "oficina", "Por oficina")
    if not imp.empty and imp["data_operacional"].nunique() > 1:
        ev = imp.groupby(["semana_ini", "origem"]).size().rename("qtd").reset_index()
        ev["Semana"] = pd.to_datetime(ev["semana_ini"]).dt.strftime("sem %d/%m")
        st.markdown("**Por semana**")
        st.altair_chart(alt.Chart(ev).mark_bar().encode(
            x=alt.X("Semana:N", sort=sorted(ev["Semana"].unique(), key=lambda s: s), title=None),
            y=alt.Y("qtd:Q", title="Improdutivas"),
            color=alt.Color("origem:N", scale=alt.Scale(domain=["Agendada", "Encaixe"], range=[COR, "#E8B73A"]),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["Semana", "origem", "qtd"]).properties(height=240), width="stretch")
    st.subheader("OS improdutivas")
    lista = imp[COLS_OS].rename(columns=NOMES_OS)
    st.dataframe(lista, hide_index=True, width="stretch")
    st.download_button("⬇️ Baixar em Excel", para_excel(lista), "improdutivas.xlsx")


# ---------------------------------------------------------------- retrabalho
elif area == "🔁 Retrabalho":
    st.title("Retrabalho")
    if casos_rt.empty:
        st.info("Importe a base de retrabalho em **📥 Dados → Retrabalho**.")
        st.stop()
    c1, c2, c3 = st.columns(3)
    meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro",
             "outubro", "novembro", "dezembro"]

    def chave_comp(s):
        mes, _, ano = str(s).partition("/")
        mes = rt.sem_acento(mes)
        return (ano, meses.index(mes) if mes in meses else 0)

    comps = sorted(casos_rt["competencia"].dropna().unique(), key=chave_comp)
    sel_comp = c1.multiselect("Competência", comps, default=comps[-1:], placeholder="Todas")
    sel_of = c2.multiselect("Oficina", sorted(casos_rt["oficina"].dropna().unique()), placeholder="Todas")
    sel_crit = c3.multiselect("Criticidade", ["🔴 0–15 dias", "🟡 16–59 dias", "🔵 60–90 dias"], placeholder="Todas")
    cr = casos_rt
    if sel_comp:
        cr = cr[cr["competencia"].isin(sel_comp)]
    if sel_of:
        cr = cr[cr["oficina"].isin(sel_of)]
    if sel_crit:
        cr = cr[cr["criticidade"].isin(sel_crit)]

    m = st.columns(4)
    m[0].metric("Casos", len(cr))
    m[1].metric("Retrabalhos", int((cr["status"] == "Retrabalho").sum()))
    m[2].metric("Não é retrabalho", int((cr["status"] == "Não é retrabalho").sum()))
    m[3].metric("Pendentes de análise", int((cr["status"] == "Pendente").sum()))

    aba = st.tabs(["📊 Visão geral", "📝 Análise", "Por oficina", "Motivos", "Todos os casos"])
    with aba[0]:
        visao_geral_retrabalho(cr)
    with aba[1]:
        ver = st.radio("Mostrar", ["Pendentes", "Decididos automaticamente", "Todos"], horizontal=True)
        lista = cr if ver == "Todos" else (cr[cr["status"] == "Pendente"] if ver == "Pendentes"
                                          else cr[(cr["origem"] == "Automática") & (cr["status"] != "Pendente")])
        lista = lista.assign(_s=~lista["motivo_auto"].str.startswith("Sinal"), _d=lista["dias"]).sort_values(["_s", "_d"])
        st.caption("Regra da empresa: retorno em até 90 dias = retrabalho. Os casos com sinal para revisar aparecem "
                   "primeiro. Marque a decisão final, a causa e uma observação, e clique em Salvar. A decisão manual vale "
                   "por cima da automática; para devolver um caso à regra, apague a decisão final.")
        causas = rt_causas
        ed = lista[["id_caso", "criticidade", "competencia", "oficina", "placa", "os_1", "data_1", "tipo_1",
                    "diag_jira_1", "diag_ofs_1", "os_2", "data_2", "tipo_2", "diag_jira_2", "diag_ofs_2", "dias",
                    "tecnico_2", "obs_tecnico_ofs", "decisao_auto", "motivo_auto", "sinistro_conf", "decisao_final", "causa",
                    "observacao"]].copy()
        ed["sinistro_conf"] = ed["sinistro_conf"].eq("Sim")
        ed["decisao_final"] = ed["decisao_final"].fillna("")
        ed["causa"] = ed["causa"].fillna("")
        ed["observacao"] = ed["observacao"].fillna("")
        fixas = [c for c in ed.columns if c not in ("decisao_final", "causa", "observacao", "sinistro_conf")]
        editado = st.data_editor(
            ed, hide_index=True, width="stretch", disabled=fixas, key="editor_rt",
            column_config={
                "id_caso": None,
                "criticidade": "Criticidade", "competencia": "Competência", "oficina": "Oficina", "placa": "Placa",
                "os_1": "OS 1ª visita", "data_1": st.column_config.DateColumn("Data 1ª", format="DD/MM/YYYY"),
                "tipo_1": "Tipo 1ª", "diag_jira_1": "Diag. Jira 1ª", "diag_ofs_1": "Diag. OFS 1ª",
                "os_2": "OS retorno", "data_2": st.column_config.DateColumn("Data retorno", format="DD/MM/YYYY"),
                "tipo_2": "Tipo retorno", "diag_jira_2": "Diag. Jira retorno", "diag_ofs_2": "Diag. OFS retorno",
                "dias": "Dias", "tecnico_2": "Técnico", "obs_tecnico_ofs": "Obs. do técnico (sistema)",
                "decisao_auto": "Decisão automática",
                "motivo_auto": "Motivo automático",
                "sinistro_conf": st.column_config.CheckboxColumn("⚠️ Sinistro identificado",
                    help="Marque quando a análise (fotos, observação) mostrar sinistro/mau uso. A OS de retorno passa a contar "
                         "como sinistro apontado no indicador. Não decide o retrabalho: a decisão final continua sendo sua."),
                "decisao_final": st.column_config.SelectboxColumn("✏️ Decisão final",
                                                                  options=["", "Retrabalho", "Não é retrabalho"]),
                "causa": st.column_config.SelectboxColumn("✏️ Causa", options=[""] + causas),
                "observacao": st.column_config.TextColumn("✏️ Observação"),
            })
        if st.button("💾 Salvar análise", type="primary"):
            cols_ed = ["decisao_final", "causa", "observacao", "sinistro_conf"]
            mud = editado[["id_caso"] + cols_ed]
            orig = ed.set_index("id_caso")[cols_ed]
            mud = mud[mud.apply(lambda r: tuple(r[1:]) != tuple(orig.loc[r["id_caso"]]), axis=1)].copy()
            if mud.empty:
                st.info("Nenhuma alteração para salvar.")
            else:
                mud["sinistro_conf"] = mud["sinistro_conf"].map(lambda v: "Sim" if v else None)
                banco.salvar_decisoes_retrabalho(mud.replace("", None))
                st.success(f"{len(mud)} caso(s) salvo(s).")
                st.rerun()

    with aba[2]:
        t = cr.groupby("oficina").agg(
            Casos=("id_caso", "count"),
            Retrabalhos=("status", lambda s: (s == "Retrabalho").sum()),
            Nao=("status", lambda s: (s == "Não é retrabalho").sum()),
            Pendentes=("status", lambda s: (s == "Pendente").sum()),
            Vermelhos=("criticidade", lambda s: s.str.startswith("🔴").sum()),
        ).reset_index().sort_values("Retrabalhos", ascending=False)
        t["% confirmado"] = (t["Retrabalhos"] / (t["Casos"] - t["Pendentes"]).astype(float).replace(0, float("nan")) * 100).round(1)
        st.dataframe(t.rename(columns={"oficina": "Oficina", "Nao": "Não é retrabalho",
                                       "Vermelhos": "🔴 Retornos em até 15 dias"}),
                     hide_index=True, width="stretch",
                     column_config={"% confirmado": st.column_config.NumberColumn(format="%.1f%%",
                                    help="Retrabalhos ÷ casos já decididos")})
        por_mes = casos_rt[casos_rt["status"] == "Retrabalho"].groupby("competencia").size()
        por_mes = por_mes.reindex([c for c in comps if c in por_mes.index])
        if len(por_mes):
            st.caption("Retrabalhos confirmados por competência (todas as oficinas da região)")
            st.bar_chart(por_mes.rename("Retrabalhos"))

    with aba[3]:
        st.caption("Por que os casos saíram ou ficaram, segundo as regras automáticas e a análise manual.")
        mot = cr.assign(motivo=cr["motivo_auto"].str.replace(r"\s*[\(:].*$", "", regex=True))
        st.dataframe(mot.groupby(["decisao_auto", "motivo"]).size().rename("Casos").reset_index()
                     .rename(columns={"decisao_auto": "Decisão automática", "motivo": "Regra"}),
                     hide_index=True, width="stretch")
        manuais = cr[cr["origem"] == "Manual"]
        if len(manuais):
            st.caption("Causas registradas na análise manual")
            st.dataframe(manuais.groupby(["status", "causa"], dropna=False).size().rename("Casos").reset_index(),
                         hide_index=True, width="stretch")

    with aba[4]:
        cols = ["competencia", "criticidade", "oficina", "placa", "os_1", "data_1", "tipo_1", "diag_jira_1",
                "os_2", "data_2", "tipo_2", "diag_jira_2", "diag_ofs_2", "obs_tecnico_ofs", "dias", "tecnico_2", "valor_servico",
                "status", "origem", "motivo_auto", "sinistro_conf", "causa", "observacao", "decidido_em"]
        nomes = {"competencia": "Competência", "criticidade": "Criticidade", "oficina": "Oficina", "placa": "Placa",
                 "os_1": "OS 1ª visita", "data_1": "Data 1ª", "tipo_1": "Tipo 1ª", "diag_jira_1": "Diag. Jira 1ª",
                 "obs_tecnico_ofs": "Obs. do técnico (sistema)", "os_2": "OS retorno", "data_2": "Data retorno", "tipo_2": "Tipo retorno",
                 "diag_jira_2": "Diag. Jira retorno", "diag_ofs_2": "Diag. OFS retorno", "dias": "Dias",
                 "tecnico_2": "Técnico", "valor_servico": "R$ serviço", "status": "Status",
                 "origem": "Decisão", "motivo_auto": "Motivo automático", "sinistro_conf": "Sinistro identificado", "causa": "Causa",
                 "observacao": "Observação", "decidido_em": "Decidido em"}
        tab = cr[cols].rename(columns=nomes)
        st.dataframe(tab, hide_index=True, width="stretch")
        st.download_button("⬇️ Baixar relatório em Excel", para_excel(tab), "retrabalho.xlsx")


# ---------------------------------------------------------------- auditoria
elif area == "✅ Auditoria":
    st.title("Auditoria")
    itens_cfg = banco.ler_config("itens_auditoria", aud.ITENS_PADRAO)
    meta = float(banco.ler_config("meta_aprovacao", 80))
    auditor_padrao = banco.ler_config("auditor_padrao", "")
    auds = banco.carregar_auditorias()
    ids_regiao = set(oficinas.loc[oficinas["uf_base"].fillna("").str.upper().isin([u.upper() for u in ufs_regiao]), "id"].astype(str)) \
        if ufs_regiao else set(oficinas["id"].astype(str))
    if not auds.empty:
        auds = auds[auds["id_oficina"].astype(str).isin(ids_regiao)]
    ja_auditadas = set(auds["os"]) if not auds.empty else set()

    if "msg_aud" in st.session_state:
        st.success(st.session_state.pop("msg_aud"))
    aba = st.tabs(["📝 Nova auditoria", "📊 Visão geral", "Auditorias realizadas"])

    with aba[0]:
        exe = pd.DataFrame()
        if not ativ.empty:
            exe = ativ[(ativ["tipo_base"] == "resultado") & (ativ["status"] == "concluído")]
            exe = exe.sort_values("data_ref").drop_duplicates("os", keep="last")
        if exe.empty:
            st.info("Ainda não há OS executadas no painel. Importe os resultados diários em 📥 Dados → Resultado.")
        else:
            dmin, dmax = min(exe["data"]), max(exe["data"])
            c1, c2, c3, c4 = st.columns([1.3, 1.4, 1.4, 1.2])
            per = c1.date_input("Período de execução", (max(dmin, dmax - timedelta(days=30)), dmax),
                                min_value=dmin, max_value=dmax, format="DD/MM/YYYY")
            ini, fim = per if len(per) == 2 else (per[0], per[0])
            exe = exe[(exe["data"] >= ini) & (exe["data"] <= fim)]
            of_sel = c2.selectbox("Oficina", ["Todas"] + sorted(exe["oficina"].dropna().unique()))
            if of_sel != "Todas":
                exe = exe[exe["oficina"] == of_sel]
            tec_sel = c3.selectbox("Técnico", ["Todos"] + sorted(exe["tecnico"].dropna().unique()))
            if tec_sel != "Todos":
                exe = exe[exe["tecnico"] == tec_sel]
            fam_sel = c4.multiselect("Serviço", regras.FAMILIAS, placeholder="Todos")
            if fam_sel:
                exe = exe[exe["familia"].isin(fam_sel)]
            exe = exe.assign(auditada=exe["os"].isin(ja_auditadas))

            with st.expander(f"{len(exe)} OS executadas no recorte · {int(exe['auditada'].sum())} já auditadas · resumo por técnico"):
                res_tec = exe.groupby(["oficina", "tecnico"]).agg(Executadas=("os", "count"),
                                                                  Auditadas=("auditada", "sum")).reset_index()
                st.dataframe(res_tec.rename(columns={"oficina": "Oficina", "tecnico": "Técnico"}),
                             hide_index=True, width="stretch")

            pendentes = exe[~exe["auditada"]]
            b1, b2 = st.columns([1, 3])
            if b1.button("🎲 Sortear uma OS não auditada", disabled=pendentes.empty, width="stretch"):
                st.session_state["os_aud"] = random.choice(pendentes["os"].tolist())
            so_pend = b2.toggle("Mostrar só as OS ainda não auditadas", value=True)
            lista = (pendentes if so_pend else exe).sort_values(["data", "oficina", "tecnico"])
            if lista.empty:
                st.success("Todas as OS do recorte já foram auditadas.")
            else:
                rot = {r.os: f"{'✅ ' if r.auditada else ''}OS {r.os} · {r.data:%d/%m} · {r.oficina} · {r.tecnico} · {r.tipo_atividade}"
                       for r in lista.itertuples()}
                opcoes = list(rot)
                if st.session_state.get("os_aud") not in opcoes:
                    st.session_state["os_aud"] = opcoes[0]
                os_sel = st.selectbox("OS para auditar", opcoes, format_func=lambda o: rot[o], key="os_aud")
                r = exe[exe["os"] == os_sel].iloc[0]
                anterior = auds[auds["os"] == os_sel].iloc[0] if os_sel in ja_auditadas else None

                with st.container(border=True):
                    k = st.columns(4)
                    k[0].markdown(f"**OS**  \n{r['os']}")
                    k[1].markdown(f"**Execução**  \n{r['data']:%d/%m/%Y}")
                    k[2].markdown(f"**Oficina**  \n{r['oficina']}")
                    k[3].markdown(f"**Técnico**  \n{r['tecnico']}")
                    k = st.columns(4)
                    k[0].markdown(f"**Serviço**  \n{r['tipo_atividade']}")
                    k[1].markdown(f"**Placa**  \n{r.get('placa') or '—'}")
                    k[2].markdown(f"**Ticket**  \n{r.get('ticket') or '—'}")
                    k[3].markdown(f"**Família**  \n{r['familia']}")
                    obs = " | ".join(str(r.get(c)) for c in ("obs_tecnico", "obs_os_tecnico", "obs_vistoria")
                                     if pd.notna(r.get(c)) and str(r.get(c)).strip())
                    if obs:
                        st.caption(f"Observação do técnico: {obs}")
                sin_auto = indica_sinistro(r)
                if sin_auto:
                    st.warning(f"O sistema indica sinistro nesta OS ({sin_auto}). A resposta já vem marcada como Sim.")
                if anterior is not None:
                    st.info(f"Esta OS já foi auditada em {anterior['data_auditoria']:%d/%m/%Y} "
                            f"({anterior['resultado']}). Salvar de novo substitui a auditoria anterior.")

                def idx(valor, opcoes_):
                    return opcoes_.index(valor) if valor in opcoes_ else None

                with st.form(f"form_aud_{os_sel}"):
                    f1, f2, f3 = st.columns(3)
                    tipo = f1.radio("Tipo de auditoria", ["Remota", "Presencial"], horizontal=True,
                                    index=idx(anterior["tipo_auditoria"], ["Remota", "Presencial"]) if anterior is not None else 0)
                    data_aud = f2.date_input("Data da auditoria", anterior["data_auditoria"].date()
                                             if anterior is not None else date.today(), format="DD/MM/YYYY")
                    auditor = f3.text_input("Auditor", anterior["auditor"] if anterior is not None else auditor_padrao)
                    s1, s2 = st.columns(2)
                    pre_sin = anterior["sinistro"] if anterior is not None else ("Sim" if sin_auto else None)
                    sinistro = s1.radio("Serviço possui sinistro?", ["Sim", "Não"], horizontal=True,
                                        index=idx(pre_sin, ["Sim", "Não"]))
                    apontado = s2.radio("Se sim, foi apontado corretamente pelo técnico, com fotos?",
                                        ["Sim", "Não", "Não se aplica"], horizontal=True,
                                        index=idx(anterior["sinistro_apontado"], ["Sim", "Não", "Não se aplica"])
                                        if anterior is not None else None)
                    st.markdown("**Itens verificados**")
                    resp = {}
                    for i, item in enumerate(itens_cfg):
                        pre = (anterior["itens"] or {}).get(item) if anterior is not None else None
                        resp[item] = st.radio(item, aud.OPCOES, horizontal=True, index=idx(pre, aud.OPCOES),
                                              key=f"it_{os_sel}_{i}")
                    obs_aud = st.text_area("Observação da auditoria",
                                           anterior["observacao"] if anterior is not None and pd.notna(anterior["observacao"]) else "")
                    enviar = st.form_submit_button("💾 Salvar auditoria", type="primary")
                if enviar:
                    faltando = [i for i, v in resp.items() if v is None]
                    if sinistro is None or faltando:
                        st.error("Responda o sinistro e todos os itens (Aprovado, Reprovado ou Não se aplica)."
                                 + (f" Faltam {len(faltando)} item(ns)." if faltando else ""))
                    else:
                        res = aud.resumo_itens(resp)
                        banco.salvar_auditoria({
                            "os": str(r["os"]), "data_execucao": str(r["data"]), "oficina": r["oficina"],
                            "id_oficina": str(r["id_oficina"]), "tecnico": r["tecnico"],
                            "tipo_servico": r["tipo_atividade"], "familia": r["familia"],
                            "placa": r.get("placa"), "ticket": r.get("ticket"),
                            "tipo_auditoria": tipo, "data_auditoria": str(data_aud), "auditor": auditor,
                            "sinistro": sinistro, "sinistro_apontado": apontado,
                            "sinistro_sistema": sin_auto or None, "itens": resp, "observacao": obs_aud or None, **res})
                        st.session_state.pop("os_aud", None)
                        st.session_state["msg_aud"] = (f"Auditoria salva: OS {r['os']} {res['resultado'].lower()} "
                                   f"({res['aprovados']} aprovados, {res['reprovados']} reprovados).")
                        st.rerun()

    with aba[1]:
        if auds.empty:
            st.info("Nenhuma auditoria registrada ainda. Faça a primeira na aba 📝 Nova auditoria.")
        else:
            meses_aud = sorted(auds["data_auditoria"].dt.strftime("%Y-%m").dropna().unique())
            g1, g2, g3 = st.columns(3)
            sel_m = g1.multiselect("Mês da auditoria", meses_aud, placeholder="Todos",
                                   format_func=lambda m: f"{m[5:]}/{m[:4]}")
            sel_o = g2.multiselect("Oficina", sorted(auds["oficina"].unique()), placeholder="Todas", key="aud_of")
            sel_t = g3.multiselect("Tipo", ["Remota", "Presencial"], placeholder="Remota e presencial")
            v = auds
            if sel_m:
                v = v[v["data_auditoria"].dt.strftime("%Y-%m").isin(sel_m)]
            if sel_o:
                v = v[v["oficina"].isin(sel_o)]
            if sel_t:
                v = v[v["tipo_auditoria"].isin(sel_t)]
            if v.empty:
                st.info("Nenhuma auditoria no recorte.")
            else:
                ap = (v["resultado"] == "Aprovada").mean() * 100
                m = st.columns(4)
                m[0].metric("OS auditadas", len(v))
                m[1].metric("Aprovação", f"{ap:.1f}%".replace(".", ","), f"meta {meta:.0f}%",
                            delta_color="normal" if ap >= meta else "inverse")
                m[2].metric("Conformidade média dos itens", f"{v['conformidade'].mean():.1f}%".replace(".", ","),
                            help="Itens aprovados ÷ itens avaliados (sem contar os Não se aplica)")
                m[3].metric("Sinistros não apontados pelo técnico", int((v["sinistro_apontado"] == "Não").sum()))
                c1, c2 = st.columns(2)
                with c1:
                    ranking_taxa(aud.taxa_por(v, "oficina"), "oficina", "Aprovação por oficina", meta)
                with c2:
                    tt = aud.taxa_por(v.assign(tec=v["tecnico"] + " (" + v["oficina"] + ")"), "tec")
                    ranking_taxa(tt, "tec", "Aprovação por técnico", meta)
                c3, c4 = st.columns(2)
                with c3:
                    li = aud.itens_longos(v)
                    barras(li[li["res"] == "Reprovado"], "item", "Itens mais reprovados")
                with c4:
                    ev = v.assign(mes=v["data_auditoria"].dt.strftime("%Y-%m")).groupby("mes").agg(
                        aprov=("resultado", lambda s: (s == "Aprovada").mean() * 100), n=("os", "count")).reset_index()
                    st.markdown("**Aprovação mês a mês**")
                    linha = alt.Chart(ev).mark_line(point=True, color=COR).encode(
                        x=alt.X("mes:N", title=None), y=alt.Y("aprov:Q", title="% aprovação", scale=alt.Scale(domain=[0, 100])),
                        tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("aprov:Q", title="% aprovação", format=".1f"),
                                 alt.Tooltip("n:Q", title="OS auditadas")])
                    regra = alt.Chart(pd.DataFrame({"m": [meta]})).mark_rule(strokeDash=[4, 4], color="#555").encode(y="m:Q")
                    st.altair_chart((linha + regra).properties(height=260), width="stretch")
                st.caption("Lembrete: a auditoria é feita pelas fotos. Uma reprovação pode ser execução fora do padrão "
                           "ou foto insuficiente; nos dois casos é ponto de melhoria para a oficina.")

    with aba[2]:
        if auds.empty:
            st.info("Nenhuma auditoria registrada ainda.")
        else:
            tab = auds.sort_values("data_auditoria", ascending=False)
            itens_df = pd.DataFrame(tab["itens"].tolist(), index=tab.index)
            cols = ["data_auditoria", "tipo_auditoria", "auditor", "os", "data_execucao", "oficina", "tecnico",
                    "tipo_servico", "resultado", "conformidade", "aprovados", "reprovados", "nao_aplica",
                    "sinistro", "sinistro_apontado", "observacao"]
            saida = pd.concat([tab[cols], itens_df], axis=1).rename(columns={
                "data_auditoria": "Data auditoria", "tipo_auditoria": "Tipo", "auditor": "Auditor", "os": "OS",
                "data_execucao": "Execução", "oficina": "Oficina", "tecnico": "Técnico", "tipo_servico": "Serviço",
                "resultado": "Resultado", "conformidade": "Conformidade %", "aprovados": "Itens aprovados",
                "reprovados": "Itens reprovados", "nao_aplica": "Não se aplica", "sinistro": "Sinistro",
                "sinistro_apontado": "Sinistro apontado", "observacao": "Observação"})
            st.dataframe(saida, hide_index=True, width="stretch",
                         column_config={"Data auditoria": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                        "Execução": st.column_config.DateColumn(format="DD/MM/YYYY")})
            st.download_button("⬇️ Baixar auditorias em Excel", para_excel(saida), "auditorias.xlsx")
            alvo = st.selectbox("Excluir uma auditoria", ["—"] + tab["os"].tolist())
            if alvo != "—" and st.button("Excluir auditoria selecionada"):
                banco.excluir_auditoria(alvo)
                st.rerun()


# ---------------------------------------------------------------- financeiro
elif area == "💰 Financeiro":
    st.title("Eficiência financeira")
    st.caption("🔒 Área interna: não aparece na visão das oficinas.")
    fz = na_regiao(banco.carregar_financeiro())
    if fz.empty:
        st.info("Importe a planilha de pagamento em **📥 Dados → Financeiro**.")
        st.stop()
    fz["oficina"] = fz["oficina_cad"].fillna(fz["oficina"])
    # contrato por oficina (vale para todos os IDs dela: basta uma linha do cadastro marcada como preço fixo)
    _fx = oficinas[oficinas["contrato"].fillna("").str.strip().str.lower() == "preço fixo"]
    _nome_id = dict(zip(oficinas["id"].astype(str), oficinas["oficina"]))
    _ini_nome = _fx.groupby("oficina")["inicio_fixo"].min().to_dict() if not _fx.empty else {}
    _val_nome = _fx.groupby("oficina")["valor_fixo"].max().to_dict() if not _fx.empty else {}

    def _modelo(i, d_):
        nome = _nome_id.get(str(i))
        if nome not in _ini_nome:
            return "Tabela"
        ini = _ini_nome[nome]
        return "Preço fixo" if (ini is None or pd.isna(ini) or d_ >= ini) else "Tabela"
    fz["modelo"] = [_modelo(i, d_) for i, d_ in zip(fz["id_oficina"], fz["data"])]
    if _ini_nome:
        st.caption("Preço fixo no cadastro: " + "; ".join(
            f"**{n}** (R$ {_val_nome.get(n) or 0:.0f}" + (f", desde {ini:%d/%m/%Y}" if ini is not None and pd.notna(ini) else ", sem data de início")
            + ")" for n, ini in _ini_nome.items()))
    else:
        st.caption("Nenhuma oficina marcada como preço fixo no cadastro (📥 Dados → Oficinas → coluna Contrato).")
    meses_f = sorted(fz["mes"].unique(), reverse=True)
    fmt_m = lambda m: f"{m[5:]}/{m[:4]}"
    c1, c2, c3 = st.columns([1.4, 1.6, 1.2])
    sel_m = c1.multiselect("Mês de execução", meses_f, default=meses_f[:1], format_func=fmt_m, placeholder="Todos")
    sel_o = c2.multiselect("Oficina", sorted(fz["oficina"].unique()), placeholder="Todas", key="fin_of")
    so_conc = c3.toggle("Só OS concluídas", value=False, help="Desligado: inclui improdutivas que geraram pagamento (KM, despesas).")
    sel_mod = c3.multiselect("Contrato", ["Tabela", "Preço fixo"], placeholder="Tabela e preço fixo", key="fin_mod")
    v = fz
    if sel_m:
        v = v[v["mes"].isin(sel_m)]
    if sel_o:
        v = v[v["oficina"].isin(sel_o)]
    if so_conc:
        v = v[v["status_ofs"] == "concluído"]
    if sel_mod:
        v = v[v["modelo"].isin(sel_mod)]
    if v.empty:
        st.info("Nada no recorte.")
        st.stop()
    brl = lambda x: ("R$ " + f"{x:,.0f}".replace(",", ".")) if pd.notna(x) else "—"
    tot = fin.resumo(v.assign(_t="t"), "_t").iloc[0]
    exe_ = v[v["status_ofs"] == "concluído"]
    imp_ = v[v["status_ofs"] == "não concluído"]
    m = st.columns(5)
    m[0].metric("Total pago", brl(tot["Total pago"]))
    m[1].metric("Serviço", brl(tot["Serviço"]), f"{tot['Serviço'] / tot['Total pago'] * 100:.0f}% do total" if tot["Total pago"] else None, delta_color="off")
    m[2].metric("Deslocamento (KM)", brl(tot["Deslocamento (KM)"]), f"{tot['% do custo em deslocamento']:.0f}% do total" if pd.notna(tot["% do custo em deslocamento"]) else None, delta_color="off")
    m[3].metric("Despesas extras", brl(tot["Despesas extras"]), f"{brl(tot['Sem comprovante'])} sem comprovante", delta_color="off")
    m[4].metric("Cobrado de clientes", brl(tot["Cobrado de clientes"]),
                help="Total a Receber: valores repassados ao cliente em casos específicos.")
    st.markdown("**Ordens de serviço**")
    m = st.columns(5)
    m[0].metric("OS pagas/registradas", int(tot["OS"]), help="Todas as OS da planilha no recorte: executadas + improdutivas.")
    m[1].metric("Custo médio (todas as OS)", brl(tot["Custo médio por OS"]),
                help="Total pago ÷ todas as OS registradas, incluindo improdutivas e OS sem pagamento.")
    m[2].metric("OS executadas", len(exe_), help="OS concluídas (sem as improdutivas).")
    m[3].metric("Custo médio por OS executada", brl(exe_["total_pagar"].mean()) if len(exe_) else "—",
                help="Total pago nas OS executadas ÷ nº de OS executadas.")
    m[4].metric("Improdutivas", len(imp_), f"{brl(imp_['total_pagar'].sum())} pagos", delta_color="off",
                help="OS não concluídas e quanto foi pago por elas.")
    st.markdown("**Deslocamento**")
    m = st.columns(5)
    m[0].metric("KM rodado", f"{tot['KM rodado']:,.0f}".replace(",", "."))
    m[1].metric("OS com deslocamento", f"{tot['% com deslocamento']:.0f}%")
    m[2].metric("KM médio (OS com desloc.)", f"{tot['KM médio (OS com desloc.)']:.0f} km" if pd.notna(tot["KM médio (OS com desloc.)"]) else "—")

    aba = st.tabs(["Por oficina", "Por tipo de serviço", "Evolução", "Retrabalho e improdutivas", "Alertas", "OS",
                   "Preço fixo × tabela"])
    with aba[0]:
        r = fin.resumo(v, "oficina").sort_values("Total pago", ascending=False)
        comp = r.melt(id_vars="oficina", value_vars=["Serviço", "Deslocamento (KM)", "Despesas extras"],
                      var_name="Parte", value_name="R$")
        st.altair_chart(alt.Chart(comp).mark_bar().encode(
            y=alt.Y("oficina:N", sort=r["oficina"].tolist(), title=None, axis=alt.Axis(labelLimit=260)),
            x=alt.X("R$:Q", title="R$ pago"),
            color=alt.Color("Parte:N", scale=alt.Scale(domain=["Serviço", "Deslocamento (KM)", "Despesas extras"],
                                                        range=[COR, "#E8B73A", "#D64545"]),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["oficina", "Parte", alt.Tooltip("R$:Q", format=",.0f")]).properties(height=max(160, 34 * len(r))),
            width="stretch")
        money = {c: st.column_config.NumberColumn(format="R$ %.0f") for c in
                 ["Total pago", "Serviço", "Deslocamento (KM)", "Despesas extras", "Sem comprovante",
                  "Cobrado de clientes", "Custo médio por OS", "Custo médio (todas as OS)"]}
        money.update({"% com deslocamento": st.column_config.NumberColumn(format="%.0f%%"),
                      "% do custo em deslocamento": st.column_config.NumberColumn(format="%.0f%%"),
                      "KM médio (OS com desloc.)": st.column_config.NumberColumn(format="%.0f km"),
                      "KM rodado": st.column_config.NumberColumn(format="%.0f")})
        contratos = oficinas.drop_duplicates("oficina").set_index("oficina")
        mapa_nome = dict(zip(fz["oficina"], fz["id_oficina"].astype(str)))
        contr_id = dict(zip(oficinas["id"].astype(str), oficinas["contrato"].fillna("Tabela")))
        fixo_id = dict(zip(oficinas["id"].astype(str), oficinas["valor_fixo"]))
        ini_id = dict(zip(oficinas["id"].astype(str), oficinas["inicio_fixo"]))

        def txt_contrato(n):
            nome = _nome_id.get(mapa_nome.get(n), n)
            if nome not in _ini_nome:
                return "Tabela"
            ini = _ini_nome[nome]
            return f"Preço fixo desde {ini:%m/%Y}" if ini is not None and pd.notna(ini) else "Preço fixo"
        r["Contrato"] = r["oficina"].map(txt_contrato)
        tab_ = v[(v["km"] > 0) & (v["valor_km"] > 0) & (v["modelo"] == "Tabela")]
        tarifa = (tab_["valor_km"].sum() / tab_["km"].sum()) if tab_["km"].sum() else None
        fx = v[v["modelo"] == "Preço fixo"]
        km_fx = fx.groupby("oficina")["km"].sum()
        r["KM incluso no contrato (R$ estimado)"] = r["oficina"].map(lambda n: km_fx.get(n) * tarifa if n in km_fx and tarifa else None)
        # custo médio por OS concluída, para TODAS as oficinas (nas de preço fixo, só o período do contrato fixo)
        conc = v[(v["status_ofs"] == "concluído") & ((v["modelo"] == "Tabela") | (v["modelo"] == "Preço fixo"))]
        conc = conc[~conc["oficina"].isin(fx["oficina"].unique()) | (conc["modelo"] == "Preço fixo")]
        med_fx = conc.groupby("oficina")["total_pagar"].mean()
        r["Custo médio por OS executada"] = r["oficina"].map(med_fx)
        r["OS executadas"] = r["oficina"].map(conc.groupby("oficina").size()).fillna(0).astype(int)
        r["Valor fixo"] = r["oficina"].map(lambda n: _val_nome.get(_nome_id.get(mapa_nome.get(n), n)))
        money["Custo médio por OS executada"] = st.column_config.NumberColumn(
            format="R$ %.0f", help="Média do total pago (serviço + KM + despesas) só das OS executadas (concluídas). Nas oficinas de "
                                   "preço fixo, só as OS a partir do início do contrato: compare com o valor fixo.")
        money["KM incluso no contrato (R$ estimado)"] = st.column_config.NumberColumn(
            format="R$ %.0f", help="Oficinas de preço fixo: KM rodado × tarifa média paga às oficinas de tabela.")
        money["Valor fixo"] = st.column_config.NumberColumn(format="R$ %.0f")
        r = r.rename(columns={"OS": "OS registradas", "Custo médio por OS": "Custo médio (todas as OS)"})
        cols_r = ["oficina", "Contrato", "Valor fixo", "OS executadas", "Custo médio por OS executada",
                  "OS registradas", "Custo médio (todas as OS)"] + [
            c for c in r.columns if c not in ("oficina", "Contrato", "Valor fixo", "OS com deslocamento", "OS executadas",
                                              "Custo médio por OS executada", "OS registradas", "Custo médio (todas as OS)")]
        r["Custo médio por OS executada"] = pd.to_numeric(r["Custo médio por OS executada"], errors="coerce")
        r["KM incluso no contrato (R$ estimado)"] = pd.to_numeric(r["KM incluso no contrato (R$ estimado)"], errors="coerce")
        vazias = [c for c in ("Custo médio por OS executada", "KM incluso no contrato (R$ estimado)", "Valor fixo")
                  if r[c].isna().all()]
        cols_r = [c for c in cols_r if c not in vazias]
        st.dataframe(r[cols_r].rename(columns={"oficina": "Oficina"}), hide_index=True, width="stretch", column_config=money)
        st.caption("**Custo médio por OS** = total pago ÷ todas as OS (inclui improdutivas e OS sem pagamento). "
                   "**Custo médio por OS concluída** = só as concluídas; nas oficinas de preço fixo, só o período do contrato fixo.")
        if r["Contrato"].str.startswith("Preço fixo").any():
            st.caption("Oficinas de **preço fixo** têm KM e despesas inclusos no valor do serviço: R$ 0 de deslocamento é "
                       "esperado (exceto atendimentos fora da área). A coluna \u201cKM incluso\u201d estima quanto esse "
                       f"deslocamento custaria no modelo de tabela (tarifa média de R$ {tarifa:.2f}/km)." if tarifa else "")
        elif not oficinas["contrato"].eq("Preço fixo").any():
            st.caption("Dica: marque as oficinas de preço fixo em 📥 Dados → Oficinas (coluna Contrato).")
    with aba[1]:
        st.caption("Custo médio por OS, por tipo de serviço e oficina (só OS com valor de serviço).")
        pv = v[v["valor_servico"] > 0].pivot_table(index="oficina", columns="familia", values="total_pagar",
                                                   aggfunc="mean").round(0)
        st.dataframe(pv, width="stretch", column_config={c: st.column_config.NumberColumn(format="R$ %.0f") for c in pv.columns})
        n_ = v.pivot_table(index="oficina", columns="familia", values="os", aggfunc="count", fill_value=0)
        st.caption("Quantidade de OS por tipo")
        st.dataframe(n_, width="stretch")
    with aba[2]:
        base_ev = fz[fz["oficina"].isin(sel_o)] if sel_o else fz
        ev = base_ev.groupby("mes")[["valor_servico", "valor_km", "extras"]].sum().reset_index().melt(
            id_vars="mes", var_name="Parte", value_name="R$")
        ev["Parte"] = ev["Parte"].map({"valor_servico": "Serviço", "valor_km": "Deslocamento (KM)", "extras": "Despesas extras"})
        ev["Mês"] = ev["mes"].map(fmt_m)
        st.altair_chart(alt.Chart(ev).mark_bar().encode(
            x=alt.X("Mês:N", sort=[fmt_m(x) for x in sorted(fz["mes"].unique())], title=None),
            y=alt.Y("R$:Q", title="R$ pago"),
            color=alt.Color("Parte:N", scale=alt.Scale(domain=["Serviço", "Deslocamento (KM)", "Despesas extras"],
                                                        range=[COR, "#E8B73A", "#D64545"]),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["Mês", "Parte", alt.Tooltip("R$:Q", format=",.0f")]).properties(height=300), width="stretch")
        cm = fin.resumo(base_ev, "mes").sort_values("mes")
        cm["Mês"] = cm["mes"].map(fmt_m)
        st.dataframe(cm[["Mês", "OS", "Total pago", "Custo médio por OS", "KM rodado", "% com deslocamento"]],
                     hide_index=True, width="stretch",
                     column_config={"Total pago": st.column_config.NumberColumn(format="R$ %.0f"),
                                    "Custo médio por OS": st.column_config.NumberColumn(format="R$ %.0f"),
                                    "% com deslocamento": st.column_config.NumberColumn(format="%.0f%%")})
    with aba[3]:
        ret_os = set(casos_rt.loc[casos_rt["status"].isin(["Retrabalho", "Pendente"]), "os_2"].astype(str)) if not casos_rt.empty else set()
        rr = v[v["os"].astype(str).isin(ret_os)]
        imp = v[v["status_ofs"] == "não concluído"]
        k = st.columns(4)
        k[0].metric("Pago em OS de retrabalho", brl(rr["total_pagar"].sum()), f"{len(rr)} OS", delta_color="off",
                    help="OS de retorno da base de retrabalho (confirmadas + pendentes de análise).")
        k[1].metric("% do total em retrabalho", f"{rr['total_pagar'].sum() / v['total_pagar'].sum() * 100:.1f}%" if v["total_pagar"].sum() else "—")
        k[2].metric("Pago em improdutivas", brl(imp["total_pagar"].sum()), f"{len(imp)} OS", delta_color="off")
        k[3].metric("% do total em improdutivas", f"{imp['total_pagar'].sum() / v['total_pagar'].sum() * 100:.1f}%" if v["total_pagar"].sum() else "—")
        t = pd.DataFrame({"Retrabalho (R$)": rr.groupby("oficina")["total_pagar"].sum(),
                          "Improdutivas (R$)": imp.groupby("oficina")["total_pagar"].sum()}).fillna(0)
        st.dataframe(t, width="stretch", column_config={c: st.column_config.NumberColumn(format="R$ %.0f") for c in t.columns})
    with aba[4]:
        al = v[v["alerta_placa"] | v["alerta_visita"] | (v["sem_comprovante"] > 0)]
        st.caption("Placa repetida (mesmo serviço/dia), visita recorrente em 30 dias ou despesa de viagem sem comprovante.")
        st.dataframe(al[["data", "oficina", "tecnico", "os", "tipo", "placa", "placa_repetida", "visita_recorrente",
                         "sem_comprovante", "total_pagar", "status_pagamento"]].rename(columns={
                         "data": "Execução", "oficina": "Oficina", "tecnico": "Técnico", "os": "OS", "tipo": "Tipo",
                         "placa": "Placa", "placa_repetida": "Placa repetida", "visita_recorrente": "Visita recorrente",
                         "sem_comprovante": "Sem comprovante (R$)", "total_pagar": "Total pago (R$)",
                         "status_pagamento": "Status pagamento"}), hide_index=True, width="stretch")
    with aba[5]:
        lista = v[["data", "oficina", "tecnico", "os", "tipo", "status_ofs", "cidade_uf", "km", "valor_km",
                   "valor_servico", "extras", "total_pagar", "total_receber", "status_pagamento"]].rename(columns={
                   "data": "Execução", "oficina": "Oficina", "tecnico": "Técnico", "os": "OS", "tipo": "Tipo",
                   "status_ofs": "Status OS", "cidade_uf": "Cidade/UF", "km": "KM", "valor_km": "R$ KM",
                   "valor_servico": "R$ serviço", "extras": "R$ extras", "total_pagar": "Total pago",
                   "total_receber": "Cobrado do cliente", "status_pagamento": "Status pagamento"})
        st.dataframe(lista, hide_index=True, width="stretch")
        st.download_button("⬇️ Baixar em Excel", para_excel(lista), "financeiro.xlsx")

    with aba[6]:
        fixas = sorted(fz.loc[fz["modelo"] == "Preço fixo", "oficina"].unique())
        if not fixas:
            st.info("Nenhuma oficina com preço fixo no cadastro (📥 Dados → Oficinas: Contrato, Valor fixo e "
                    "Preço fixo desde).")
        else:
            of_fx = st.selectbox("Oficina de preço fixo", fixas)
            sim, ref = fin.simular_tabela(fz[fz["oficina"] == of_fx], fz)
            if sel_m:
                sim = sim[sim["mes"].isin(sel_m)]
            st.caption("Compara o que foi pago no preço fixo (OS concluídas) com uma **estimativa** de quanto as mesmas OS "
                       "custariam na tabela, usando o histórico da própria oficina quando era tabela: valor por tipo de "
                       f"serviço, KM médio por cidade e tarifa de R$ {ref['tarifa']:.2f}/km. Despesas extras entram nos dois lados. "
                       "Use o filtro de mês acima (vazio = todos os meses).")
            if sim.empty:
                st.info("Sem OS de preço fixo no recorte.")
            else:
                pago, tab_ = sim["total_pagar"].sum(), sim["custaria_tabela"].sum()
                k = st.columns(4)
                k[0].metric("OS concluídas no preço fixo", len(sim))
                k[1].metric("Pago (preço fixo)", brl(pago))
                k[2].metric("Custaria na tabela (estimado)", brl(tab_))
                dif = pago - tab_
                k[3].metric("Diferença", brl(dif), f"{dif / tab_ * 100:+.0f}% {'mais caro' if dif > 0 else 'mais barato'} que a tabela" if tab_ else None,
                            delta_color="inverse")
                cfg_m = {c: st.column_config.NumberColumn(format="R$ %.0f") for c in ["Pago", "Custaria na tabela", "Diferença", "Preço tabela de referência"]}
                st.markdown("**Por tipo de serviço**")
                pt = sim.groupby("familia").agg(OS=("os", "count"), Pago=("total_pagar", "sum"),
                                                **{"Custaria na tabela": ("custaria_tabela", "sum")}).reset_index()
                pt["Diferença"] = pt["Pago"] - pt["Custaria na tabela"]
                pt["Preço tabela de referência"] = pt["familia"].map(ref["precos"])
                st.dataframe(pt.rename(columns={"familia": "Tipo"}), hide_index=True, width="stretch", column_config=cfg_m)
                st.markdown("**Por cidade** (onde o preço fixo compensa: diferença negativa)")
                pc = sim.groupby("cid").agg(OS=("os", "count"), **{"KM médio na tabela": ("km_estimado", "mean")},
                                            Pago=("total_pagar", "sum"), **{"Custaria na tabela": ("custaria_tabela", "sum")}).reset_index()
                pc["Diferença"] = pc["Pago"] - pc["Custaria na tabela"]
                st.dataframe(pc.sort_values("Diferença").rename(columns={"cid": "Cidade"}), hide_index=True, width="stretch",
                             column_config={**cfg_m, "KM médio na tabela": st.column_config.NumberColumn(format="%.0f km")})
                pm = sim.groupby("mes").agg(Pago=("total_pagar", "sum"), **{"Custaria na tabela": ("custaria_tabela", "sum")}).reset_index()
                pm["Mês"] = pm["mes"].map(fmt_m)
                g = pm.melt(id_vars="Mês", value_vars=["Pago", "Custaria na tabela"], var_name="Modelo", value_name="R$")
                st.markdown("**Mês a mês**")
                st.altair_chart(alt.Chart(g).mark_bar().encode(
                    x=alt.X("Mês:N", title=None), xOffset="Modelo:N", y=alt.Y("R$:Q"),
                    color=alt.Color("Modelo:N", scale=alt.Scale(domain=["Pago", "Custaria na tabela"], range=[COR, "#9DBDBA"]),
                                    legend=alt.Legend(title=None, orient="bottom")),
                    tooltip=["Mês", "Modelo", alt.Tooltip("R$:Q", format=",.0f")]).properties(height=260), width="stretch")
                if ref["cidades_sem_historico"]:
                    st.warning("Cidades sem histórico na época da tabela (o KM delas entra como 0 na estimativa, então o "
                               "custo de tabela fica subestimado): " + ", ".join(ref["cidades_sem_historico"]))


# ---------------------------------------------------------------- comparativo anual
elif area == "📅 Comparativo anual":
    st.title("Comparativo anual")
    st.caption("🔒 Área interna. Compara a região mês a mês com as oficinas que existiam em cada período. Fonte: "
               "Consolidados e planilhas de pagamento importados em 📥 Dados → Financeiro.")
    fz = na_regiao(banco.carregar_financeiro())
    if fz.empty:
        st.info("Importe os Consolidados em **📥 Dados → Financeiro**.")
        st.stop()
    fz["oficina"] = fz["oficina_cad"].fillna(fz["oficina"])
    futuras = pd.to_datetime(fz["data"]) > pd.Timestamp.today()
    if futuras.any():  # datas no futuro são erro de digitação na planilha
        st.caption(f"⚠️ {int(futuras.sum())} OS com data de execução no futuro foram ignoradas (erro de data na planilha).")
        fz = fz[~futuras]
    dts = pd.to_datetime(fz["data"])
    fz["ano"], fz["mes_n"] = dts.dt.year, dts.dt.month
    anos = sorted(fz["ano"].unique())
    if len(anos) < 2:
        st.info("É preciso ter pelo menos dois anos importados.")
        st.stop()
    MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    c1, c2, c3, c4 = st.columns([0.8, 0.8, 1.6, 1.6])
    ano_a = c1.selectbox("Ano base", anos, index=len(anos) - 2)
    ano_b = c2.selectbox("Comparar com", anos, index=len(anos) - 1)
    meses_b = sorted(fz.loc[fz["ano"] == ano_b, "mes_n"].unique())
    hoje_ = pd.Timestamp.today()
    mes_aberto = ano_b == hoje_.year and meses_b and meses_b[-1] == hoje_.month
    if mes_aberto and len(meses_b) > 1:  # mês corrente ainda não fechou: fica fora da comparação "mesmos meses"
        meses_b = meses_b[:-1]
    modo_p = c3.radio("Período", [f"Mesmos meses ({MESES[meses_b[0] - 1]} a {MESES[meses_b[-1] - 1]})", "Ano inteiro"],
                      horizontal=True, help="Mesmos meses: compara só os meses que o ano de comparação já tem, sem o mês "
                                            "corrente (ainda não fechado). Ano inteiro: todos os meses de cada ano.")
    sel_of = c4.multiselect("Oficinas (pode escolher várias)", sorted(fz.loc[fz["ano"].isin([ano_a, ano_b]), "oficina"].unique()),
                            placeholder="Região toda", key="cmp_of",
                            help="Escolha juntas as oficinas que atenderam a mesma área em anos diferentes (ex.: a que saiu "
                                 "e a que entrou) para comparar a área como um todo.")
    v = fz[fz["ano"].isin([ano_a, ano_b])]
    if modo_p != "Ano inteiro":
        v = v[v["mes_n"].isin(meses_b)]
    if sel_of:
        v = v[v["oficina"].isin(sel_of)]

    # técnicos: pelo instalador das planilhas; quando não houver (ex.: 2025), pelo lançamento manual
    tec_man = banco.ler_config("tecnicos_ano", {})
    # média mensal de técnicos diferentes (evita contar como equipe todos que passaram pela oficina no ano)
    tec_dados = (v.dropna(subset=["tecnico"]).groupby(["ano", "oficina", "mes_n"])["tecnico"].nunique()
                 .groupby(["ano", "oficina"]).mean().round(1))

    def tecnicos(ano, ofs):
        tot = 0
        for o in ofs:
            n = tec_dados.get((ano, o)) if (ano, o) in tec_dados.index else None
            if n is None:
                n = tec_man.get(str(ano), {}).get(o)
            tot += float(n or 0)
        return round(tot, 1)

    def metricas(d, ano):
        e = d[d["status_ofs"] == "concluído"]
        meses_n = d["mes_n"].nunique() or 1
        ofs = sorted(d["oficina"].unique())
        tec = tecnicos(ano, ofs)
        com_km = d[d["km"] > 0]
        return {
            "Oficinas atendendo": len(ofs),
            "Técnicos": tec or None,
            "OS registradas": len(d),
            "OS executadas": len(e),
            "Improdutividade (%)": (d["status_ofs"] == "não concluído").mean() * 100 if len(d) else None,
            "Total pago (R$)": d["total_pagar"].sum(),
            "Custo médio por OS executada (R$)": e["total_pagar"].mean() if len(e) else None,
            "Serviço no custo (%)": d["valor_servico"].sum() / d["total_pagar"].sum() * 100 if d["total_pagar"].sum() else None,
            "Deslocamento no custo (%)": d["valor_km"].sum() / d["total_pagar"].sum() * 100 if d["total_pagar"].sum() else None,
            "OS com deslocamento (%)": len(com_km) / len(d) * 100 if len(d) else None,
            "KM médio (OS com desloc.)": com_km["km"].mean() if len(com_km) else None,
            "R$ por KM": com_km["valor_km"].sum() / com_km["km"].sum() if com_km["km"].sum() else None,
            "OS executadas por mês": len(e) / meses_n,
            "OS por oficina por mês": len(e) / meses_n / len(ofs) if ofs else None,
            "OS por técnico por mês": len(e) / meses_n / tec if tec else None,
        }

    ma, mb = metricas(v[v["ano"] == ano_a], ano_a), metricas(v[v["ano"] == ano_b], ano_b)
    linhas = []
    for k in ma:
        x, y = ma[k], mb[k]
        var = (y - x) / x * 100 if (x not in (None, 0) and y is not None and pd.notna(x) and pd.notna(y)) else None
        fmt = (lambda z: "—" if z is None or pd.isna(z) else (f"R$ {z:,.0f}".replace(",", ".") if "(R$)" in k else
               f"{z:.1f}%".replace(".", ",") if "(%)" in k else f"{z:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
               if isinstance(z, float) and not float(z).is_integer() else f"{int(z):,}".replace(",", ".")))
        linhas.append({"Indicador": k, str(ano_a): fmt(x), str(ano_b): fmt(y),
                       "Variação": "—" if var is None else f"{var:+.0f}%"})
    st.subheader(f"Região: {ano_a} × {ano_b}" + ("" if modo_p == "Ano inteiro" else f" ({MESES[meses_b[0] - 1]}–{MESES[meses_b[-1] - 1]})"))
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
    if not ma["Técnicos"] or not mb["Técnicos"]:
        st.caption("Para \u201cOS por técnico\u201d, informe o nº de técnicos dos anos sem instalador na planilha "
                   "(ex.: 2025) no quadro \u201cTécnicos por oficina e ano\u201d abaixo.")

    aba = st.tabs(["Mês a mês", "Mix de serviços", "Por oficina", "Técnicos por oficina e ano", "Marcos de mudança"])
    marcos = pd.DataFrame(banco.ler_config("marcos", []), columns=["oficina", "data", "descricao"])
    with aba[0]:
        separar = False
        if len(sel_of) >= 2:
            separar = st.radio("Mostrar as oficinas", ["Separadas", "Somadas"], horizontal=True, key="cmp_sep",
                               help="Separadas: uma linha por oficina e ano. Somadas: as oficinas escolhidas como se fossem uma área só.") == "Separadas"
        chaves = ["ano", "mes_n"] + (["oficina"] if separar else [])
        mm = v.groupby(chaves).agg(exec_=("status_ofs", lambda s: (s == "concluído").sum()),
                                   pago=("total_pagar", "sum")).reset_index()
        ex_ = v[v["status_ofs"] == "concluído"].groupby(chaves)["total_pagar"].mean().rename("medio")
        mm = mm.merge(ex_.reset_index(), on=chaves, how="left")
        mm["Mês"] = mm["mes_n"].map(lambda m: MESES[m - 1])
        mm["Ano"] = mm["ano"].astype(str)
        x_ = alt.X("Mês:N", sort=MESES, title=None)
        leg = alt.Legend(title=None, orient="bottom", columns=2, labelLimit=320)
        if separar:
            mm["Oficina"] = mm["oficina"]
            mm["Série"] = mm["Oficina"] + " · " + mm["Ano"]
            enc = dict(x=x_, color=alt.Color("Oficina:N", legend=leg),
                       strokeDash=alt.StrokeDash("Ano:N", scale=alt.Scale(range=[[4, 3], [1, 0]]), legend=alt.Legend(title="Ano (tracejado = ano base)", orient="bottom")),
                       detail="Série:N")
            tip = ["Oficina", "Ano", "Mês"]
            st.caption("Cada cor é uma oficina; **linha tracejada = ano base**, linha cheia = ano de comparação.")
        else:
            enc = dict(x=x_, color=alt.Color("Ano:N", scale=alt.Scale(range=["#9DBDBA", COR]), legend=leg))
            tip = ["Ano", "Mês"]
            if len(sel_of) >= 2:
                st.caption(f"Somando as {len(sel_of)} oficinas escolhidas: " + ", ".join(sel_of) + ".")
        c1, c2 = st.columns(2)
        c1.markdown("**OS executadas**")
        c1.altair_chart(alt.Chart(mm).mark_line(point=True).encode(y=alt.Y("exec_:Q", title=None),
                        tooltip=tip + [alt.Tooltip("exec_:Q", title="OS executadas")], **enc).properties(height=280), width="stretch")
        c2.markdown("**Custo médio por OS executada (R$)**")
        c2.altair_chart(alt.Chart(mm).mark_line(point=True).encode(y=alt.Y("medio:Q", title=None),
                        tooltip=tip + [alt.Tooltip("medio:Q", title="R$", format=",.0f")], **enc).properties(height=280), width="stretch")
        st.markdown("**Total pago por mês (R$)**")
        if separar:
            st.altair_chart(alt.Chart(mm).mark_bar().encode(x=x_, xOffset="Ano:N", y=alt.Y("pago:Q", title=None, stack=True),
                            color=alt.Color("Oficina:N", legend=leg), opacity=alt.Opacity("Ano:N", scale=alt.Scale(range=[0.45, 1]),
                                                                                           legend=alt.Legend(title="Ano (claro = ano base)", orient="bottom")),
                            tooltip=["Oficina", "Ano", "Mês", alt.Tooltip("pago:Q", title="R$", format=",.0f")]).properties(height=260), width="stretch")
        else:
            st.altair_chart(alt.Chart(mm).mark_bar().encode(x=x_, xOffset="Ano:N",
                            y=alt.Y("pago:Q", title=None), color=enc["color"],
                            tooltip=["Ano", "Mês", alt.Tooltip("pago:Q", title="R$", format=",.0f")]).properties(height=240), width="stretch")
        if len(sel_of) == 1:
            mk = marcos[marcos["oficina"] == sel_of[0]]
            if not mk.empty:
                st.caption("Marcos desta oficina: " + "; ".join(f"{pd.to_datetime(r.data):%m/%Y} — {r.descricao}" for r in mk.itertuples()))
    with aba[1]:
        mx = v[v["status_ofs"] == "concluído"].groupby(["ano", "familia"]).size().rename("qtd").reset_index()
        mx["%"] = mx["qtd"] / mx.groupby("ano")["qtd"].transform("sum") * 100
        mx["Ano"] = mx["ano"].astype(str)
        st.altair_chart(alt.Chart(mx).mark_bar().encode(y=alt.Y("familia:N", title=None, sort="-x"), x=alt.X("%:Q", title="% das OS executadas"),
                        yOffset="Ano:N", color=alt.Color("Ano:N", scale=alt.Scale(range=["#9DBDBA", COR]), legend=alt.Legend(title=None, orient="bottom")),
                        tooltip=["Ano", "familia", "qtd", alt.Tooltip("%:Q", format=".1f")]).properties(height=320), width="stretch")
    with aba[2]:
        ofs_all = sorted(v["oficina"].unique())
        tab = []
        ativas = dict(zip(oficinas["oficina"], oficinas["ativa"].fillna("Sim")))
        for o in ofs_all:
            da, db = v[(v["oficina"] == o) & (v["ano"] == ano_a)], v[(v["oficina"] == o) & (v["ano"] == ano_b)]
            xa, xb = metricas(da, ano_a) if len(da) else {}, metricas(db, ano_b) if len(db) else {}
            sit = ("Entrou em " + f"{pd.to_datetime(db['data'].min()):%m/%Y}") if len(da) == 0 else \
                  ("Saiu — última OS " + f"{pd.to_datetime(da['data'].max()):%m/%Y}") if len(db) == 0 else \
                  ("Inativa" if str(ativas.get(o, "Sim")).lower().startswith("n") else "Ativa nos dois anos")
            mk = marcos[marcos["oficina"] == o]
            tab.append({"Oficina": o, "Situação": sit,
                        f"OS exec. {ano_a}": xa.get("OS executadas"), f"OS exec. {ano_b}": xb.get("OS executadas"),
                        f"Custo médio {ano_a}": xa.get("Custo médio por OS executada (R$)"), f"Custo médio {ano_b}": xb.get("Custo médio por OS executada (R$)"),
                        f"KM médio {ano_a}": xa.get("KM médio (OS com desloc.)"), f"KM médio {ano_b}": xb.get("KM médio (OS com desloc.)"),
                        f"Improd. {ano_a} %": xa.get("Improdutividade (%)"), f"Improd. {ano_b} %": xb.get("Improdutividade (%)"),
                        "Marcos": "; ".join(f"{pd.to_datetime(r.data):%m/%Y} {r.descricao}" for r in mk.itertuples())})
        td = pd.DataFrame(tab)
        cfg_t = {c: st.column_config.NumberColumn(format="R$ %.0f") for c in td.columns if c.startswith("Custo médio")}
        cfg_t.update({c: st.column_config.NumberColumn(format="%.0f km") for c in td.columns if c.startswith("KM médio")})
        cfg_t.update({c: st.column_config.NumberColumn(format="%.1f%%") for c in td.columns if c.startswith("Improd.")})
        st.dataframe(td, hide_index=True, width="stretch", column_config=cfg_t)
    with aba[3]:
        st.caption("Quando a planilha não traz o instalador (ex.: Consolidado 2025), informe aqui quantos técnicos cada "
                   "oficina tinha no ano. Anos com instalador na planilha são contados automaticamente.")
        ano_t = st.selectbox("Ano", anos, index=anos.index(ano_a), key="ano_tec")
        ofs_t = sorted(fz.loc[fz["ano"] == ano_t, "oficina"].unique())
        auto = (fz[fz["ano"] == ano_t].dropna(subset=["tecnico"]).groupby(["oficina", "mes_n"])["tecnico"].nunique()
                .groupby("oficina").mean().round(1))
        grade = pd.DataFrame({"Oficina": ofs_t, "Pela planilha (média por mês)": [auto.get(o) for o in ofs_t],
                              "Informado": [tec_man.get(str(ano_t), {}).get(o) for o in ofs_t]})
        ed = st.data_editor(grade, hide_index=True, width="stretch", disabled=["Oficina", "Pela planilha (média por mês)"], key=f"tec_{ano_t}",
                            column_config={"Informado": st.column_config.NumberColumn(min_value=0, step=1)})
        if st.button("Salvar técnicos do ano"):
            tec_man[str(ano_t)] = {r["Oficina"]: int(r["Informado"]) for _, r in ed.iterrows() if pd.notna(r["Informado"])}
            banco.salvar_config("tecnicos_ano", tec_man)
            st.success("Técnicos salvos.")
            st.rerun()
    with aba[4]:
        st.caption("Registre as mudanças importantes por oficina (contrato, nova área, novo tipo de atendimento). Elas "
                   "aparecem na tabela por oficina e ajudam a ler o antes × depois.")
        ed_m = st.data_editor(marcos.assign(data=pd.to_datetime(marcos["data"], errors="coerce")), num_rows="dynamic",
                              hide_index=True, width="stretch", key="ed_marcos",
                              column_config={"oficina": st.column_config.SelectboxColumn("Oficina", options=sorted(fz["oficina"].unique())),
                                             "data": st.column_config.DateColumn("Data", format="MM/YYYY"),
                                             "descricao": st.column_config.TextColumn("O que mudou", width="large")})
        if st.button("Salvar marcos"):
            ok = ed_m.dropna(subset=["oficina", "data"])
            banco.salvar_config("marcos", [{"oficina": r.oficina, "data": str(pd.to_datetime(r.data).date()),
                                             "descricao": r.descricao or ""} for r in ok.itertuples()])
            st.success("Marcos salvos.")
            st.rerun()


# ---------------------------------------------------------------- oficinas próprias
elif area == "🏠 Oficinas próprias":
    st.title("Oficinas próprias")
    st.caption("Oficinas do próprio cliente. Acompanhamento só de volume: não entram nos indicadores da rede nem no "
               "financeiro. Fonte: 📥 Dados → Oficinas próprias (e a base de retrabalho).")
    props = oficinas_todas[oficinas_todas["tipo"] == "Própria"]
    if consultor_ver != "Todos":
        props = props[props["consultor"].astype(str).str.strip() == consultor_ver]
    nome_p = dict(zip(props["id"].astype(str), props["oficina"]))
    pp = ativ_todas[ativ_todas["tipo_base"] == "proprias"].copy() if not ativ_todas.empty else pd.DataFrame()
    if pp.empty:
        st.info("Importe a exportação das oficinas próprias em **📥 Dados → Oficinas próprias**.")
        st.stop()
    pp["oficina"] = pp["id_oficina"].astype(str).map(nome_p).fillna(pp["oficina"])
    pp["mes"] = pd.to_datetime(pp["data"]).dt.strftime("%Y-%m")
    fmt_m = lambda m: f"{m[5:]}/{m[:4]}"
    c1, c2 = st.columns(2)
    meses_p = sorted(pp["mes"].unique(), reverse=True)
    sel_m = c1.multiselect("Mês", meses_p, placeholder="Todos", format_func=fmt_m, key="pp_m")
    sel_o = c2.multiselect("Oficina", sorted(pp["oficina"].unique()), placeholder="Todas", key="pp_o")
    v = pp
    if sel_m:
        v = v[v["mes"].isin(sel_m)]
    if sel_o:
        v = v[v["oficina"].isin(sel_o)]
    exe = (v["status"] == "concluído").sum()
    imp = (v["status"] == "não concluído").sum()
    k = st.columns(5)
    k[0].metric("Atendimentos registrados", len(v))
    k[1].metric("Executados", int(exe))
    k[2].metric("Improdutivos", int(imp))
    k[3].metric("Cancelados", int((v["status"] == "cancelado").sum()))
    k[4].metric("Improdutividade", f"{imp / (exe + imp) * 100:.0f}%" if (exe + imp) else "—")
    t = v.groupby("oficina").agg(Registrados=("os", "count"),
                                 Executados=("status", lambda s: (s == "concluído").sum()),
                                 Improdutivos=("status", lambda s: (s == "não concluído").sum()),
                                 Cancelados=("status", lambda s: (s == "cancelado").sum()),
                                 Meses=("mes", "nunique"), **{"Última OS": ("data", "max")}).reset_index()
    t["Executados por mês"] = (t["Executados"] / t["Meses"]).round(1)
    st.dataframe(t.drop(columns="Meses").rename(columns={"oficina": "Oficina"}).sort_values("Executados", ascending=False),
                 hide_index=True, width="stretch",
                 column_config={"Última OS": st.column_config.DateColumn(format="DD/MM/YYYY")})
    c1, c2 = st.columns(2)
    with c1:
        ev = v[v["status"] == "concluído"].groupby(["mes", "oficina"]).size().rename("qtd").reset_index()
        ev["Mês"] = ev["mes"].map(fmt_m)
        st.markdown("**Executados por mês**")
        st.altair_chart(alt.Chart(ev).mark_bar().encode(x=alt.X("Mês:N", sort=[fmt_m(m) for m in sorted(ev["mes"].unique())], title=None),
                        y=alt.Y("qtd:Q", title=None), color=alt.Color("oficina:N", legend=alt.Legend(title=None, orient="bottom")),
                        tooltip=["Mês", "oficina", "qtd"]).properties(height=260), width="stretch")
    with c2:
        barras(v[v["status"] == "concluído"], "familia", "Tipos de serviço executados")
    # retrabalho das próprias (mesma base de retrabalho, ligada pelo nome / outros nomes do cadastro)
    st.subheader("Retrabalho das oficinas próprias")
    base_rt = banco.carregar_retrabalho()
    if base_rt.empty:
        st.caption("Importe a base de retrabalho em 📥 Dados → Retrabalho.")
    else:
        nomes_cmp = {}
        for _, r_ in props.iterrows():
            for n_ in [r_["oficina"]] + [x for x in str(r_.get("outros_nomes") or "").split(";") if x.strip()]:
                nomes_cmp[compacto(n_)] = r_["oficina"]

        def oficina_propria(nome):
            c_ = compacto(nome)
            if c_ in nomes_cmp:
                return nomes_cmp[c_]
            for k_, v_ in nomes_cmp.items():
                if len(k_) >= 5 and len(c_) >= 5 and (c_.startswith(k_) or k_.startswith(c_)):
                    return v_
            return None
        rp = rt.triar(base_rt, cfg_rt, obs_ofs)
        rp["oficina_p"] = rp["oficina"].map(oficina_propria)
        rp = rp[rp["oficina_p"].notna()]
        if sel_o:
            rp = rp[rp["oficina_p"].isin(sel_o)]
        if rp.empty:
            st.caption("Nenhum caso de retrabalho das oficinas próprias na base.")
        else:
            rp["status"] = rp.apply(status_final, axis=1)
            tr = rp.groupby("oficina_p").agg(Casos=("id_caso", "count"),
                                             Retrabalhos=("status", lambda s: s.isin(["Retrabalho", "Pendente"]).sum()),
                                             **{"Não é retrabalho": ("status", lambda s: (s == "Não é retrabalho").sum())},
                                             **{"Último retorno": ("data_2", "max")}).reset_index()
            st.dataframe(tr.rename(columns={"oficina_p": "Oficina"}), hide_index=True, width="stretch",
                         column_config={"Último retorno": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                        "Retrabalhos": st.column_config.NumberColumn(help="Confirmados + pendentes de análise (regra dos 90 dias).")})
            with st.expander("Ver os casos"):
                st.dataframe(rp[["competencia", "oficina_p", "placa", "os_1", "data_1", "os_2", "data_2", "dias",
                                 "diag_jira_2", "status", "motivo_auto"]].rename(columns={
                                 "competencia": "Competência", "oficina_p": "Oficina", "placa": "Placa", "os_1": "OS 1ª",
                                 "data_1": "Data 1ª", "os_2": "OS retorno", "data_2": "Data retorno", "dias": "Dias",
                                 "diag_jira_2": "Diagnóstico retorno", "status": "Status", "motivo_auto": "Motivo"}),
                             hide_index=True, width="stretch")


# ---------------------------------------------------------------- mau uso (sinistro)
elif area == "⚠️ Mau uso (sinistro)":
    st.title("Mau uso / sinistro apontado")
    st.caption("OS executadas em que o técnico apontou sinistro ou mau uso: flag de sinistro na OS ou termos como "
               "\u201csinistro\u201d, \u201cviolado\u201d, \u201cmau uso\u201d na observação (lista em ⚙️ Configurações → "
               "Regras de retrabalho). Apontar é o esperado: a meta é um % mínimo de apontamento.")
    if base.empty:
        sem_dados()
        st.stop()
    feitos = base[base["classificacao"].isin([regras.EXECUTADO, regras.ENCAIXE, regras.IMPRODUTIVA])].copy()
    c1, c2, c3 = st.columns([1.4, 1.6, 1.4])
    dmin, dmax = min(feitos["data_operacional"]), max(feitos["data_operacional"])
    per = c1.date_input("Período", (max(dmin, dmax - timedelta(days=30)), dmax), min_value=dmin, max_value=dmax,
                        format="DD/MM/YYYY", key="sin_per")
    ini, fim = per if len(per) == 2 else (per[0], per[0])
    feitos = feitos[(feitos["data_operacional"] >= ini) & (feitos["data_operacional"] <= fim)]
    sel_o = c2.multiselect("Oficina", sorted(feitos["oficina"].dropna().unique()), placeholder="Todas", key="sin_of")
    if sel_o:
        feitos = feitos[feitos["oficina"].isin(sel_o)]
    sel_f = c3.multiselect("Família de serviço", regras.FAMILIAS, placeholder="Todas", key="sin_fam")
    if sel_f:
        feitos = feitos[feitos["familia"].isin(sel_f)]
    feitos["sinistro"] = feitos.apply(indica_sinistro, axis=1)
    sin = feitos[feitos["sinistro"] != ""]
    meta_s = {**ef.METAS_PADRAO, **banco.ler_config("metas_eficiencia", {})}["sinistro"]
    pct_s = len(sin) / len(feitos) * 100 if len(feitos) else None
    k = st.columns(3)
    k[0].metric("Atendimentos no período", len(feitos))
    k[1].metric("Com sinistro / mau uso apontado", len(sin))
    k[2].metric("Apontamento", "—" if pct_s is None else f"{pct_s:.1f}%".replace(".", ","), f"meta mín. {meta_s}%",
                delta_color="normal" if (pct_s or 0) >= meta_s else "inverse")
    if not feitos.empty:
        t = feitos.groupby("oficina").agg(Atendimentos=("os", "count"), Apontados=("sinistro", lambda s: (s != "").sum())).reset_index()
        t["% apontado"] = (t["Apontados"] / t["Atendimentos"] * 100).round(1)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Por oficina**")
            st.dataframe(t.rename(columns={"oficina": "Oficina"}).sort_values("% apontado", ascending=False), hide_index=True,
                         width="stretch", column_config={"% apontado": st.column_config.NumberColumn(format="%.1f%%")})
        with c2:
            tt = feitos.groupby(["tecnico", "oficina"]).agg(Atendimentos=("os", "count"),
                                                            Apontados=("sinistro", lambda s: (s != "").sum())).reset_index()
            tt["% apontado"] = (tt["Apontados"] / tt["Atendimentos"] * 100).round(1)
            st.markdown("**Por técnico**")
            st.dataframe(tt.rename(columns={"tecnico": "Técnico", "oficina": "Oficina"}).sort_values("% apontado", ascending=False),
                         hide_index=True, width="stretch", column_config={"% apontado": st.column_config.NumberColumn(format="%.1f%%")})
    st.subheader("OS com sinistro / mau uso apontado")
    if sin.empty:
        st.info("Nenhuma OS com sinistro apontado no recorte.")
    else:
        lista = sin[["data_operacional", "oficina", "tecnico", "os", "ticket", "placa", "tipo_atividade", "sinistro",
                     "obs_tecnico"]].rename(columns={"data_operacional": "Data", "oficina": "Oficina", "tecnico": "Técnico",
                     "os": "OS", "ticket": "Ticket", "placa": "Placa", "tipo_atividade": "Serviço",
                     "sinistro": "Como foi identificado", "obs_tecnico": "Observação do técnico"})
        st.dataframe(lista, hide_index=True, width="stretch",
                     column_config={"Data": st.column_config.DateColumn(format="DD/MM/YYYY")})
        st.download_button("⬇️ Baixar em Excel", para_excel(lista), "sinistros_apontados.xlsx")


# ---------------------------------------------------------------- não conformidade
elif area == "📝 Não conformidade":
    st.title("Não conformidades / reclamações de cliente")
    st.caption("Registro das reclamações (ex.: que chegam pelo Asana) e da sua análise. **Procedentes** contam no KPI "
               "\u201cNão conformidade\u201d da 🏆 Eficiência e, na visão da oficina, aparecem com relato e análise. "
               "**Improcedentes** não contam; a oficina verá só a quantidade. **Canceladas** não contam e não aparecem.")
    ncs = banco.carregar_nc()
    CANAIS = ["Asana", "WhatsApp", "Telefone", "Chamado / ticket", "E-mail", "Presencial", "Outro"]
    MOTIVOS = ["Atraso / fora do horário", "Técnico não compareceu", "Postura / atendimento do técnico",
               "Serviço mal executado", "Dano ao veículo", "Sujeira / organização", "Demora para resolver", "Outro"]
    STATUS = ["Em análise", "Procedente", "Improcedente"]
    for c_ in ("reeditada", "historico"):
        if c_ not in ncs.columns:
            ncs[c_] = None
    abertas = ncs[ncs["status"] == "Em análise"] if not ncs.empty else ncs
    agora = lambda: f"{pd.Timestamp.now():%d/%m/%Y %H:%M}"

    def form_nc(editar, chave):
        """Formulário de reclamação: novo (editar=None) ou edição de uma em análise."""
        g = lambda c, pad=None: (editar[c] if editar is not None and c in editar and pd.notna(editar[c]) else pad)
        os_in = st.text_input("Número da OS (se houver)", g("os", ""), key=f"os_{chave}",
                              help="Se a OS estiver nas bases importadas, oficina, técnico, placa e data vêm preenchidos.")
        achado = None
        if os_in and not ativ_todas.empty:
            m_ = ativ_todas[ativ_todas["os"].astype(str) == os_in.strip()]
            if not m_.empty:
                achado = m_.sort_values("data_ref").iloc[-1]
                st.success(f"OS encontrada: {achado['oficina']} · {achado.get('tecnico') or '—'} · {achado.get('placa') or '—'} · {achado['data']:%d/%m/%Y}")
        nomes_of = sorted(oficinas_todas["oficina"].dropna().unique())
        of_pad = g("oficina", achado["oficina"] if achado is not None else None)
        with st.form(f"form_nc_{chave}"):
            c1, c2, c3 = st.columns(3)
            data_nc = c1.date_input("Data da reclamação", pd.to_datetime(g("data", pd.Timestamp.today())).date(), format="DD/MM/YYYY")
            of_nc = c2.selectbox("Oficina", nomes_of, index=nomes_of.index(of_pad) if of_pad in nomes_of else None)
            tec_nc = c3.text_input("Técnico", g("tecnico", achado.get("tecnico") if achado is not None else "") or "")
            c1, c2, c3 = st.columns(3)
            cli_nc = c1.text_input("Cliente", g("cliente", "") or "")
            placa_nc = c2.text_input("Placa", g("placa", achado.get("placa") if achado is not None else "") or "")
            canal_nc = c3.selectbox("Canal", CANAIS, index=CANAIS.index(g("canal")) if g("canal") in CANAIS else 0)
            motivo_nc = st.selectbox("Motivo", MOTIVOS, index=MOTIVOS.index(g("motivo")) if g("motivo") in MOTIVOS else 0)
            desc_nc = st.text_area("O que o cliente relatou", g("descricao", "") or "")
            st.markdown("**Análise**")
            c1, c2 = st.columns(2)
            st_nc = c1.radio("Situação", STATUS, horizontal=True, index=STATUS.index(g("status")) if g("status") in STATUS else 0,
                             help="Enquanto estiver Em análise, dá para editar. Procedente ou Improcedente encerra o registro.")
            dt_an = c2.date_input("Data da análise", pd.to_datetime(g("data_analise", pd.Timestamp.today())).date(), format="DD/MM/YYYY")
            an_nc = st.text_area("Análise / resposta (o que foi apurado e conversado com a oficina)", g("analise", "") or "")
            ev_nc = st.text_area("Evidências (links, prints, protocolo do Asana)", g("evidencias", "") or "")
            enviar = st.form_submit_button("💾 Salvar", type="primary")
        if enviar:
            if not of_nc:
                st.error("Escolha a oficina.")
                return
            id_ = g("id") or f"NC{pd.Timestamp.now():%Y%m%d%H%M%S}"
            linha_id = oficinas_todas.loc[oficinas_todas["oficina"] == of_nc, "id"].astype(str)
            evento = ("criada" if editar is None else "atualizada") + (f" e concluída como {st_nc}" if st_nc != "Em análise" else "")
            hist = ((g("historico", "") or "") + f"\n{agora()} — {evento}").strip()
            banco.salvar_nc({"id": id_, "data": str(data_nc), "os": os_in.strip() or None, "oficina": of_nc,
                             "id_oficina": linha_id.iloc[0] if len(linha_id) else None,
                             "tecnico": tec_nc or None, "cliente": cli_nc or None, "placa": placa_nc or None, "canal": canal_nc,
                             "motivo": motivo_nc, "descricao": desc_nc or None, "status": st_nc,
                             "data_analise": str(dt_an) if st_nc != "Em análise" else None, "analise": an_nc or None,
                             "evidencias": ev_nc or None, "reeditada": g("reeditada"), "historico": hist,
                             "registrado_em": g("registrado_em") or f"{pd.Timestamp.now():%Y-%m-%d %H:%M}"})
            st.session_state["msg_nc"] = f"Registro {id_} salvo ({st_nc})."
            st.rerun()

    if "msg_nc" in st.session_state:
        st.success(st.session_state.pop("msg_nc"))
    aba = st.tabs([f"⏳ Em análise ({len(abertas)})", "➕ Nova reclamação", "Registros", "Resumo"])
    with aba[0]:
        if abertas.empty:
            st.info("Nenhuma reclamação em análise.")
        else:
            ab = abertas.assign(dias=(pd.Timestamp.today().normalize() - abertas["data"]).dt.days).sort_values("data")
            st.dataframe(ab[["id", "data", "dias", "oficina", "tecnico", "motivo", "canal", "reeditada"]].rename(columns={
                "id": "Registro", "data": "Data", "dias": "Dias em aberto", "oficina": "Oficina", "tecnico": "Técnico",
                "motivo": "Motivo", "canal": "Canal", "reeditada": "Reaberta"}), hide_index=True, width="stretch",
                column_config={"Data": st.column_config.DateColumn(format="DD/MM/YYYY")})
            esc = st.selectbox("Abrir para continuar a análise", [None] + ab["id"].tolist(), key="nc_abrir",
                               format_func=lambda i: "Escolha uma reclamação" if i is None else
                               f"{i} · {ab.set_index('id').loc[i, 'oficina']} · {ab.set_index('id').loc[i, 'data']:%d/%m/%Y}")
            if esc:
                reg = ab[ab["id"] == esc].iloc[0]
                if pd.notna(reg.get("historico")):
                    st.caption("Histórico: " + str(reg["historico"]).replace("\n", " · "))
                form_nc(reg, f"ed_{esc}")
                with st.expander("🚫 Cancelar este registro"):
                    st.caption("Cancelar não apaga: o registro fica no sistema com o motivo, mas não conta em indicador "
                               "e não aparece para a oficina. Use para duplicidades, registros por engano ou testes.")
                    mot_c = st.text_input("Motivo do cancelamento", key=f"mot_c_{esc}")
                    if st.button("Cancelar registro", key=f"canc_{esc}", disabled=not mot_c.strip()):
                        r_ = reg.to_dict()
                        r_["historico"] = ((r_.get("historico") or "") + f"\n{agora()} — cancelado: {mot_c.strip()}").strip()
                        r_["status"] = "Cancelada"
                        for c_ in ("data", "data_analise"):
                            r_[c_] = str(pd.to_datetime(r_[c_]).date()) if pd.notna(r_.get(c_)) else None
                        r_.pop("dias", None)
                        banco.salvar_nc(r_)
                        st.session_state["msg_nc"] = f"{esc} cancelado (continua no histórico)."
                        st.rerun()
    with aba[1]:
        form_nc(None, "novo")
    with aba[2]:
        if ncs.empty:
            st.info("Nenhuma não conformidade registrada.")
        else:
            ver_canc = st.toggle("Mostrar cancelados", value=False, key="nc_ver_canc")
            vis = {"Procedente": "Sim, com relato e análise", "Improcedente": "Só a contagem (sem detalhes)",
                   "Em análise": "Não (ainda em análise)", "Cancelada": "Não"}
            base_l = ncs if ver_canc else ncs[ncs["status"] != "Cancelada"]
            lst = base_l.assign(visivel=base_l["status"].map(vis)).sort_values("data", ascending=False)[
                ["id", "data", "oficina", "tecnico", "os", "cliente", "canal", "motivo", "status", "visivel", "reeditada",
                 "descricao", "analise", "evidencias", "historico"]]
            lst = lst.rename(columns={"id": "Registro", "data": "Data", "oficina": "Oficina", "tecnico": "Técnico", "os": "OS",
                                      "cliente": "Cliente", "canal": "Canal", "motivo": "Motivo", "status": "Situação",
                                      "reeditada": "Reaberta", "visivel": "Visível para a oficina",
                                      "descricao": "Relato do cliente", "analise": "Análise",
                                      "evidencias": "Evidências", "historico": "Histórico"})
            st.dataframe(lst, hide_index=True, width="stretch", column_config={"Data": st.column_config.DateColumn(format="DD/MM/YYYY")})
            st.download_button("⬇️ Baixar em Excel", para_excel(lst), "nao_conformidades.xlsx")
            fechadas = ncs[ncs["status"].isin(["Procedente", "Improcedente"])]
            if not fechadas.empty:
                with st.expander("🔓 Reabrir uma reclamação concluída (para correção)"):
                    st.caption("Concluídas não são editadas direto. Para corrigir (ex.: faltou uma evidência), reabra com uma "
                               "justificativa: ela volta para Em análise, fica marcada como Reaberta e tudo fica no histórico.")
                    r_id = st.selectbox("Reclamação", fechadas["id"].tolist(), key="nc_reabrir",
                                        format_func=lambda i: f"{i} · {fechadas.set_index('id').loc[i, 'oficina']} · {fechadas.set_index('id').loc[i, 'status']}")
                    just = st.text_input("Motivo da reabertura", key="nc_just")
                    if st.button("Reabrir", disabled=not just.strip()):
                        reg = fechadas[fechadas["id"] == r_id].iloc[0].to_dict()
                        reg["historico"] = ((reg.get("historico") or "") + f"\n{agora()} — reaberta (estava {reg['status']}): {just.strip()}").strip()
                        reg["status"], reg["reeditada"] = "Em análise", "Sim"
                        for c_ in ("data", "data_analise"):
                            reg[c_] = str(pd.to_datetime(reg[c_]).date()) if pd.notna(reg.get(c_)) else None
                        banco.salvar_nc(reg)
                        st.session_state["msg_nc"] = f"{r_id} reaberta. Está na aba Em análise."
                        st.rerun()
            canceladas = ncs[ncs["status"] == "Cancelada"]
            if not canceladas.empty and eh_admin():
                with st.expander("🗑️ Excluir definitivamente um registro cancelado (administração)"):
                    st.caption("Só para limpar registros de teste ou feitos por engano. Esta ação não deixa rastro.")
                    d_id = st.selectbox("Registro cancelado", canceladas["id"].tolist(), key="nc_del")
                    conf = st.checkbox("Confirmo a exclusão definitiva", key="nc_del_conf")
                    if st.button("Excluir definitivamente", disabled=not conf):
                        banco.excluir_nc(d_id)
                        st.session_state["msg_nc"] = f"{d_id} excluído definitivamente."
                        st.rerun()
    with aba[3]:
        if ncs.empty:
            st.info("Nenhuma não conformidade registrada.")
        else:
            ncv = ncs[ncs["status"] != "Cancelada"].copy()
            r_ = ncv.pivot_table(index="oficina", columns="status", values="id", aggfunc="count", fill_value=0)
            for c_ in ("Procedente", "Improcedente", "Em análise"):
                if c_ not in r_.columns:
                    r_[c_] = 0
            r_["Total de apontamentos"] = r_[["Procedente", "Improcedente", "Em análise"]].sum(axis=1)
            st.markdown("**Por oficina** (cancelados não entram)")
            st.caption("Procedentes contam no indicador da oficina. Improcedentes não contam, mas ficam registradas: "
                       "mostram quantas vezes a oficina foi apontada.")
            st.dataframe(r_[["Total de apontamentos", "Procedente", "Improcedente", "Em análise"]]
                         .sort_values("Total de apontamentos", ascending=False), width="stretch")
            ncs = ncv
            c1, c2 = st.columns(2)
            with c1:
                barras(ncs[ncs["status"] != "Improcedente"], "motivo", "Motivos (procedentes + em análise)")
            with c2:
                barras(ncs[ncs["status"] != "Improcedente"].assign(tec=lambda d: d["tecnico"].fillna("Não informado")),
                       "tec", "Técnicos (procedentes + em análise)")


# ---------------------------------------------------------------- dados
elif area == "📥 Dados":
    oficinas = oficinas_todas  # importações e cadastro sempre com todas as oficinas (credenciadas e próprias)
    st.title("Dados")
    if banco.usando_nuvem():
        st.success("Banco na nuvem conectado. As bases ficam salvas.")
    else:
        st.warning("Usando banco local (arquivo dados_painel.db). Bom para testar; na nuvem configure o db_url.")
    st.caption("🔒 Só as colunas usadas pelo painel são gravadas (OS, ticket, placa, oficina, status, tipo, data, "
               "razão e observação da improdutiva, técnico). Cliente, endereço, telefone e e-mail são descartados na leitura.")

    def regiao(df):
        """Descarta as oficinas fora da região antes de gravar e mostra a conferência por oficina."""
        # resultado e planejado da rede: só oficinas credenciadas (próprias têm a aba Oficinas próprias)
        filtrado = regras.filtrar_regiao(df, oficinas_todas[oficinas_todas["tipo"] == "Credenciada"], ufs_regiao)
        if ufs_regiao:
            st.caption(f"Região {', '.join(ufs_regiao)}: {len(filtrado)} de {len(df)} atividades do arquivo serão "
                       f"importadas. As demais oficinas do Brasil são descartadas.")
            conferir_regiao(df)
        if filtrado.empty:
            raise ValueError("Nenhuma atividade da sua região neste arquivo. Confira o cadastro de oficinas e a "
                             "região em Configurações.")
        return filtrado

    def conferir_regiao(df):
        ufs = [u.upper() for u in ufs_regiao]
        d = df.assign(uf_painel=regras.uf_da_atividade(df, oficinas))
        cad = dict(zip(oficinas["id"].astype(str), oficinas["uf_base"].fillna("")))
        resumo = (d.groupby(["id_oficina", "oficina"], dropna=False)
                  .agg(atividades=("os", "count"), uf_painel=("uf_painel", "first"),
                       ufs_atendimento=("uf_cliente", lambda s: ", ".join(sorted(s.dropna().unique()))))
                  .reset_index())
        resumo["uf_cadastro"] = resumo["id_oficina"].astype(str).map(cad).fillna("não cadastrada")
        resumo["entra"] = resumo["uf_painel"].isin(ufs)
        entram = resumo[resumo["entra"]]
        suspeitas = resumo[~resumo["entra"] & resumo["ufs_atendimento"].str.contains("|".join(ufs) or "^$")]
        nomes = {"id_oficina": "ID", "oficina": "Oficina", "atividades": "Atividades", "uf_cadastro": "UF-base no cadastro",
                 "ufs_atendimento": "UF dos atendimentos"}
        cols = ["id_oficina", "oficina", "atividades", "uf_cadastro", "ufs_atendimento"]
        with st.expander(f"Conferir oficinas: {len(entram)} entram no painel"
                         + (f" · {len(suspeitas)} descartadas com atendimento na região" if len(suspeitas) else "")):
            st.dataframe(entram[cols].rename(columns=nomes), hide_index=True, width="stretch")
            if len(suspeitas):
                st.warning("Estas oficinas foram descartadas, mas atenderam clientes na sua região. Se forem suas, "
                           "corrija a UF-base delas no cadastro (o ID tem que ser igual ao do arquivo).")
                st.dataframe(suspeitas[cols].rename(columns=nomes), hide_index=True, width="stretch")
            sem = oficinas[oficinas["uf_base"].fillna("").str.upper().isin(ufs)
                           & ~oficinas["id"].astype(str).isin(resumo["id_oficina"].astype(str))]
            if len(sem):
                st.info("Oficinas da sua região no cadastro que não têm nenhuma atividade neste arquivo: "
                        + ", ".join(sem["oficina"].fillna(sem["id"]).astype(str)))

    if oficinas.empty:
        st.warning("Importe primeiro o cadastro de oficinas (aba Oficinas). É por ele que o painel sabe quais "
                   "oficinas são da sua região.")
    aba = st.tabs(["Resultado", "Planejado", "Oficinas", "Oficinas próprias", "Retrabalho", "Financeiro", "Bases salvas"])

    with aba[0]:
        st.write("Exportação do dia (ou de vários dias). Se já existir resultado da mesma data, ele é substituído.")
        arq = st.file_uploader("Arquivo de resultado", type=["csv", "xlsx"], key="up_res")
        if arq and "propria" in rt.sem_acento(arq.name):
            st.error("Este é o arquivo das **oficinas próprias**. Ele vai na aba **Oficinas próprias**, não aqui: "
                     "importar aqui substituiria o resultado da rede deste dia.")
            arq = None
        if arq:
            d1, d2 = datas_do_nome(arq.name)
            if d2:
                st.error(f"O nome do arquivo tem duas datas ({d1:%d/%m} a {d2:%d/%m}): é um **planejado**. "
                         "Importação bloqueada: use a aba Planejado.")
                arq = None
            if arq:
                try:
                    df = regiao(regras.preparar_atividades(regras.ler_arquivo(arq)))
                    datas = sorted(df["data"].unique())
                    if len(datas) == 1:
                        data_op = st.date_input("Data operacional do resultado", datas[0], format="DD/MM/YYYY",
                                                help="Já vem preenchida com a data das atividades do arquivo.")
                        if data_op != datas[0]:
                            st.warning(f"As atividades do arquivo são de **{datas[0]:%d/%m/%Y}**, mas você escolheu "
                                       f"**{data_op:%d/%m/%Y}**. Elas serão gravadas como {data_op:%d/%m/%Y}. "
                                       "Confira se é isso mesmo antes de importar.")
                            df = df.assign(data=data_op)
                            datas = [data_op]
                    else:
                        st.info("Este arquivo tem atividades de mais de um dia: "
                                + ", ".join(f"{d:%d/%m/%Y}" for d in datas) + ". Cada dia é gravado na sua data.")
                    st.write(f"**{len(df)} atividades** da região.")
                    st.dataframe(df["familia"].value_counts().rename("Atividades"), width="content")
                    if st.button("Importar resultado", type="primary"):
                        for d in datas:
                            banco.salvar_base("resultado", d, df[df["data"] == d], arq.name)
                        st.success("Resultado importado.")
                except ValueError as e:
                    st.error(str(e))

    with aba[1]:
        st.write("Exportação com as datas futuras (normalmente 3 dias à frente). Para cada dia, o painel usa o "
                 "planejado mais recente importado até aquele dia.")
        arq = st.file_uploader("Arquivo de planejado", type=["csv", "xlsx"], key="up_pla")
        if arq and "propria" in rt.sem_acento(arq.name):
            st.error("Este é o arquivo das **oficinas próprias**: use a aba **Oficinas próprias**.")
            arq = None
        d1, d2 = datas_do_nome(arq.name) if arq else (None, None)
        ref = st.date_input("Data da exportação", d1 or date.today(), format="DD/MM/YYYY",
                            help="Dia em que você baixou o planejado (vem da primeira data do nome do arquivo). "
                                 "Importar de novo na mesma data substitui.")
        if arq and d1 and not d2:
            st.error(f"O nome do arquivo tem uma data só ({d1:%d/%m}): é um **resultado**, não um planejado. "
                     "O planejado tem duas datas no nome (ex.: Spot_22_10_26-24_10_26). Importação bloqueada para não "
                     f"substituir o planejado de {ref:%d/%m}: use a aba Resultado.")
            arq = None
        imps_ = banco.carregar_importacoes()
        if arq and not imps_.empty:
            ja = imps_[(imps_["tipo_base"] == "planejado") & (imps_["data_ref"].astype(str) == str(ref))]
            if not ja.empty and ja["arquivo"].iloc[0] != arq.name:
                st.warning(f"Já existe um planejado com data {ref:%d/%m/%Y} (**{ja['arquivo'].iloc[0]}**). "
                           "Importar este arquivo vai substituí-lo.")
        if arq:
            try:
                df = regiao(regras.preparar_atividades(regras.ler_arquivo(arq)))
                datas = sorted(df["data"].unique())
                st.write(f"**{len(df)} atividades** da região, de {datas[0]:%d/%m/%Y} a {datas[-1]:%d/%m/%Y}.")
                if any(d < ref for d in datas):
                    st.info("O arquivo tem datas anteriores à data da exportação; elas não serão usadas como planejado.")
                if st.button("Importar planejado", type="primary"):
                    banco.salvar_base("planejado", ref, df, arq.name)
                    st.success("Planejado importado.")
            except ValueError as e:
                st.error(str(e))

    with aba[2]:
        st.write("Cadastro mestre: liga cada oficina (pelo ID) ao consultor e à UF-base.")
        arq = st.file_uploader("Importar cadastro de oficinas", type=["csv", "xlsx", "ods"], key="up_of")
        if arq:
            bruto = regras.ler_arquivo(arq)
            mapa = {"id": "id", "iddaoficina": "id", "idoficina": "id", "oficina": "oficina", "nome": "oficina",
                    "cidadebase": "cidade_base", "cidade": "cidade_base", "ufbase": "uf_base", "uf": "uf_base",
                    "estado": "uf_base", "consultor": "consultor", "prioridade": "prioridade", "ativa": "ativa",
                    "observacao": "observacao", "observacoes": "observacao", "tecnicos": "tecnicos",
                    "ntecnicos": "tecnicos", "qtdtecnicos": "tecnicos", "quantidadedetecnicos": "tecnicos"}
            ren = {}
            for c in bruto.columns:
                alvo = mapa.get(norm(c))
                if alvo and alvo not in ren.values():
                    ren[c] = alvo
            novo = bruto.rename(columns=ren)
            for c in banco.COLS_OFICINA:
                if c not in novo.columns:
                    novo[c] = None
            if novo["id"].isna().all():
                st.error("Não encontrei a coluna de ID da oficina no arquivo.")
            else:
                novo["id"] = novo["id"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
                ja_ids = set(oficinas_todas["id"].astype(str))
                n_novas = int((~novo["id"].isin(ja_ids)).sum())
                st.write(f"{novo['id'].notna().sum()} oficinas no arquivo · **{n_novas} novas** · "
                         f"{len(novo) - n_novas} já estão no cadastro.")
                modo_cad = st.radio("Como importar", ["Acrescentar só as oficinas novas (mantém as já cadastradas)"]
                                    + (["Substituir o cadastro inteiro pelo arquivo"] if eh_admin() else []),
                                    help="Acrescentar preserva o que você já preencheu (nº de técnicos, contrato, preço fixo, "
                                         "outros nomes, inativas, próprias). Substituir apaga e grava só o arquivo.")
                if st.button("Importar cadastro", type="primary"):
                    if modo_cad.startswith("Acrescentar"):
                        banco.salvar_oficinas(pd.concat([oficinas_todas, novo[~novo["id"].isin(ja_ids)]], ignore_index=True))
                    else:
                        banco.salvar_oficinas(novo)
                    st.success("Cadastro atualizado.")
                    st.rerun()

        faltam = pd.DataFrame()
        if not ativ.empty:
            vistas = ativ.dropna(subset=["id_oficina"]).drop_duplicates("id_oficina")[["id_oficina", "oficina"]]
            faltam = vistas[~vistas["id_oficina"].isin(oficinas["id"])]
        if not faltam.empty:
            st.warning(f"{len(faltam)} oficina(s) aparecem nas bases e não estão no cadastro (ficam como 'Sem cadastro').")
            if st.button("Incluir essas oficinas no cadastro para eu completar"):
                extra = faltam.rename(columns={"id_oficina": "id"}).assign(ativa="Sim", prioridade="Normal")
                banco.salvar_oficinas(pd.concat([oficinas, extra], ignore_index=True))
                st.rerun()

        st.subheader("Editar cadastro")
        busca = st.text_input("Pesquisar oficina")
        vis = oficinas[oficinas["oficina"].fillna("").str.contains(busca, case=False)] if busca else oficinas
        editado = st.data_editor(vis, num_rows="dynamic", hide_index=True, width="stretch",
                                 column_config={"id": "ID", "oficina": "Oficina", "cidade_base": "Cidade-base",
                                                "outros_nomes": st.column_config.TextColumn("Outros nomes",
                                                    help="Outros nomes com que a mesma oficina aparece nas planilhas, separados por ponto e vírgula (;)."),
                                                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Credenciada", "Própria"],
                                                    help="Própria: oficina do próprio cliente (mesmo nome do cliente)."),
                                                "contrato": st.column_config.SelectboxColumn("Contrato", options=["Tabela", "Preço fixo"],
                                                    help="Tabela: serviço + KM + despesas. Preço fixo: valor único por serviço, com KM e despesas inclusos."),
                                                "valor_fixo": st.column_config.NumberColumn("Valor fixo (R$)", min_value=0, format="R$ %.2f",
                                                    help="Só para contrato de preço fixo."),
                                                "inicio_fixo": st.column_config.DateColumn("Preço fixo desde", format="DD/MM/YYYY",
                                                    help="Data em que começou o preço fixo. Antes dela, as OS contam como tabela."),
                                                "tecnicos": st.column_config.NumberColumn("Nº de técnicos", min_value=0, step=1,
                                                    help="Usado na capacidade. Em branco = estimado pelos técnicos que aparecem nas OS."),
                                                "uf_base": "UF-base", "consultor": "Consultor",
                                                "prioridade": "Prioridade", "ativa": "Ativa", "observacao": "Observação"})
        if st.button("Salvar alterações do cadastro"):
            resto = oficinas[~oficinas.index.isin(vis.index)]
            banco.salvar_oficinas(pd.concat([resto, editado], ignore_index=True))
            st.success("Cadastro salvo.")
            st.rerun()

    with aba[3]:
        st.write("Exportação do sistema **só com as oficinas próprias** (mesmo formato do arquivo de atividades). Serve "
                 "para contar os serviços que elas fizeram: não entra nos indicadores da rede nem no financeiro. Pode "
                 "subir uma semana ou um mês de uma vez; reimportar um dia substitui só aquele dia das próprias.")
        arq = st.file_uploader("Arquivo das oficinas próprias", type=["csv", "xlsx"], key="up_prop")
        if arq and "spot" in rt.sem_acento(arq.name):
            st.error("Este parece ser o arquivo da **rede** (Spot). Resultado vai na aba **Resultado** e planejado na aba **Planejado**.")
            arq = None
        if arq:
            try:
                bruto_p = regras.ler_arquivo(arq)
                dfp = regras.preparar_atividades(bruto_p)
                achar = achar_id_fn()
                ids_prop = set(oficinas_todas.loc[oficinas_todas["tipo"] == "Própria", "id"].astype(str))
                # liga pelo ID do sistema e, se não achar, pelo nome (inclui \u201coutros nomes\u201d)
                dfp["id_oficina"] = [i if str(i) in ids_prop else (achar(n) or i) for i, n in zip(dfp["id_oficina"], dfp["oficina"])]
                dentro = dfp[dfp["id_oficina"].astype(str).isin(ids_prop)]
                fora = dfp[~dfp.index.isin(dentro.index)]
                if not fora.empty:
                    uf_f = fora.groupby("oficina")["uf_cliente"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else "")
                    reg_f = fora.groupby("oficina")["uf_cliente"].agg(lambda s: s.isin(ufs_regiao).mean() if ufs_regiao else 1)
                    cand = pd.DataFrame({"OS": fora.groupby("oficina").size(), "UF": uf_f, "na_reg": reg_f,
                                         "id": fora.groupby("oficina")["id_oficina"].first()}).reset_index()
                    cand = cand[cand["na_reg"] >= 0.5]
                    if not cand.empty:
                        with st.container(border=True):
                            st.markdown("**Oficinas próprias do arquivo que ainda não estão no cadastro** (atendendo na sua região)")
                            st.dataframe(cand.drop(columns="na_reg").rename(columns={"oficina": "Oficina", "id": "ID"}),
                                         hide_index=True, width="stretch")
                            add = st.multiselect("Incluir no cadastro como próprias", cand["oficina"].tolist(),
                                                 default=cand["oficina"].tolist(), key="prop_add")
                            if add and st.button("Incluir no cadastro"):
                                consultor_pad = oficinas_todas["consultor"].dropna().mode().iat[0] if oficinas_todas["consultor"].notna().any() else None
                                c_ = cand.set_index("oficina")
                                # se já existir uma própria com nome parecido (criada pelo financeiro), só acrescenta o ID ao nome
                                novas = pd.DataFrame([{"id": str(c_.loc[n, "id"]), "oficina": n, "tipo": "Própria",
                                                       "uf_base": c_.loc[n, "UF"], "consultor": consultor_pad, "ativa": "Sim",
                                                       "contrato": "Tabela", "observacao": "Oficina própria do cliente"} for n in add])
                                banco.salvar_oficinas(pd.concat([oficinas_todas, novas], ignore_index=True))
                                st.success("Incluídas. Suba o arquivo de novo para gravar.")
                                st.rerun()
                datas = sorted(dentro["data"].unique())
                st.write(f"**{len(dentro)} atividades** das suas oficinas próprias"
                         + (f", de {datas[0]:%d/%m/%Y} a {datas[-1]:%d/%m/%Y}." if datas else "."))
                if not datas:
                    dias_arq = sorted(dfp["data"].unique())
                    st.info(f"O arquivo tem {len(dfp)} atividade(s) de oficinas próprias de **outras regiões** "
                            + (f"({', '.join(f'{d:%d/%m}' for d in dias_arq)})" if dias_arq else "")
                            + " e nenhuma da sua. Não é erro: nesse dia as próprias da sua região não tiveram atendimento.")
                if datas:
                    st.dataframe(dentro.groupby("oficina")["status"].value_counts().unstack(fill_value=0), width="stretch")
                    if st.button("Importar oficinas próprias", type="primary"):
                        for d in datas:
                            banco.salvar_base("proprias", d, dentro[dentro["data"] == d], arq.name)
                        st.success("Importado. Veja em 🏠 Oficinas próprias.")
            except ValueError as e:
                st.error(str(e) + " Se o arquivo das próprias tiver outro formato, mande uma amostra para ajustarmos.")

    with aba[4]:
        st.write("Base mensal de retrabalho do administrativo (uma linha por visita: 1ª visita e Retorno de cada caso). "
                 "Pode subir o mês ou o ano inteiro: casos repetidos são atualizados, e as análises que você já "
                 "fez são mantidas.")
        arq = st.file_uploader("Arquivo de retrabalho", type=["xlsx", "csv"], key="up_rt")
        if arq:
            try:
                bruto_r = regras.ler_arquivo(arq)
                if "Cliente" in bruto_r.columns:
                    bloco_proprias(regras.sugerir_proprias(bruto_r["Oficina"], bruto_r["Cliente"],
                                                           bruto_r.get("UF", pd.Series("", index=bruto_r.index)), ufs_regiao), "rt")
                casos_novos = rt.montar_casos(bruto_r)
                tri = regiao_retrabalho(rt.triar(casos_novos, cfg_rt, obs_ofs))
                st.write(f"**{len(casos_novos)} casos** no arquivo; **{len(tri)}** da sua região "
                         f"({', '.join(sorted(casos_novos['competencia'].dropna().unique()))}).")
                fora = sorted(set(casos_novos["oficina"].dropna()) - set(tri["oficina"].dropna()))
                if fora:
                    with st.expander(f"{len(fora)} oficina(s) descartadas (fora do cadastro da região)"):
                        st.write(", ".join(fora))
                st.dataframe(tri["decisao_auto"].value_counts().rename("Casos"), width="content")
                if st.button("Importar retrabalho", type="primary"):
                    banco.salvar_casos_retrabalho(casos_novos[casos_novos["id_caso"].isin(tri["id_caso"])])
                    st.success("Base de retrabalho importada. Vá em 🔁 Retrabalho para analisar os pendentes.")
            except ValueError as e:
                st.error(str(e))
        if not casos_rt.empty and eh_admin() and st.checkbox("Quero apagar toda a base de retrabalho (inclusive as análises)"):
            if st.button("Apagar base de retrabalho"):
                banco.excluir_retrabalho()
                st.rerun()

    with aba[5]:
        st.write("Planilha de pagamento das oficinas. Pode subir vários meses e importar de novo quando quiser: **nada é "
                 "apagado nem duplicado** (cada OS é identificada pelo protocolo). Só as oficinas da sua região são "
                 "gravadas; nome de cliente não é gravado.")
        arq = st.file_uploader("Planilha de pagamento ou Consolidado", type=["xlsx", "csv"], key="up_fin")
        if arq:
            try:
                fbr = fin.preparar(regras.ler_arquivo(arq))
                freg = na_regiao(fbr)
                # oficinas do arquivo que não estão no cadastro, mas atenderam principalmente na região
                bruto_f = regras.ler_arquivo(arq)
                col_of = "Planilha Origem" if "Planilha Origem" in bruto_f.columns else "Oficina"
                if "Cliente" in bruto_f.columns:
                    uf_f = (bruto_f["Cidade/UF"].astype(str).str.split("/").str[-1] if "Cidade/UF" in bruto_f.columns else
                            bruto_f["UF"] if "UF" in bruto_f.columns else bruto_f.get("Cidade", pd.Series("", index=bruto_f.index)).astype(str).str.split(" - ").str[-1])
                    sug_p = regras.sugerir_proprias(bruto_f[col_of], bruto_f["Cliente"], uf_f.str.strip(), ufs_regiao)
                    bloco_proprias(sug_p, "fin")
                else:
                    sug_p = pd.DataFrame(columns=["oficina"])
                fora = fbr[~fbr.index.isin(freg.index) & ~fbr["oficina"].isin(sug_p["oficina"])].copy()
                if not fora.empty:
                    fora["uf_at"] = fora["cidade_uf"].fillna("").str.split("/").str[-1].str.strip().str.upper()
                    achar = achar_id_fn()
                    fora = fora[fora["oficina"].map(achar).isna()]
                    sug = fora.groupby("oficina").agg(OS=("os", "count"),
                                                      na_regiao=("uf_at", lambda s: s.isin(ufs_regiao).mean() if ufs_regiao else 1.0),
                                                      uf=("uf_at", lambda s: s.mode().iat[0] if len(s.mode()) else ""),
                                                      de=("data", "min"), ate=("data", "max")).reset_index()
                    sug = sug[sug["na_regiao"] >= 0.5].sort_values("OS", ascending=False)
                    if not sug.empty:
                        with st.container(border=True):
                            st.markdown("**Oficinas do arquivo que não estão no cadastro**" + (" (atenderam na sua região)" if ufs_regiao else ""))
                            if not ufs_regiao:
                                uf_f = st.multiselect("Filtrar pela UF principal", sorted(sug["uf"].unique()), key="inat_uf",
                                                      placeholder="Todas as UFs")
                                if uf_f:
                                    sug = sug[sug["uf"].isin(uf_f)]
                            st.caption("Marque as que eram (ou são) suas: elas entram no cadastro como **inativas** e o histórico "
                                       "delas passa a contar. Deixe desmarcadas as oficinas próprias de clientes e as de outros consultores.")
                            st.dataframe(sug.assign(**{"% na região": (sug["na_regiao"] * 100).round(0)}).drop(columns="na_regiao")
                                         .rename(columns={"oficina": "Oficina", "uf": "UF principal", "de": "Primeira OS", "ate": "Última OS"}),
                                         hide_index=True, width="stretch")
                            marcar = st.multiselect("Incluir como oficinas inativas da região", sug["oficina"].tolist(), key="inativas_sel")
                            juntar = st.checkbox("Os nomes marcados são da **mesma oficina** (juntar em uma só)", key="inativas_juntar")
                            nome_final = st.text_input("Nome da oficina", marcar[0] if marcar else "", key="inativas_nome") if juntar else None
                            cons_op = CONSULTORES or ["(sem consultor)"]
                            consultor_inat = st.selectbox("Consultor responsável pela região dessas oficinas", cons_op, key="inat_cons",
                                                          index=cons_op.index(consultor_ver) if consultor_ver in cons_op else 0)
                            if marcar and st.button("Adicionar ao cadastro como inativas"):
                                consultor_pad = consultor_inat if consultor_inat != "(sem consultor)" else None
                                if juntar:
                                    nome_f = (nome_final or marcar[0]).strip()
                                    novas = pd.DataFrame([{"id": "INAT-" + compacto(nome_f)[:30], "oficina": nome_f,
                                                           "outros_nomes": "; ".join(n for n in marcar if n != nome_f),
                                                           "uf_base": sug.set_index("oficina").loc[marcar[0], "uf"],
                                                           "consultor": consultor_pad, "ativa": "Não", "contrato": "Tabela",
                                                           "observacao": "Incluída pelo histórico do financeiro"}])
                                else:
                                    novas = pd.DataFrame([{"id": "INAT-" + compacto(n)[:30], "oficina": n,
                                                           "uf_base": sug.set_index("oficina").loc[n, "uf"], "consultor": consultor_pad,
                                                           "ativa": "Não", "contrato": "Tabela",
                                                           "observacao": "Incluída pelo histórico do financeiro"} for n in marcar])
                                banco.salvar_oficinas(pd.concat([oficinas_todas, novas], ignore_index=True))
                                st.success(f"{len(marcar)} oficina(s) incluída(s) como inativas. Agora clique em Importar financeiro.")
                                st.rerun()
                st.write(f"**{len(fbr)} OS** no arquivo; **{len(freg)}** das suas oficinas · meses: "
                         + ", ".join(f"{m[5:]}/{m[:4]}" for m in sorted(freg["mes"].unique())))
                sem = sorted(set(fbr.loc[~fbr.index.isin(freg.index), "oficina"].dropna()))
                if freg["oficina_cad"].isna().any():
                    st.warning("Algumas linhas não foram ligadas ao cadastro.")
                st.dataframe(freg.groupby("oficina_cad").agg(OS=("os", "count"), Total=("total_pagar", "sum"))
                             .rename_axis("Oficina"), width="content",
                             column_config={"Total": st.column_config.NumberColumn(format="R$ %.0f")})
                st.caption("Planilha reconhecida: **" + ("Consolidado (mês fechado)" if fbr["fonte"].iloc[0] == "consolidado"
                           else "Auditoria de pagamento (pode estar em aberto)") + "**. O Consolidado sempre vale mais: "
                           "ele substitui os dados provisórios da auditoria da mesma OS, e a auditoria nunca substitui o Consolidado.")
                atual_f = banco.carregar_financeiro()
                ja = set(atual_f["os"].astype(str)) if not atual_f.empty else set()
                novas = freg[~freg["os"].astype(str).isin(ja)]
                existentes = freg[freg["os"].astype(str).isin(ja)]
                mudaram = 0
                if not existentes.empty:
                    cmp = existentes.set_index(existentes["os"].astype(str))
                    ant = atual_f.set_index(atual_f["os"].astype(str)).reindex(cmp.index)
                    dif_num = (cmp[fin.NUM].astype(float).round(2) - ant[fin.NUM].apply(pd.to_numeric, errors="coerce").round(2)).abs() > 0.01
                    dif_st = cmp["status_pagamento"].fillna("").astype(str) != ant["status_pagamento"].fillna("").astype(str)
                    mudaram = int((dif_num.any(axis=1) | dif_st).sum())
                st.markdown(f"**{len(novas)}** OS novas · **{len(existentes)}** já estão no painel"
                            + (f" (**{mudaram}** com valores ou status diferentes no arquivo novo)" if len(existentes) else ""))
                modo_imp = st.radio("Como importar", ["Só acrescentar as OS novas (mantém as que já estão)",
                                                      "Acrescentar as novas e atualizar as que mudaram"],
                                    help="Nada é apagado nos dois casos. Use a segunda opção depois do fechamento, "
                                         "quando o administrativo corrigir valores ou validar pagamentos.")
                if st.button("Importar financeiro", type="primary"):
                    n_ = banco.salvar_financeiro(freg.drop(columns=["uf_base", "oficina_cad"]),
                                                 atualizar_existentes=modo_imp.startswith("Acrescentar as novas e"))
                    st.success(f"Financeiro importado: {n_} OS gravadas. Veja em 💰 Financeiro.")
            except ValueError as e:
                st.error(str(e))

    with aba[6]:
        imps = banco.carregar_importacoes()
        if imps.empty:
            st.info("Nenhuma base importada ainda.")
        else:
            st.dataframe(imps.rename(columns={"tipo_base": "Tipo", "data_ref": "Data", "linhas": "Atividades",
                                              "arquivo": "Arquivo", "importado_em": "Importado em"}),
                         hide_index=True, width="stretch")
            opcoes = [f"{r.tipo_base} | {r.data_ref}" for r in imps.itertuples()]
            alvo = st.selectbox("Excluir uma base", ["—"] + opcoes, disabled=not eh_admin(),
                                help=None if eh_admin() else "Só o administrador pode excluir bases.")
            if alvo != "—" and eh_admin() and st.button("Excluir base selecionada"):
                t, d = alvo.split(" | ")
                banco.excluir_base(t, d)
                st.rerun()


# ---------------------------------------------------------------- configurações
else:
    st.title("Configurações")
    if not eh_admin():
        pedir_admin("Configurações")
        st.stop()
    st.subheader("Região do painel")
    st.caption("Só entram no painel as oficinas do cadastro cuja UF-base está nesta lista. **Deixe vazio para o Brasil "
               "inteiro** (todas as oficinas do cadastro, de todos os consultores; cada um filtra a sua pelo seletor "
               "👤 Consultor). Oficinas fora do cadastro ficam sempre de fora.")
    todas_ufs = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
                 "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
    ufs_sel = st.multiselect("UFs da região", todas_ufs, default=ufs_regiao, placeholder="Brasil inteiro")
    if st.button("Salvar região", type="primary"):
        banco.salvar_config("ufs_regiao", ufs_sel)
        st.cache_data.clear()
        st.success("Região salva.")
        st.rerun()

    st.subheader("Regras automáticas de retrabalho")
    st.caption("Regra base: retorno ao mesmo veículo dentro da janela = retrabalho. As listas abaixo são as exceções. "
               "Os termos são procurados sem diferenciar maiúsculas e acentos; um termo por linha. Sinistro e equipamento "
               "são procurados na observação do técnico que vem do CSV diário do sistema (cruzada pelo número da OS).")
    j = st.number_input("Janela de retrabalho (dias)", 1, 365, int(cfg_rt["janela_dias"]))
    c1, c2 = st.columns(2)
    t_terc = c1.text_area("Sinistro / terceiro na observação do técnico → expurga", "\n".join(cfg_rt["termos_terceiro"]), height=200)
    t_eq = c2.text_area("Defeito / troca de equipamento na observação do técnico → expurga", "\n".join(cfg_rt["termos_equipamento"]), height=200)
    c3, c4 = st.columns(2)
    t_peca = c3.text_area("Peça faltante / kit incompleto (após instalação, reinstalação ou renovação) → expurga",
                          "\n".join(cfg_rt["termos_peca"]), height=180)
    t_rev = c4.text_area("Sinais que mandam para revisão com destaque", "\n".join(cfg_rt["termos_revisar"]), height=180)
    d_peca = st.number_input("Peça faltante: retorno em até (dias)", 0, 90, int(cfg_rt["dias_peca"]))
    if st.button("Salvar regras de retrabalho", type="primary"):
        linhas = lambda t: [x.strip() for x in t.splitlines() if x.strip()]
        banco.salvar_config("regras_retrabalho", {"janela_dias": int(j), "termos_terceiro": linhas(t_terc),
                                                  "termos_equipamento": linhas(t_eq), "termos_peca": linhas(t_peca),
                                                  "termos_revisar": linhas(t_rev), "dias_peca": int(d_peca)})
        st.cache_data.clear()
        st.success("Regras salvas. A triagem é refeita na hora com as regras novas.")
        st.rerun()
    st.markdown("**Ordem das regras:** 1) duplicidade (o retorno já é a 1ª visita de outro caso) → expurga · "
                "2) retorno é retirada → expurga · 3) fora da janela → expurga · 4) sinistro/terceiro na observação → "
                "expurga · 5) troca/defeito de equipamento na observação → expurga · 6) peça faltante após serviço "
                "inicial → expurga · 7) sinal para revisar → análise · 8) sem observação do técnico no painel → análise · "
                "9) o resto → retrabalho.")

    st.subheader("Metas de eficiência")
    me = {**ef.METAS_PADRAO, **banco.ler_config("metas_eficiencia", {})}
    e = st.columns(4)
    n_ns = e[0].number_input("Nível de serviço (até 7 dias) — mín. %", 0, 100, int(me["nivel_servico"]))
    n_imp = e[1].number_input("Improdutividade — máx. %", 0, 100, int(me["improdutividade"]))
    n_ret = e[2].number_input("Retrabalho — máx. %", 0, 100, int(me["retrabalho"]))
    n_aud = e[3].number_input("Auditoria — mín. % de aprovação", 0, 100, int(me["auditoria"]))
    e = st.columns(4)
    n_sin = e[0].number_input("Apontamento de sinistro — mín. %", 0, 100, int(me["sinistro"]))
    n_omin = e[1].number_input("Ocupação ideal — de %", 0, 200, int(me["ocupacao_min"]))
    n_omax = e[2].number_input("Ocupação ideal — até %", 0, 200, int(me["ocupacao_max"]))
    n_sla = e[3].number_input("SLA de agendamento — mín. %", 0, 100, int(me["sla"]))
    e = st.columns(4)
    n_nc = e[0].number_input("Não conformidades — máx. por mês", 0, 100, int(me["nao_conf"]))
    n_ns2 = e[1].number_input("No show — máx. por mês", 0, 100, int(me["no_show"]))
    n_tme = e[2].number_input("TME — máx. dias", 0, 90, int(me["tme"]))
    n_tma = e[3].number_input("Ticket TMA — máx. horas", 0, 500, int(me["tma"]))
    if st.button("Salvar metas", type="primary"):
        banco.salvar_config("metas_eficiencia", {"nivel_servico": n_ns, "improdutividade": n_imp, "retrabalho": n_ret,
                                                 "auditoria": n_aud, "sinistro": n_sin, "ocupacao_min": n_omin,
                                                 "ocupacao_max": n_omax, "sla": n_sla, "nao_conf": n_nc, "no_show": n_ns2,
                                                 "tme": n_tme, "tma": n_tma})
        st.success("Metas salvas.")
        st.rerun()

    st.subheader("Capacidade")
    cfg_cap = {**cap.PADRAO, **banco.ler_config("capacidade", {})}
    k1, k2, k3 = st.columns(3)
    osd = k1.number_input("Atendimentos por técnico por dia", 1, 10, int(cfg_cap["os_por_tecnico_dia"]))
    fa = k2.number_input("Faixa de atenção a partir de (%)", 1, 200, int(cfg_cap["faixa_atencao"]))
    fs = k3.number_input("Acima da capacidade a partir de (%)", 1, 300, int(cfg_cap["faixa_sobrecarga"]))
    dt_ = st.multiselect("Dias de trabalho", list(range(7)), default=cfg_cap["dias_trabalho"],
                         format_func=lambda i: cap.DIAS_SEMANA[i])
    if st.button("Salvar capacidade", type="primary"):
        banco.salvar_config("capacidade", {"os_por_tecnico_dia": int(osd), "faixa_atencao": int(fa),
                                           "faixa_sobrecarga": int(fs), "dias_trabalho": sorted(dt_)})
        st.success("Parâmetros de capacidade salvos.")
        st.rerun()

    st.subheader("Auditoria")
    st.caption("Itens do checklist, um por linha. Mudar um item vale para as próximas auditorias; as já salvas "
               "guardam os itens com que foram feitas.")
    itens_txt = st.text_area("Itens verificados", "\n".join(banco.ler_config("itens_auditoria", aud.ITENS_PADRAO)), height=230)
    a1, a2 = st.columns(2)
    meta_in = a1.number_input("Meta de aprovação (%)", 0, 100, int(banco.ler_config("meta_aprovacao", 80)))
    auditor_in = a2.text_input("Auditor padrão", banco.ler_config("auditor_padrao", ""))
    if st.button("Salvar configurações de auditoria", type="primary"):
        banco.salvar_config("itens_auditoria", [x.strip() for x in itens_txt.splitlines() if x.strip()])
        banco.salvar_config("meta_aprovacao", int(meta_in))
        banco.salvar_config("auditor_padrao", auditor_in)
        st.success("Configurações de auditoria salvas.")
        st.rerun()

    st.subheader("☁️ Cópia de segurança e migração")
    st.caption("Banco em uso: " + ("**nuvem (Supabase)**" if banco.usando_nuvem() else "**local (arquivo dados_painel.db)**"))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Baixar cópia de todos os dados**")
        st.caption("Gera um arquivo .db com tudo: bases, cadastro, retrabalho, auditorias, não conformidades, financeiro "
                   "e configurações. Serve de backup e para levar os dados para outro banco.")
        if st.button("Gerar cópia"):
            st.session_state["copia_db"] = banco.exportar_sqlite()
        if "copia_db" in st.session_state:
            st.download_button("⬇️ Baixar copia_painel.db", st.session_state["copia_db"],
                               f"copia_painel_{date.today():%Y%m%d}.db", mime="application/octet-stream")
    with c2:
        st.markdown("**Trazer dados de um arquivo .db**")
        st.caption("Use no painel online para trazer os dados do computador: suba o arquivo **dados_painel.db** da pasta "
                   "do painel (ou uma cópia gerada ao lado). As tabelas do arquivo substituem as deste banco.")
        arq_db = st.file_uploader("Arquivo .db", type=["db"], key="up_db")
        if arq_db:
            conteudo = arq_db.getvalue()
            try:
                res = banco.resumo_sqlite(conteudo)
                st.dataframe(pd.Series(res, name="Linhas").rename_axis("Tabela"), width="content")
                conf = st.checkbox("Entendo que os dados deste banco serão substituídos pelos do arquivo", key="conf_db")
                if st.button("Copiar para este banco", type="primary", disabled=not conf):
                    with st.spinner("Copiando..."):
                        feitos = banco.importar_sqlite(conteudo)
                    st.success(f"{len(feitos)} tabelas copiadas ({sum(feitos.values())} linhas).")
            except Exception as e:
                st.error(f"Não consegui ler o arquivo: {e}")

    st.subheader("Famílias de serviço")
    st.caption("Como cada tipo de atividade das bases foi agrupado.")
    if not ativ.empty:
        fam = ativ.groupby(["familia", "tipo_atividade"]).size().rename("Atividades").reset_index()
        st.dataframe(fam.rename(columns={"familia": "Família", "tipo_atividade": "Tipo de atividade"}),
                     hide_index=True, width="stretch")
