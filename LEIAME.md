# Painel Operacional OFS — todos os serviços

Mesma lógica do painel de manutenção (planejado × resultado, cruzando pela OS), mas para
instalação, retirada, reinstalação, renovação e manutenção, com filtro por família de serviço.

## Como o painel classifica cada atendimento (todos os serviços)

Para cada dia com **resultado** importado, o painel usa o **planejado vigente** (o mais recente importado até o dia).
Uma OS é **agendada** se está nesse planejado **e** apareceu pela primeira vez num planejado exportado **antes do dia**.

| Situação | Classificação |
|---|---|
| Agendada e concluída | Atendimento executado |
| Agendada e não concluída | Improdutiva |
| Agendada e cancelada | Cancelada |
| Agendada e pendente/iniciada | Status intermediário |
| Agendada e não aparece no resultado (nem trocada por outra OS com o mesmo ticket + placa) | OS perdida |
| Sem prova de agendamento e concluída | Encaixe |
| Sem prova de agendamento e não concluída | Improdutiva (origem encaixe) |

Indicadores: Execução da agenda = executados ÷ agendados · Improdutividade = improdutivas ÷ (executados + encaixes +
improdutivas) · Cancelamento e Perda de OS = ÷ agendados · Participação de encaixes = encaixes ÷ (executados + encaixes).
O MCI/MD continua sendo acompanhado no painel de manutenção.

## 1. Testar no seu computador (opcional, ~10 min)

1. Instale o Python 3.11+ em python.org (marque "Add Python to PATH").
2. Abra o terminal na pasta do painel e rode:
   ```
   pip install -r requirements.txt
   streamlit run app.py
   ```
3. O painel abre no navegador. Os dados ficam no arquivo `dados_painel.db` da pasta.

## 2. Colocar na internet (gratuito)

**a) Banco de dados — Supabase**
1. Crie uma conta em supabase.com e um projeto novo (região São Paulo). Anote a senha do banco.
2. Em *Project Settings → Database → Connection string*, escolha **Session pooler** e copie o endereço.
   Troque `[YOUR-PASSWORD]` pela senha do banco. As tabelas são criadas sozinhas na primeira importação.

**b) Código — GitHub**
1. Crie uma conta em github.com e um repositório **privado** (ex.: `painel-ofs`).
2. Use *Add file → Upload files* e envie todos os arquivos desta pasta, inclusive a pasta `.streamlit`
   (sem o `secrets.toml`). Nunca suba CSVs com dados.

**c) Publicar — Streamlit Community Cloud**
1. Entre em share.streamlit.io com a conta do GitHub e clique em *Create app*.
2. Escolha o repositório e o arquivo `app.py`.
3. Em *Advanced settings → Secrets*, cole (com seus valores):
   ```
   senha_app = "uma-senha-forte"
   db_url = "postgresql://postgres.xxxx:SENHA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
   ```
4. Clique em *Deploy*. Em *Settings → Sharing*, deixe o app visível só para quem você convidar.

## 3. Rotina de uso

1. **Oficinas** (quando mudar): Dados → Oficinas → importar cadastro, ou incluir as que aparecerem "Sem cadastro" e completar consultor e UF-base.
2. **Planejado** (a cada ~3 dias): Dados → Planejado, informe a data da exportação e suba o CSV com as datas futuras.
3. **Resultado** (diário): Dados → Resultado, suba o CSV do dia. Reimportar o mesmo dia substitui.

## Próximo passo (fase 2)

Visão para as oficinas: login por oficina, mostrando só os números dela e as OS com número e situação.

## Retrabalho (versão 1.4)

1. **Dados → Retrabalho:** suba a base do administrativo (uma linha por visita: "1ª visita" e "Retorno").
   Pode subir o ano inteiro; reimportar atualiza os casos e mantém as análises já feitas.
2. **🔁 Retrabalho → Análise:** o painel já separou os casos em Retrabalho, Expurgado e Para analisar.
   Analise os pendentes, marque a decisão final, a causa e a observação e clique em Salvar.
   A decisão manual vale por cima da automática.
3. **Configurações → Regras automáticas de retrabalho:** termos e prazos editáveis; a triagem é refeita na hora.

## Auditoria (versão 1.8)

**✅ Auditoria → Nova auditoria:** escolha período, oficina e técnico, selecione a OS (ou sorteie uma não auditada),
preencha tipo, sinistro e os itens (Aprovado / Reprovado / Não se aplica) e salve. Oficina, técnico, OS, data e
serviço vêm do sistema. A OS é reprovada se qualquer item for reprovado. Itens, meta e auditor padrão ficam em Configurações.
