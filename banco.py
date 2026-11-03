"""Armazenamento das bases importadas.
Sem configuração, usa um arquivo SQLite local (bom para testar no computador).
Com `db_url` nos secrets, usa o Postgres do Supabase (necessário na nuvem)."""
import json
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, inspect, text


def _url_banco():
    """Endereço do banco. Aceita:
    - [banco] com host, port, user, password, database nos Secrets (recomendado: senha com qualquer caractere funciona);
    - ou db_url = "postgresql://..." nos Secrets;
    - sem nada: arquivo local dados_painel.db."""
    from sqlalchemy.engine import URL
    try:
        cfg = st.secrets["banco"]
        try:
            import psycopg  # noqa: F401
            driver = "postgresql+psycopg"
        except ImportError:
            driver = "postgresql+psycopg2"
        return URL.create(driver, username=str(cfg["user"]).strip(), password=str(cfg["password"]).strip(),
                          host=str(cfg["host"]).strip(), port=int(cfg.get("port", 5432)),
                          database=str(cfg.get("database", "postgres")).strip())
    except Exception:
        pass
    try:
        url = str(st.secrets["db_url"]).strip()
    except Exception:
        return "sqlite:///dados_painel.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@st.cache_resource
def _motor_para(url_txt: str, _url):
    eng = create_engine(_url, pool_pre_ping=True)
    try:
        with eng.connect():
            pass
    except Exception as e:  # mostra o motivo sem expor a senha
        msg = str(getattr(e, "orig", e)).split("\n")[0]
        st.error("**Não consegui conectar ao banco de dados.**\n\n"
                 f"Motivo informado pelo banco: `{msg}`\n\n"
                 "Confira os dados de conexão nos Secrets do app (usuário, senha, servidor e porta) e reinicie o app.")
        st.stop()
    return eng


def motor():
    url = _url_banco()
    # a chave do cache muda quando os Secrets mudam: não precisa reiniciar o app depois de corrigir
    return _motor_para(url.render_as_string(hide_password=False) if hasattr(url, "render_as_string") else str(url), url)


def usando_nuvem() -> bool:
    return not str(motor().url).startswith("sqlite")


def _existe(tabela: str) -> bool:
    return inspect(motor()).has_table(tabela)


def modo_integrado() -> bool:
    """Habilite somente após configurar a conexão PostgreSQL no Streamlit."""
    try:
        return bool(st.secrets.get("integracao_ofs", {}).get("habilitada", False))
    except Exception:
        return False


def _bloquear_gravacao_integrada(operacao: str):
    if modo_integrado():
        raise RuntimeError(
            f"{operacao}: operação bloqueada no modo integrado de leitura. "
            "Não altere as tabelas originais; finalize primeiro a validação de gravações."
        )


def _carregar_ofs_integrado() -> pd.DataFrame:
    """Consulta views do schema painel_marcos, sem copiar ou alterar as OS originais."""
    if str(motor().url).startswith("sqlite"):
        raise RuntimeError("Modo integrado exige conexão PostgreSQL/Supabase configurada.")
    sql = """SELECT * FROM painel_marcos.ofs_todos"""
    df = pd.read_sql(text(sql), motor())
    if df.empty:
        return df
    # Dados do OFS originalmente importados podem ter campos adicionais no JSON.
    # A prioridade é preservar o valor já padronizado nas views.
    alias = {"uf": "uf_cliente", "ticket": "ticket", "tecnico": "tecnico"}
    for origem, destino in alias.items():
        if origem in df.columns and destino not in df.columns:
            df[destino] = df[origem]
    if "dados_originais" in df.columns:
        json_rows = df["dados_originais"].map(lambda x: x if isinstance(x, dict) else {})
        campos = {
            "id_oficina": ["ID da Oficina", "id_oficina"],
            "razao_improdutiva": ["Razão da Improdutiva", "razao_improdutiva"],
            "obs_improdutiva": ["Observação do Técnico (Improdutiva)", "obs_improdutiva"],
            "motivo_desagendamento": ["Motivo do Desagendamento", "motivo_desagendamento"],
            "obs_tecnico": ["Observações do Técnico", "obs_tecnico"],
            "obs_os_tecnico": ["Observação da O.S. (técnico)", "obs_os_tecnico"],
            "obs_vistoria": ["Observação Vistoria", "obs_vistoria"],
            "flag_sinistro": ["Flag OS com Sinistro", "flag_sinistro"],
            "equip_trocados": ["Equipamentos trocados", "equip_trocados"],
            "diag_real": ["Diagnóstico Real", "diag_real"],
            "data_portal": ["Data Portal", "data_portal"],
        }
        for destino, chaves in campos.items():
            df[destino] = json_rows.map(lambda d: next((d[k] for k in chaves if k in d and d[k] is not None), None))
    for col in ("data", "data_ref"):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    if "tipo_atividade" in df.columns:
        from regras import familia_servico
        df["familia"] = df["tipo_atividade"].map(familia_servico)
    if "status" in df.columns:
        df["status"] = df["status"].fillna("").astype(str).str.lower().str.strip()
    if "id_oficina" not in df.columns:
        df["id_oficina"] = None
    return df


