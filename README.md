# Sistema de Auditoria Operacional — Postos de Combustíveis

MVP robusto para auditoria automática de LMC, aferição de bombas e fechamento de caixa.

---

## Estrutura do Projeto

```
projeto/
├── app/
│   ├── models/
│   │   └── schemas.py          # Tipos de dados e configurações de tolerância
│   ├── rules/
│   │   ├── lmc.py              # Regras de negócio do LMC
│   │   ├── caixa.py            # Regras de negócio do caixa
│   │   └── afericao.py         # Regras de aferição de bombas
│   ├── services/
│   │   ├── parser_service.py   # Leitura e validação de arquivos
│   │   ├── auditoria_service.py# Orquestrador da auditoria
│   │   └── relatorio_service.py# Geração de relatórios (TXT/CSV/JSON)
│   └── main.py                 # Entry point com CLI
├── data/
│   ├── entradas/               # Arquivos de entrada (lmc.xlsx, caixa.csv, afericao.xlsx)
│   └── relatorios/             # Relatórios gerados automaticamente
├── generate_examples.py        # Gerador de dados fictícios para teste
└── requirements.txt
```

---

## Instalação

```bash
pip install -r requirements.txt
```

---

## Como Usar

### 1. Gerar dados de exemplo (com anomalias embutidas para teste)

```bash
python generate_examples.py
```

Cria em `data/entradas/`:
- `lmc.xlsx` — 25 registros, 5 tanques × 5 dias
- `caixa.csv` — 10 registros, 5 operadores × 2 dias de anomalias
- `afericao.xlsx` — 25 registros, 5 bombas × 5 dias

### 2. Executar auditoria (posto único)

```bash
python -m app.main
python -m app.main --posto "Posto Central" --pasta data/entradas
```

### 3. Executar auditoria (múltiplos postos)

```bash
python -m app.main --multi --pasta data/postos
```

Onde `data/postos/` contém subpastas, uma por posto:
```
data/postos/
    posto_central/
        lmc.xlsx
        caixa.csv
        afericao.xlsx
    posto_norte/
        ...
```

### 4. Tolerâncias customizáveis via CLI

```bash
python -m app.main \
  --lmc-tolerancia-alto 200 \
  --caixa-tolerancia-alto 1000 \
  --afericao-tolerancia-medio 0.4 \
  --limite-sangria 1500
```

### 5. Modo verbose (logs detalhados)

```bash
python -m app.main --verbose
```

---

## Saída

Relatório impresso no terminal + 3 arquivos em `data/relatorios/`:

| Formato | Conteúdo |
|---------|----------|
| `.txt`  | Relatório completo legível, com score de conformidade e ações prioritárias |
| `.csv`  | Tabela de divergências para importação em Excel ou Power BI |
| `.json` | Estrutura completa para integração com APIs e sistemas externos |

---

## Regras de Negócio Implementadas

### LMC (Livro de Movimentação de Combustíveis)
| Regra | Descrição |
|-------|-----------|
| R1 — Balanço de estoque | `estoque_final_esperado = estoque_inicial + entradas - vendas` |
| R2 — Estoque negativo | Valor fisicamente impossível → sempre CRÍTICO |
| R3 — Entrada sem venda | Recebeu combustível mas não registrou vendas |
| R4 — Variação extrema | Vendas >80% acima ou abaixo da média histórica |

### Caixa
| Regra | Descrição |
|-------|-----------|
| R1 — Diferença no total | `total_calculado = dinheiro + cartão + PIX - sangria` vs `total_informado` |
| R2 — Sangria excessiva | Sangria acima do limite configurável (padrão: R$ 2.000) |
| R3 — Caixa zerado | Todos os valores zerados (turno fantasma) |
| R4 — Concentração em dinheiro | >95% do total em espécie (dificulta rastreabilidade) |
| R5 — Padrão recorrente | Mesmo operador com diferença em múltiplos dias |

### Aferição de Bombas
| Regra | Descrição |
|-------|-----------|
| R1 — Tolerância INMETRO | Erro percentual acima de ±0,5% (Portaria INMETRO 9/2002) |
| R2/R3 — Viés sistemático | Bomba sempre erra na mesma direção (possível adulteração) |
| R4 — Instabilidade | Alta variação de erro entre aferições (problema mecânico) |

### Classificação de Risco

| Nível | LMC | Caixa | Aferição |
|-------|-----|-------|----------|
| BAIXO | < 30 L | < R$ 10 | < 0,3% |
| MÉDIO | 30–100 L | R$ 10–100 | 0,3–0,5% |
| ALTO | 100–300 L | R$ 100–500 | 0,5–1,0% |
| CRÍTICO | > 300 L | > R$ 500 | > 1,0% |

---

## Expansão Futura (já preparado)

O código foi estruturado para acomodar:

- **Banco de dados (PostgreSQL):** substituir leitura de arquivos por queries no `parser_service.py`
- **Interface web (Streamlit/FastAPI):** `auditoria_service.py` já expõe interface limpa para ser consumida por API
- **Multi-posto:** `AuditoriaMultiPostoService` já implementado
- **Tolerâncias por posto:** passar `ConfiguracaoTolerancia` diferente por instância de `AuditoriaService`
- **Agendamento:** executar via cron ou task scheduler apontando para `python -m app.main`
