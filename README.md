# Gestão X — Automação de Notas Fiscais (MEIs)

Robô que entra no Gestão X, filtra os chamados do grupo **CSC - Contas a Pagar - Lançamentos**, abre cada um, identifica o anexo que é **Nota Fiscal** e salva em `~/Desktop/Nota Fiscal - MEIs/`. Tudo registrado numa planilha de controle pra nunca duplicar.

## Status atual: Etapa 1

| Etapa | O que faz | Status |
|---|---|---|
| 0 | Sanity check: só abre o browser, loga, lista linhas | ✅ pronto |
| 1 | Processa **1 chamado** de ponta a ponta com classificação + planilha | ✅ pronto |
| 2 | Itera **todos os chamados** visíveis (liga `PROCESS_ALL_TICKETS=True`) | ⏳ aguardando validação da Etapa 1 |
| 3+ | Paginação, agendamento, melhorias diversas | ⏳ |

> A Etapa 1 está **propositalmente limitada a 1 chamado** (configurável). Você valida o fluxo, depois flipa a flag e partimos pra Etapa 2.

## Estrutura

```
gestao_x_automation/
├── main.py            # orquestração completa (Etapa 1)
├── sanity_check.py    # Etapa 0: só abre e lista (validação visual)
├── classifier.py      # regras de "o que é NF" (P1/P2/P3)
├── tracker.py         # planilha controle_notas_fiscais.xlsx
├── config.py          # credenciais, caminhos, modo de execução
├── requirements.txt
└── README.md
```

## Pré-requisitos

- Python 3.10+
- Playwright + Chromium:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```

## Como usar

### 1) Configurar credenciais

Edite `config.py` e preencha `USERNAME` e `PASSWORD`, **ou** use variáveis de ambiente:

```bash
export GESTAO_X_USER="joao.faria"
export GESTAO_X_PASS="147258"
```

### 2) Validar os seletores (Etapa 0 — RECOMENDADO antes da Etapa 1)

```bash
python sanity_check.py
```

O browser abre, ele loga, aplica os filtros, lista as linhas que encontrou e ainda abre o primeiro chamado pra você ver a grade de anexos. Se aparecer "0 linhas", os seletores da Telerik mudaram e precisamos ajustar antes de rodar a Etapa 1.

### 3) Rodar a Etapa 1

```bash
python main.py
```

Ele vai:
1. Logar
2. Aplicar filtro de serviço + grupo
3. Abrir o **primeiro** chamado
4. Ler o código (`JP0000172118`, etc.)
5. Checar se já tá na planilha (se sim, pula)
6. Listar os anexos
7. Classificar e escolher **1** candidato a NF
8. Baixar pra `~/Desktop/Nota Fiscal - MEIs/`
9. Registrar na planilha `~/Desktop/Nota Fiscal - MEIs/controle_notas_fiscais.xlsx`
10. Fechar o chamado

### 4) Quando a Etapa 1 funcionar → Etapa 2

Em `config.py`, mude:
```python
PROCESS_ALL_TICKETS = True
```

E rode `python main.py` de novo. Agora ele itera todos os chamados visíveis (respeitando o controle de duplicidade).

## Regras de classificação (resumo)

| Prioridade | Quando | Exemplo |
|---|---|---|
| **P1** | Nome contém `NF`, `NF-e` ou `NFe` | `NF 56 GUSTAVO LIMA.pdf`, `NF-e 18_2507507...pdf` |
| **P2** | ≥ 30 dígitos consecutivos (chave NF-e tem 44) | `250750722683987605867000000000000000000000000.pdf` |
| **P3** | `.pdf` ou `.xml` sem pista forte, mas plausível | `nota_fiscal_cliente_x.pdf`, `documento_recebimento.xml` |
| **0 — descartado** | Tem `OC`; é número curto (≤8 dígitos); é `.png`/`.jpg`/`.docx`/etc.; é "Captura de tela" | `OC Instalação.pdf`, `206743.pdf`, `Captura de tela 2026 09 09.png` |

**1 chamado = 1 arquivo salvo.** Se houver vários candidatos, o de menor número de prioridade vence. Empate = primeiro da lista.

## Onde os dados ficam

- **Notas fiscais:** `~/Desktop/Nota Fiscal - MEIs/<código>_<nome original>.pdf`
- **Planilha de controle:** `~/Desktop/Nota Fiscal - MEIs/controle_notas_fiscais.xlsx`

A planilha tem as colunas: `Chamado | Total de anexos | Arquivo salvo | Status | Data/hora | Caminho completo`

## Solução de problemas

- **"0 linhas no grid principal"** → os filtros não retornaram nada. Pode ser:
  - Telerik `get_by_alt_text("Filter DESCRICAO_SERVICO")` mudou de assinatura. Rode o `sanity_check.py` e me diga o que aparece.
  - Filtro de serviço/grupo tá com string diferente da que o sistema espera. Confere em `config.py`.

- **"Não consegui ler o código do chamado"** → o seletor do header mudou. O fallback tenta achar um padrão `XX000000000` no body inteiro. Se não achar, me manda o HTML do header (F12 no Chrome) que eu ajusto.

- **"Botão 'Close' não encontrado"** → troquei pra ESC como fallback, mas se travar, me avisa.

- **Download fica em Downloads/ ao invés de Nota Fiscal - MEIs/** → o `save_as` tá falhando. Confere se o caminho da pasta tá acessível. Em Windows, `~/Desktop` resolve pra `C:\Users\seu_user\Desktop`. Em VM/container isso pode ser diferente.

## Segurança

- **NÃO** commita `config.py` com credenciais reais (já tem `.gitignore`).
- Em produção, prefira variáveis de ambiente (`GESTAO_X_USER` / `GESTAO_X_PASS`).