def salvar_base(tipo: str, data_ref, df: pd.DataFrame, nome_arquivo: str):
    """Substitui a base do mesmo tipo e data de referência."""
    _bloquear_gravacao_integrada("Importação de OFS")
    data_ref = str(data_ref)
    df = df.copy()
    df["tipo_base"] = tipo
    df["data_ref"] = data_ref
    df["data"] = df["data"].astype(str)
    with motor().begin() as con:
        if _existe("atividades"):
            existentes = {c["name"] for c in inspect(motor()).get_columns("atividades")}
            for col in df.columns:
                if col not in existentes:
                    con.execute(text(f'ALTER TABLE atividades ADD COLUMN "{col}" TEXT'))
        for tab in ("atividades", "importacoes"):
            if _existe(tab):
                con.execute(text(f"DELETE FROM {tab} WHERE tipo_base = :t AND data_ref = :d"), {"t": tipo, "d": data_ref})
        df.to_sql("atividades", con, if_exists="append", index=False)
        pd.DataFrame([{
            "tipo_base": tipo, "data_ref": data_ref, "linhas": len(df),
            "arquivo": nome_arquivo, "importado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }]).to_sql("importacoes", con, if_exists="append", index=False)
    st.cache_data.clear()


def excluir_base(tipo: str, data_ref):
    _bloquear_gravacao_integrada("Exclusão de OFS")
    data_ref = str(data_ref)
    with motor().begin() as con:
        for tab in ("atividades", "importacoes"):
            if _existe(tab):
                con.execute(text(f"DELETE FROM {tab} WHERE tipo_base = :t AND data_ref = :d"), {"t": tipo, "d": data_ref})
    st.cache_data.clear()


@st.cache_data(ttl=300)
def carregar_atividades() -> pd.DataFrame:
    if modo_integrado():
        return _carregar_ofs_integrado()
    if not _existe("atividades"):
        return pd.DataFrame()
    df = pd.read_sql("SELECT * FROM atividades", motor())
    for c in ("data", "data_ref"):
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


@st.cache_data(ttl=300)
def carregar_importacoes() -> pd.DataFrame:
    if modo_integrado():
        return pd.DataFrame(columns=["tipo_base", "data_ref", "linhas", "arquivo", "importado_em"])
    if not _existe("importacoes"):
        return pd.DataFrame()
    return pd.read_sql("SELECT * FROM importacoes ORDER BY data_ref DESC", motor())


COLS_OFICINA = ["id", "oficina", "tipo", "cidade_base", "uf_base", "consultor", "tecnicos", "contrato", "valor_fixo",
                "inicio_fixo", "outros_nomes", "prioridade", "ativa", "observacao"]


@st.cache_data(ttl=300)
def carregar_oficinas() -> pd.DataFrame:
    if not _existe("oficinas"):
        return pd.DataFrame(columns=COLS_OFICINA)
    df = pd.read_sql("SELECT * FROM oficinas", motor())
    df["id"] = df["id"].astype(str)
    for c in COLS_OFICINA:
        if c not in df.columns:
            df[c] = None
    df["tecnicos"] = pd.to_numeric(df["tecnicos"], errors="coerce")
    df["valor_fixo"] = pd.to_numeric(df["valor_fixo"], errors="coerce")
    df["contrato"] = df["contrato"].fillna("Tabela")
    df["tipo"] = df["tipo"].fillna("Credenciada")
    df["inicio_fixo"] = pd.to_datetime(df["inicio_fixo"], errors="coerce").dt.date
    return df[COLS_OFICINA]


def salvar_oficinas(df: pd.DataFrame):
    _bloquear_gravacao_integrada("Alteração de oficinas")
    df = df.copy()
    for c in COLS_OFICINA:
        if c not in df.columns:
            df[c] = None
    df = df[COLS_OFICINA]
    df["tecnicos"] = pd.to_numeric(df["tecnicos"], errors="coerce")
    df["valor_fixo"] = pd.to_numeric(df["valor_fixo"], errors="coerce")
    df["id"] = df["id"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df["uf_base"] = df["uf_base"].fillna("").astype(str).str.upper().str.strip()
    df = df[df["id"].ne("") & df["id"].ne("nan")].drop_duplicates("id", keep="last")
    df.to_sql("oficinas", motor(), if_exists="replace", index=False)
    st.cache_data.clear()


def ler_config(chave: str, padrao):
    if not _existe("config"):
        return padrao
    with motor().connect() as con:
        linha = con.execute(text("SELECT valor FROM config WHERE chave = :c"), {"c": chave}).fetchone()
    return json.loads(linha[0]) if linha else padrao


def salvar_config(chave: str, valor):
    _bloquear_gravacao_integrada("Configuração")
    with motor().begin() as con:
        if _existe("config"):
            con.execute(text("DELETE FROM config WHERE chave = :c"), {"c": chave})
        pd.DataFrame([{"chave": chave, "valor": json.dumps(valor, ensure_ascii=False)}]).to_sql("config", con, if_exists="append", index=False)


# ---------------------------------------------------------------- retrabalho
def _upsert(tabela: str, df: pd.DataFrame, chave: str):
    """Substitui as linhas com a mesma chave e mantém as demais."""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    if _existe(tabela):
        atual = pd.read_sql(f"SELECT * FROM {tabela}", motor())
        df = pd.concat([atual[~atual[chave].isin(df[chave])], df], ignore_index=True)
    df.to_sql(tabela, motor(), if_exists="replace", index=False)
    st.cache_data.clear()


def salvar_casos_retrabalho(df: pd.DataFrame):
    _bloquear_gravacao_integrada("Gravação de retrabalho")
    _upsert("retrabalho_casos", df, "id_caso")


def salvar_decisoes_retrabalho(df: pd.DataFrame):
    _bloquear_gravacao_integrada("Decisão de retrabalho")
    df = df.assign(decidido_em=datetime.now().strftime("%Y-%m-%d %H:%M"))
    _upsert("retrabalho_decisoes", df, "id_caso")


@st.cache_data(ttl=300)
def carregar_retrabalho() -> pd.DataFrame:
    if not _existe("retrabalho_casos"):
        return pd.DataFrame()
    casos = pd.read_sql("SELECT * FROM retrabalho_casos", motor())
    if _existe("retrabalho_decisoes"):
        dec = pd.read_sql("SELECT * FROM retrabalho_decisoes", motor())
        casos = casos.merge(dec, on="id_caso", how="left")
    for c in ("decisao_final", "causa", "observacao", "decidido_em", "sinistro_conf"):
        if c not in casos.columns:
            casos[c] = None
    for c in ("data_1", "data_2"):
        casos[c] = pd.to_datetime(casos[c], errors="coerce")
    return casos


def excluir_retrabalho():
    _bloquear_gravacao_integrada("Exclusão de retrabalho")
    with motor().begin() as con:
        for tab in ("retrabalho_casos", "retrabalho_decisoes"):
            if _existe(tab):
                con.execute(text(f"DROP TABLE {tab}"))
    st.cache_data.clear()


# ---------------------------------------------------------------- auditoria
def salvar_auditoria(registro: dict):
    _bloquear_gravacao_integrada("Auditoria")
    """Uma auditoria por OS: auditar de novo a mesma OS substitui a anterior."""
    reg = dict(registro)
    reg["itens"] = json.dumps(reg.get("itens", {}), ensure_ascii=False)
    reg["registrado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _upsert("auditorias", pd.DataFrame([reg]), "os")


def excluir_auditoria(os_: str):
    _bloquear_gravacao_integrada("Exclusão de auditoria")
    if _existe("auditorias"):
        with motor().begin() as con:
            con.execute(text("DELETE FROM auditorias WHERE os = :o"), {"o": str(os_)})
    st.cache_data.clear()


@st.cache_data(ttl=300)
def carregar_auditorias() -> pd.DataFrame:
    if not _existe("auditorias"):
        return pd.DataFrame()
    df = pd.read_sql("SELECT * FROM auditorias", motor())
    df["os"] = df["os"].astype(str)
    for c in ("data_execucao", "data_auditoria"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["itens"] = df["itens"].map(lambda s: json.loads(s) if isinstance(s, str) and s else {})
    return df


# ---------------------------------------------------------------- lançamentos manuais (eficiência)
def salvar_manuais(df: pd.DataFrame):
    _bloquear_gravacao_integrada("Lançamentos manuais")
    df = df.copy()
    df["chave"] = df["id_oficina"].astype(str) + "|" + df["mes"].astype(str)
    _upsert("lancamentos_manuais", df, "chave")


@st.cache_data(ttl=300)
def carregar_manuais() -> pd.DataFrame:
    if not _existe("lancamentos_manuais"):
        return pd.DataFrame(columns=["id_oficina", "mes", "nao_conf", "no_show", "observacao"])
    return pd.read_sql("SELECT * FROM lancamentos_manuais", motor())


# ---------------------------------------------------------------- financeiro (interno)
def salvar_financeiro(df: pd.DataFrame, atualizar_existentes: bool = False):
    _bloquear_gravacao_integrada("Gravação financeira")
    """Nunca apaga nada.
    - OS novas: sempre entram.
    - Consolidado (mês fechado) substitui o que veio da auditoria de pagamento (dado provisório) para a mesma OS.
    - Auditoria nunca substitui o Consolidado.
    - Fora isso, a OS que já existe só é atualizada se atualizar_existentes=True."""
    df = df.copy()
    df["data"] = df["data"].astype(str)
    df["os"] = df["os"].astype(str)
    if _existe("financeiro"):
        cols = [c["name"] for c in inspect(motor()).get_columns("financeiro")]
        atual = pd.read_sql("SELECT os" + (", fonte" if "fonte" in cols else "") + " FROM financeiro", motor())
        if "fonte" not in atual:
            atual["fonte"] = "auditoria"
        fonte_atual = dict(zip(atual["os"].astype(str), atual["fonte"].fillna("auditoria")))
        fonte_nova = df["fonte"].iloc[0] if "fonte" in df and len(df) else "auditoria"

        def entra(os_):
            if os_ not in fonte_atual:
                return True
            if fonte_nova == "consolidado" and fonte_atual[os_] != "consolidado":
                return True
            if fonte_nova == "auditoria" and fonte_atual[os_] == "consolidado":
                return False
            return atualizar_existentes
        df = df[df["os"].map(entra)]
        if df.empty:
            return 0
    _upsert("financeiro", df, "os")
    return len(df)


@st.cache_data(ttl=300)
def carregar_financeiro() -> pd.DataFrame:
    if not _existe("financeiro"):
        return pd.DataFrame()
    df = pd.read_sql("SELECT * FROM financeiro", motor())
    df["data"] = pd.to_datetime(df["data"]).dt.date
    for c in ("com_km", "alerta_placa", "alerta_visita"):
        df[c] = df[c].astype(bool)
    return df


# ---------------------------------------------------------------- não conformidades (reclamações)
def salvar_nc(reg: dict):
    _bloquear_gravacao_integrada("Não conformidade")
    _upsert("nao_conformidades", pd.DataFrame([reg]), "id")


def excluir_nc(id_: str):
    _bloquear_gravacao_integrada("Exclusão de não conformidade")
    if _existe("nao_conformidades"):
        with motor().begin() as con:
            con.execute(text("DELETE FROM nao_conformidades WHERE id = :i"), {"i": id_})
    st.cache_data.clear()


@st.cache_data(ttl=300)
def carregar_nc() -> pd.DataFrame:
    if not _existe("nao_conformidades"):
        return pd.DataFrame()
    df = pd.read_sql("SELECT * FROM nao_conformidades", motor())
    for c in ("id", "data", "os", "oficina", "id_oficina", "tecnico", "cliente", "placa", "canal", "motivo", "descricao",
              "status", "data_analise", "analise", "evidencias", "registrado_em"):
        if c not in df.columns:
            df[c] = None
    for c in ("data", "data_analise"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


# ---------------------------------------------------------------- cópia de segurança / migração
def tabelas() -> list:
    return [t for t in inspect(motor()).get_table_names() if not t.startswith(("pg_", "sql_"))]


def exportar_sqlite() -> bytes:
    """Gera um arquivo .db (SQLite) com TODAS as tabelas do banco atual: cópia de segurança e migração."""
    import os
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(), "copia_painel.db")
    destino = create_engine(f"sqlite:///{caminho}")
    for t in tabelas():
        pd.read_sql(f'SELECT * FROM "{t}"', motor()).to_sql(t, destino, if_exists="replace", index=False)
    destino.dispose()
    with open(caminho, "rb") as f:
        return f.read()


def resumo_sqlite(conteudo: bytes) -> dict:
    import os
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(), "origem.db")
    with open(caminho, "wb") as f:
        f.write(conteudo)
    origem = create_engine(f"sqlite:///{caminho}")
    res = {t: int(pd.read_sql(f'SELECT COUNT(*) AS n FROM "{t}"', origem)["n"].iloc[0])
           for t in inspect(origem).get_table_names()}
    origem.dispose()
    return res


def importar_sqlite(conteudo: bytes) -> dict:
    _bloquear_gravacao_integrada("Restauração de backup")
    """Copia todas as tabelas de um arquivo .db para o banco atual, substituindo as tabelas de mesmo nome."""
    import os
    import tempfile
    caminho = os.path.join(tempfile.mkdtemp(), "origem.db")
    with open(caminho, "wb") as f:
        f.write(conteudo)
    origem = create_engine(f"sqlite:///{caminho}")
    feitos = {}
    for t in inspect(origem).get_table_names():
        df = pd.read_sql(f'SELECT * FROM "{t}"', origem)
        df.to_sql(t, motor(), if_exists="replace", index=False, chunksize=2000, method="multi")
        feitos[t] = len(df)
    origem.dispose()
    st.cache_data.clear()
    return feitos
