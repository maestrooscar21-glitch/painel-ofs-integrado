# Integração OFS — versão de validação (somente leitura)

## Como testar

1. Faça uma cópia do aplicativo original. Não substitua o painel de produção.
2. Configure `.streamlit/secrets.toml` usando o exemplo, com as credenciais do banco PostgreSQL já existente. **Não envie nem publique a senha.**
3. Defina `[integracao_ofs] habilitada = true` para habilitar leitura das views `painel_marcos.ofs_todos`.
4. Instale dependências de `requirements.txt` e execute `streamlit run app.py`.
5. Confira contagens e filtros contra os dados OFS do painel anterior.

## Limites e cuidados

- Não grava nas tabelas OFS de produção e não substitui nem apaga OS.
- Importações OFS, edições de oficinas, financeiro, retrabalho, auditorias e demais gravações ficam **bloqueadas** nesse modo; a adaptação de escrita ainda não foi validada.
- A consulta `ofs_todos` usa `UNION ALL`: contém aparições de planejado e resultado, **não OS únicas**.
- O painel original filtra por `id_oficina` e cadastro `oficinas`; valide a disponibilidade desse cadastro e o mapeamento do JSON antes de interpretar indicadores.
- A leitura do cadastro de oficinas e de outros módulos ainda segue a estrutura original. Se as tabelas não existirem, algumas abas podem aparecer vazias. Não use o painel para decisões até validar esses pontos.
- Para voltar ao modo original, configure `habilitada = false` e use o banco original do painel.
- **Próxima etapa**: adaptar com segurança a persistência das tabelas auxiliares e definir chave financeira por lançamento (não apenas OS).
