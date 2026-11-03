"""Regras de negócio do painel: leitura do CSV, famílias de serviço,
classificação planejado x resultado e cálculo dos indicadores."""
import io
import unicodedata

import pandas as pd

# Colunas do CSV do sistema que o painel usa. Todo o resto (cliente, endereço,
# telefone, e-mail, CEP, conta...) é descartado na importação e nunca é gravado.
COLUNAS_CSV = {
    "OS": "os",
    "Ticket Jira": "ticket",
    "Placa": "placa",
    "Oficina": "oficina",
    "ID da Oficina": "id_oficina",
    "Status da Atividade": "status",
    "Tipo de Atividade": "tipo_atividade",
    "Data": "data",
    "Razão da Improdutiva": "razao_improdutiva",
    "Observação do Técnico (Improdutiva)": "obs_improdutiva",
    "Motivo do Desagendamento": "motivo_desagendamento",
    "Recurso": "tecnico",
    "Estado": "uf_cliente",
    # usados na triagem de retrabalho (cruzamento pelo número da OS)
    "Observações do Técnico": "obs_tecnico",
    "Observação da O.S. (técnico)": "obs_os_tecnico",
    "Observação Vistoria": "obs_vistoria",
    "Flag OS com Sinistro": "flag_sinistro",
    "Equipamentos trocados": "equip_trocados",
    "Diagnóstico Real": "diag_real",
    "Data Portal": "data_portal",  # entrada do chamado: base do nível de serviço (até 7 dias) e do TME
}

UFS_PADRAO = ["RS", "SC"]

FAMILIAS = ["Manutenção", "Instalação", "Retirada", "Reinstalação", "Renovação", "Upgrade", "Outros"]

def _sem_acento(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt))
    return "".join(c for c in txt if not unicodedata.combining(c)).lower().strip()


def familia_servico(tipo) -> str:
    t = _sem_acento(tipo or "")
    if "renova" in t:
        return "Renovação"
    if t.startswith("reinstala"):
        return "Reinstalação"
    if t.startswith("instala"):
        return "Instalação"
    if t.startswith("retirada"):
        return "Retirada"
    if t.startswith("manuten"):
        return "Manutenção"
    if t.startswith("upgrade"):
        return "Upgrade"
    return "Outros"


def ler_arquivo(arquivo) -> pd.DataFrame:
    """Lê CSV (vírgula ou ponto e vírgula, UTF-8 ou Latin-1) ou planilha."""
    nome = getattr(arquivo, "name", "").lower()
    bruto = arquivo.getvalue() if hasattr(arquivo, "getvalue") else arquivo.read()
    if nome.endswith((".xlsx", ".xls", ".ods")):
        abas = pd.read_excel(io.BytesIO(bruto), dtype=str, sheet_name=None)
        return max(abas.values(), key=len)  # usa a aba com mais linhas (ignora tabelas dinâmicas e abas vazias)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = bruto.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    primeira = texto.split("\n", 1)[0]
    sep = ";" if primeira.count(";") > primeira.count(",") else ","
    return pd.read_csv(io.StringIO(texto), sep=sep, dtype=str)


