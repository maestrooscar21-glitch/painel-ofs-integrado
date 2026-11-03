"""Extrato mensal da oficina em PDF (enviado à oficina por WhatsApp/e-mail).
Regras: retrabalho só confirmado; não conformidades procedentes com relato e análise, improcedentes só a quantidade,
canceladas e em análise fora. Sem dados de cliente."""
import io
from datetime import date

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import eficiencia as ef

COR = colors.HexColor("#0E6E6B")
CINZA = colors.HexColor("#5B6B70")
FUNDO = colors.HexColor("#EEF3F2")
SEMAFORO = {"🟢": ("Dentro da meta", colors.HexColor("#D8EFE4"), colors.HexColor("#1E7A4F")),
            "🟡": ("Atenção", colors.HexColor("#FBF0D2"), colors.HexColor("#8A6400")),
            "🔴": ("Fora da meta", colors.HexColor("#F8DADA"), colors.HexColor("#A12A2A")),
            "⚪": ("Sem dado", colors.HexColor("#F1F1F1"), colors.HexColor("#777777"))}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]

_s = getSampleStyleSheet()
T1 = ParagraphStyle("t1", parent=_s["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=COR, alignment=0, spaceAfter=2)
T2 = ParagraphStyle("t2", parent=_s["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=COR, spaceBefore=10, spaceAfter=4)
TX = ParagraphStyle("tx", parent=_s["Normal"], fontName="Helvetica", fontSize=9, leading=12)
TXP = ParagraphStyle("txp", parent=TX, fontSize=8, textColor=CINZA, leading=10)
CEL = ParagraphStyle("cel", parent=TX, fontSize=8.5, leading=10.5)
NOTA = ParagraphStyle("nota", parent=TX, fontName="Helvetica-Bold", fontSize=30, leading=32, alignment=TA_CENTER, textColor=COR)


def nome_mes(m: str) -> str:
    return f"{MESES[int(m[5:]) - 1]}/{m[:4]}"


def _tabela(dados, larguras, cab=True, zebra=True, extra=None):
    t = Table(dados, colWidths=larguras, repeatRows=1 if cab else 0)
    est = [("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DEDC"))]
    if cab:
        est += [("BACKGROUND", (0, 0), (-1, 0), COR), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    if zebra:
        for i in range(1 if cab else 0, len(dados)):
            if i % 2 == 0:
                est.append(("BACKGROUND", (0, i), (-1, i), FUNDO))
    t.setStyle(TableStyle(est + (extra or [])))
    return t


def gerar(oficina: str, mes: str, linha: pd.Series, historico: pd.DataFrame, metas: dict, posicao: tuple | None,
          retrab: pd.DataFrame, auds: pd.DataFrame, ncs: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm,
                            bottomMargin=1.5 * cm, title=f"Extrato {oficina} {nome_mes(mes)}", author="Painel OFS")

    def rodape(c, d):
        c.saveState()
        c.setFont("Helvetica", 7.5)
        c.setFillColor(CINZA)
        c.drawString(1.6 * cm, 0.9 * cm, f"Painel OFS · Extrato mensal · {oficina} · gerado em {date.today():%d/%m/%Y}")
        c.drawRightString(A4[0] - 1.6 * cm, 0.9 * cm, f"Página {d.page}")
        c.restoreState()

    h = []
    h.append(Paragraph("Extrato mensal da oficina", T1))
    h.append(Paragraph(f"<b>{oficina}</b> · {nome_mes(mes).capitalize()}", ParagraphStyle("sub", parent=TX, fontSize=11, leading=14)))
    h.append(Spacer(1, 8))

    # ---------------- nota + resumo
    nt = ef.nota(linha, metas) if not linha.empty else None
    pos_txt = f"Posição na região: <b>{posicao[0]}º de {posicao[1]}</b>" if posicao else ""
    caixa = Table([[Paragraph(f"{nt if nt is not None else '—'}", NOTA)],
                   [Paragraph("Nota de eficiência (0 a 100)", ParagraphStyle("c", parent=TXP, alignment=TA_CENTER))],
                   [Paragraph(pos_txt, ParagraphStyle("c2", parent=TX, alignment=TA_CENTER))]], colWidths=[5 * cm])
    caixa.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, COR), ("BACKGROUND", (0, 0), (-1, -1), FUNDO),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    expl = Paragraph("A nota é a média dos indicadores que têm meta: <b>dentro da meta</b> vale 1, <b>atenção</b> vale ½ e "
                     "<b>fora da meta</b> vale 0. Indicadores sem dado no mês não entram na conta. Nas próximas páginas "
                     "estão o detalhe de cada indicador e os registros de qualidade do mês.", TX)
    h.append(Table([[caixa, expl]], colWidths=[5.4 * cm, 12.4 * cm],
                   style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (1, 0), (1, 0), 12)]))

    # ---------------- indicadores por pilar
    h.append(Paragraph("Indicadores do mês", T2))
    dados = [["Pilar", "Indicador", "Resultado", "Meta", "Situação"]]
    extra = []
    ultimo_pilar = None
    for k, (rot, pilar, _, sentido) in ef.KPIS.items():
        if k in ef.PENDENTES:
            continue
        v = linha.get(k) if not linha.empty else None
        s = ef.semaforo(k, v, metas)
        texto, fundo, cor = SEMAFORO.get(s, ("", None, None))
        rot = rot.replace("≤", "até")
        dados.append([Paragraph(f"<b>{pilar}</b>", CEL) if pilar != ultimo_pilar else "", rot, ef.formatar(k, v),
                      ef.texto_meta(k, metas) or "—", texto or "—"])
        ultimo_pilar = pilar
        if fundo is not None:
            i = len(dados) - 1
            extra += [("BACKGROUND", (4, i), (4, i), fundo), ("TEXTCOLOR", (4, i), (4, i), cor), ("FONTNAME", (4, i), (4, i), "Helvetica-Bold")]
    h.append(_tabela(dados, [3.4 * cm, 5.4 * cm, 2.4 * cm, 3.2 * cm, 3.4 * cm], extra=extra))
    h.append(Paragraph("Retrabalho considera somente os casos confirmados após análise (retorno ao mesmo veículo em até 90 dias). "
                       "Mau uso (sinistro) é o percentual de atendimentos em que o técnico apontou sinistro ou mau uso.", TXP))

    # ---------------- mix + evolução
    h.append(Paragraph("Volume de serviços", T2))
    mix = [("Instalação / renovação / upgrade", linha.get("inst")), ("Manutenção", linha.get("manut")),
           ("Retirada / reinstalação", linha.get("ret"))]
    tot = sum(int(x or 0) for _, x in mix)
    dmix = [["Tipo", "Serviços", "% do mês"]] + [[n, int(x or 0), f"{(x or 0) / tot * 100:.0f}%" if tot else "—"] for n, x in mix]
    dmix.append(["Total", tot, "100%" if tot else "—"])
    h.append(_tabela(dmix, [8 * cm, 3 * cm, 3 * cm], extra=[("FONTNAME", (0, len(dmix) - 1), (-1, len(dmix) - 1), "Helvetica-Bold")]))
    if historico is not None and len(historico) > 1:
        hist = historico.sort_values("mes").tail(6)
        kp = ["servicos", "improdutividade", "retrabalho", "sinistro", "auditoria"]
        dev = [["Indicador"] + [f"{MESES[int(m[5:]) - 1][:3]}/{m[2:4]}" for m in hist["mes"]]]
        for k in kp:
            dev.append([ef.KPIS[k][0].replace("≤", "até")] + [ef.formatar(k, v) for v in hist[k]])
        notas = [ef.nota(r, metas) for _, r in hist.iterrows()]
        dev.append(["Nota de eficiência"] + [str(n) if n is not None else "—" for n in notas])
        h.append(Spacer(1, 6))
        h.append(Paragraph("Evolução (últimos meses)", ParagraphStyle("t3", parent=TX, fontName="Helvetica-Bold", fontSize=10)))
        larg = [5.2 * cm] + [(17.8 - 5.2) / (len(dev[0]) - 1) * cm] * (len(dev[0]) - 1)
        h.append(_tabela(dev, larg))

    # ---------------- qualidade: retrabalho
    h.append(Paragraph("Qualidade · Retrabalhos confirmados", T2))
    if retrab is None or retrab.empty:
        h.append(Paragraph("Nenhum retrabalho confirmado no mês.", TX))
    else:
        dr = [["Retorno", "Placa", "OS retorno", "Dias", "Diagnóstico do retorno", "Causa"]]
        for _, r in retrab.sort_values("data_2").iterrows():
            dr.append([f"{pd.to_datetime(r['data_2']):%d/%m}", r.get("placa") or "", str(r.get("os_2") or ""),
                       "" if pd.isna(r.get("dias")) else int(r["dias"]),
                       Paragraph(next((str(r[c]) for c in ("diag_jira_2", "diag_ofs_2") if pd.notna(r.get(c)) and r.get(c)), "—"), CEL),
                       Paragraph(str(r["causa"]) if pd.notna(r.get("causa")) and r.get("causa") else "—", CEL)])
        h.append(_tabela(dr, [1.6 * cm, 2 * cm, 2.6 * cm, 1.2 * cm, 5.6 * cm, 4.8 * cm]))

    # ---------------- auditoria
    h.append(Paragraph("Qualidade · Auditoria", T2))
    if auds is None or auds.empty:
        h.append(Paragraph("Nenhuma OS auditada no mês.", TX))
    else:
        ap = (auds["resultado"] == "Aprovada").mean() * 100
        h.append(Paragraph(f"<b>{len(auds)}</b> OS auditadas · aprovação <b>{ap:.0f}%</b> · conformidade média dos itens "
                           f"<b>{auds['conformidade'].mean():.0f}%</b>.", TX))
        itens = [(i, r) for its in auds["itens"] for i, r in (its or {}).items()]
        rep = pd.Series([i for i, r in itens if r == "Reprovado"]).value_counts()
        if len(rep):
            h.append(Spacer(1, 3))
            h.append(_tabela([["Itens reprovados", "Vezes"]] + [[Paragraph(i, CEL), int(n)] for i, n in rep.items()],
                             [14 * cm, 2.5 * cm]))
        h.append(Paragraph("A auditoria é feita pelas fotos da OS: uma reprovação pode indicar execução fora do padrão ou "
                           "registro fotográfico insuficiente.", TXP))

    # ---------------- não conformidades
    h.append(Paragraph("Qualidade · Reclamações de cliente (não conformidades)", T2))
    proc = ncs[ncs["status"] == "Procedente"] if ncs is not None and not ncs.empty else pd.DataFrame()
    improc = int((ncs["status"] == "Improcedente").sum()) if ncs is not None and not ncs.empty else 0
    h.append(Paragraph(f"<b>{len(proc)}</b> procedente(s) · <b>{improc}</b> analisada(s) como improcedente(s). "
                       "Somente as procedentes contam no indicador.", TX))
    for _, r in proc.sort_values("data").iterrows() if not proc.empty else []:
        bloco = [[Paragraph(f"<b>{pd.to_datetime(r['data']):%d/%m/%Y}</b> · {r.get('motivo') or ''} · canal: {r.get('canal') or ''}"
                            + (f" · técnico: {r['tecnico']}" if r.get("tecnico") else "") + (f" · OS {r['os']}" if r.get("os") else ""), CEL)],
                 [Paragraph(f"<b>Relato:</b> {r.get('descricao') or '—'}", CEL)],
                 [Paragraph(f"<b>Análise:</b> {r.get('analise') or '—'}", CEL)]]
        t = Table(bloco, colWidths=[17.8 * cm])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9D3D1")),
                               ("BACKGROUND", (0, 0), (-1, 0), FUNDO), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        h.append(Spacer(1, 4))
        h.append(KeepTogether(t))

    doc.build(h, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