def preparar_atividades(bruto: pd.DataFrame) -> pd.DataFrame:
    """Mantém só as colunas necessárias, limpa e padroniza."""
    faltando = [c for c in ("OS", "Status da Atividade", "Tipo de Atividade", "Data") if c not in bruto.columns]
    if faltando:
        raise ValueError("O arquivo não tem as colunas obrigatórias: " + ", ".join(faltando))
    df = pd.DataFrame({novo: bruto[orig] if orig in bruto.columns else None for orig, novo in COLUNAS_CSV.items()})
    df = df.dropna(subset=["os"])
    df["os"] = df["os"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df = df[df["os"] != ""]
    df = df[~df["tipo_atividade"].fillna("").str.lower().str.startswith("intervalo")]
    df["status"] = df["status"].fillna("").str.strip().str.lower()
    df["id_oficina"] = df["id_oficina"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).replace({"nan": None, "None": None})
    df["data"] = pd.to_datetime(df["data"], dayfirst=True, errors="coerce").dt.date
    df = df.dropna(subset=["data"])
    df["familia"] = df["tipo_atividade"].map(familia_servico)
    return df.drop_duplicates(subset=["os", "data"], keep="last").reset_index(drop=True)


def uf_da_atividade(df: pd.DataFrame, oficinas: pd.DataFrame) -> pd.Series:
    """UF-base da oficina pelo cadastro. Oficina fora do cadastro não tem UF e fica fora do painel
    (evita oficinas próprias de clientes e oficinas de outros estados que atenderam na região)."""
    mapa = dict(zip(oficinas["id"].astype(str), oficinas["uf_base"].fillna("").astype(str).str.upper().str.strip()))
    return df["id_oficina"].astype(str).map(mapa).fillna("")


def filtrar_regiao(df: pd.DataFrame, oficinas: pd.DataFrame, ufs: list) -> pd.DataFrame:
    """Mantém só as atividades das oficinas da região escolhida em Configurações."""
    if df.empty:
        return df
    uf = uf_da_atividade(df, oficinas)
    if not ufs:  # sem região definida: todas as oficinas do cadastro (Brasil), nada de fora dele
        return df[uf != ""]
    return df[uf.isin([u.upper() for u in ufs])]


# Classes do painel operacional (todos os serviços, sem MCI/MD)
EXECUTADO = "Atendimento executado"
ENCAIXE = "Encaixe"
IMPRODUTIVA = "Improdutiva"
CANCELADA = "Cancelada"
PERDIDA = "OS perdida"
INTERMEDIARIO = "Status intermediário"
OUTROS = "Fora da agenda (não concluída)"


def _chave_troca(r):
    t, p = str(r.get("ticket") or "").strip(), str(r.get("placa") or "").strip().upper()
    return (t, p) if t and p and t.lower() != "nan" and p.lower() != "nan" else None


def classificar_dia(dia, planejados: pd.DataFrame, resultado: pd.DataFrame) -> pd.DataFrame:
    """Classifica os atendimentos de um dia.
    Agendado = a OS estava no planejado mais recente exportado ANTES do dia (agenda de antes de o dia começar),
    ou está no planejado exportado no próprio dia, ainda pendente, e já tinha aparecido num planejado anterior.
    Se a OS planejada não aparece no resultado, procura uma substituta com o mesmo ticket + placa (troca de OS)."""
    res = resultado[resultado["data"] == dia].drop_duplicates("os", keep="last")
    primeira = planejados.groupby("os")["data_ref"].min()
    do_dia = planejados[planejados["data"] == dia]
    # 1) agenda como estava antes de o dia começar: planejado mais recente exportado ANTES do dia
    antes = do_dia[do_dia["data_ref"] < dia]
    ref_antes = antes["data_ref"].max() if not antes.empty else None
    agenda = antes[antes["data_ref"] == ref_antes].drop_duplicates("os", keep="last") if ref_antes else antes.iloc[0:0]
    agenda = agenda[agenda["status"] != "cancelado"].assign(_ref=ref_antes)
    # 2) planejado exportado no próprio dia: entram OS que já tinham aparecido antes e ainda estavam pendentes
    mesmo = do_dia[do_dia["data_ref"] == dia].drop_duplicates("os", keep="last")
    extra = mesmo[mesmo["status"].isin(["pendente", "iniciado"]) & ~mesmo["os"].isin(agenda["os"])
                  & mesmo["os"].map(lambda o: primeira.get(o) is not None and primeira.get(o) < dia)]
    plano = pd.concat([agenda, extra.assign(_ref=dia)], ignore_index=True)
    vig_ref = ref_antes if ref_antes else (dia if not mesmo.empty else None)

    res_por_os = res.set_index("os")
    res_por_troca = {}
    for _, rr in res.iterrows():
        k = _chave_troca(rr)
        if k:
            res_por_troca.setdefault(k, rr)
    usadas, linhas = set(), []

    for _, p in plano.iterrows():
        prim = primeira.get(p["os"])
        r, troca = None, False
        if p["os"] in res_por_os.index:
            r = res_por_os.loc[p["os"]]
        elif (k := _chave_troca(p)) and k in res_por_troca and res_por_troca[k]["os"] not in usadas:
            r, troca = res_por_troca[k], True
        base = (r if r is not None else p).to_dict()
        base["os"] = r.name if (r is not None and not troca) else (r["os"] if troca else p["os"])
        base["os_planejada"] = p["os"]
        txt_vig = f"planejado de {p['_ref']:%d/%m} (primeira aparição: {prim:%d/%m})"
        if r is None:
            classe, mot = PERDIDA, f"Estava no {txt_vig}, mas não apareceu no resultado e não há substituta com o mesmo ticket + placa."
        else:
            usadas.add(base["os"])
            st_ = r["status"]
            sufixo = " (OS trocada: mesmo ticket + placa)" if troca else ""
            if st_ == "concluído":
                classe, mot = EXECUTADO, f"Estava no {txt_vig} e foi executada{sufixo}."
            elif st_ == "não concluído":
                classe, mot = IMPRODUTIVA, f"Estava no {txt_vig} e terminou não concluída{sufixo}."
            elif st_ == "cancelado":
                classe, mot = CANCELADA, f"Estava no {txt_vig} e apareceu cancelada no resultado{sufixo}."
            else:
                classe, mot = INTERMEDIARIO, f"Estava no {txt_vig}; no resultado ficou como \u201c{st_}\u201d{sufixo}."
        base.update(classificacao=classe, motivo=mot, origem="Agendada", troca_os="Sim" if troca else "Não",
                    status_planejado=p["status"], status_resultado=None if r is None else r["status"],
                    primeira_aparicao=prim, data_planejada=p["data"])
        linhas.append(base)

    for os_, r in res_por_os.iterrows():
        if os_ in usadas:
            continue
        prim = primeira.get(os_)
        prova = "sem prova de agendamento antes do início do dia" + (f" (primeira aparição: {prim:%d/%m})" if prim is not None else "")
        base = r.to_dict()
        base["os"] = os_
        if r["status"] == "concluído":
            classe, mot = ENCAIXE, f"Executada {prova}: encaixe/adicional."
        elif r["status"] == "não concluído":
            classe, mot = IMPRODUTIVA, f"Encaixe {prova} que terminou não concluído."
        else:
            classe, mot = OUTROS, f"Fora da agenda e ficou como \u201c{r['status']}\u201d; não entra nos indicadores."
        base.update(classificacao=classe, motivo=mot, origem="Encaixe", troca_os="Não", os_planejada=None,
                    status_planejado=None, status_resultado=r["status"], primeira_aparicao=prim, data_planejada=None)
        linhas.append(base)

    out = pd.DataFrame(linhas)
    if out.empty:
        return out
    out["data_operacional"] = dia
    out["agendada"] = out["origem"] == "Agendada"
    out["plano_vigente"] = vig_ref
    return out


def indicadores(df: pd.DataFrame) -> dict:
    c = df["classificacao"].value_counts() if not df.empty else pd.Series(dtype=int)
    g = lambda k: int(c.get(k, 0))
    agend = int(df["agendada"].sum()) if not df.empty else 0
    exe, enc, imp = g(EXECUTADO), g(ENCAIXE), g(IMPRODUTIVA)
    div = lambda a, b: (a / b) if b else None
    return {
        "Atendimentos agendados": agend,
        "Atendimentos executados": exe,
        "Encaixes": enc,
        "Improdutivas": imp,
        "Improdutivas da agenda": int(((df["classificacao"] == IMPRODUTIVA) & (df["origem"] == "Agendada")).sum()) if not df.empty else 0,
        "Improdutivas de encaixe": int(((df["classificacao"] == IMPRODUTIVA) & (df["origem"] == "Encaixe")).sum()) if not df.empty else 0,
        "Canceladas": g(CANCELADA),
        "OS perdidas": g(PERDIDA),
        "Status intermediário": g(INTERMEDIARIO),
        "Total realizado": exe + enc,
        "Execução da agenda": div(exe, agend),
        "Improdutividade": div(imp, exe + enc + imp),
        "Cancelamento": div(g(CANCELADA), agend),
        "Perda de OS": div(g(PERDIDA), agend),
        "Participação de encaixes": div(enc, exe + enc),
        "Improdutividade dos encaixes": div(int(((df["classificacao"] == IMPRODUTIVA) & (df["origem"] == "Encaixe")).sum())
                                            if not df.empty else 0,
                                            enc + (int(((df["classificacao"] == IMPRODUTIVA) & (df["origem"] == "Encaixe")).sum())
                                                   if not df.empty else 0)),
    }


def tabela_por(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
    linhas = []
    for valor, grupo in df.groupby(coluna, dropna=False):
        linha = {coluna: valor}
        linha.update(indicadores(grupo))
        linhas.append(linha)
    return pd.DataFrame(linhas)


_GENERICAS = {"operacao", "oficina", "ltda", "me", "sa", "de", "da", "do", "dos", "das", "sul", "norte", "transporte",
              "transportes", "turismo", "agro", "servicos", "servico", "instalacoes", "rastreadores", "tecnologia",
              "sistemas", "seguranca", "grupo", "filial", "matriz", "logistica", "eireli", "epp", "cia", "comercio",
              "industria", "unidade", "propria", "viacao"}


def _tokens(s) -> set:
    import re
    s = _sem_acento(s)
    return {t for t in re.findall(r"[a-z0-9]+", s) if len(t) >= 3 and t not in _GENERICAS}


def sugerir_proprias(oficina: pd.Series, cliente: pd.Series, uf: pd.Series, ufs: list) -> pd.DataFrame:
    """Oficina própria = oficina com o mesmo nome do cliente que ela atende (ex.: oficina Buzin atendendo cliente Buzin).
    Sugere as oficinas em que a maioria das OS é de cliente com nome parecido, atendendo na região."""
    d = pd.DataFrame({"oficina": oficina.fillna(""), "cliente": cliente.fillna(""), "uf": uf.fillna("").astype(str).str.upper()})
    d["mesmo_nome"] = [bool(_tokens(o) & _tokens(c)) for o, c in zip(d["oficina"], d["cliente"])]
    g = d.groupby("oficina").agg(OS=("oficina", "size"), mesmo_nome=("mesmo_nome", "mean"),
                                 na_regiao=("uf", lambda s: s.isin([u.upper() for u in ufs]).mean() if ufs else 1.0),
                                 uf=("uf", lambda s: s.mode().iat[0] if len(s.mode()) else "")).reset_index()
    return g[(g["mesmo_nome"] >= 0.5) & (g["na_regiao"] >= 0.5) & (g["oficina"] != "")].sort_values("OS", ascending=False)
