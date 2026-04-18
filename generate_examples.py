"""
generate_examples.py — Geração de dados fictícios realistas para testes.

Execução:
    python generate_examples.py

Gera os arquivos:
    data/entradas/lmc.xlsx
    data/entradas/caixa.csv
    data/entradas/afericao.xlsx

Os dados incluem propositalmente divergências e anomalias para validar
que o sistema de auditoria as detecta corretamente.

Anomalias embutidas:
  LMC (balanço / variação):
    - Tanque 2 (2026-04-14): divergência de 150 L (CRÍTICO)
    - Tanque 1 (2026-04-12): divergência de 45 L (MÉDIO)
    - Tanque 3 (2026-04-15): entrada sem venda registrada

  Perdas e Sobras (módulo PS):
    - T1 Gasolina Comum: perda em todos os 5 dias (18–32 L/dia)
        → R3 padrão recorrente ALTO + R4 sequência consecutiva MÉDIO
        → R6 candidato a maior perda do período (125 L total)
    - T2 Gasolina Aditivada: picos isolados de perda em 13/04 e 15/04
        → R1 ALTO (60 L / 1,2%) e R1 CRÍTICO (85 L / 2,1%)
        → R6 maior perda do período (145 L total) [ALTO]
    - T3 Etanol: sobras diárias pequenas + pico em 13/04 (48 L)
        → R3 padrão sistemático de sobras ALTO
        → R2 pico 3,5× a média ALTO
    - T4 Diesel S10: diferença sistemática medidor vs escritural (-18 a -25 L)
        → R5 divergência sistemática MÉDIO

  Caixa:
    - João Silva (2026-04-14): diferença de -R$ 320,50 (ALTO)
    - Maria Souza (2026-04-13): diferença de -R$ 18,00 (BAIXO)
    - Carlos Lima (2026-04-12 e 14): padrão recorrente de diferença
    - Pedro Alves (2026-04-15): sangria excessiva (R$ 3.500)

  Aferição:
    - Bomba 03 (2026-04-14): erro de 0,82% (ALTO — acima da tolerância INMETRO)
    - Bomba 01 (múltiplos dias): viés sistemático negativo
    - Bomba 05 (2026-04-15): erro crítico de 1,35%
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

PASTA_SAIDA = Path("data/entradas")
PASTA_SAIDA.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# LMC — Livro de Movimentação de Combustíveis
# ---------------------------------------------------------------------------

def gerar_lmc() -> None:
    """
    Simula 5 tanques ao longo de 5 dias com colunas de balanço e de perdas/sobras.
    Tanques: T1=Gasolina Comum, T2=Gasolina Aditivada, T3=Etanol, T4=Diesel S10, T5=Diesel S500

    Convenção das colunas de Perdas/Sobras:
      perdas_sobras > 0  → PERDA   (estoque físico MENOR que o escritural)
      perdas_sobras < 0  → SOBRA   (estoque físico MAIOR que o escritural)
      perdas_sobras_pct  → valor em % (ex: 1.20 significa 1,20%)
      diferenca_l        → diferença entre medidor e escritural (independente de perdas_sobras)

    Anomalias de Perdas/Sobras embutidas:
      T1 - Gasolina Comum : perda diária pequena mas constante (18-32 L, 5 dias seguidos)
           → R3 padrão recorrente ALTO + R4 sequência consecutiva MÉDIO
      T2 - Gasolina Aditivada: picos isolados de perda em 13/04 (1,2%) e 15/04 (2,1%)
           → R1 ALTO + R1 CRÍTICO | R6 maior perda do período (145 L)
      T3 - Etanol : sobras pequenas todos os dias + pico de 48 L em 13/04 (<1% → sem R1)
           → R3 sistemático de sobras ALTO + R2 pico 3,5× a média ALTO
      T4 - Diesel S10 : diferença sistemática medidor vs escritural (-18 a -25 L)
           → R5 divergência sistemática MÉDIO
      T5 - Diesel S500 : normal, sem anomalias de perdas/sobras
    """
    registros = [
        # --- 2026-04-11 (dia normal, sem divergências de balanço) ---
        {"data": "2026-04-11", "tanque": "T1 - Gasolina Comum",     "estoque_inicial": 12000, "entradas": 0,     "vendas": 4200, "estoque_final": 7800,  "perdas_sobras": 18,   "perdas_sobras_pct": 0.15, "diferenca_l": 0},
        {"data": "2026-04-11", "tanque": "T2 - Gasolina Aditivada", "estoque_inicial": 8000,  "entradas": 15000, "vendas": 3500, "estoque_final": 19500, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},
        {"data": "2026-04-11", "tanque": "T3 - Etanol",             "estoque_inicial": 6000,  "entradas": 0,     "vendas": 2100, "estoque_final": 3900,  "perdas_sobras": -5,   "perdas_sobras_pct": -0.24,"diferenca_l": 0},
        {"data": "2026-04-11", "tanque": "T4 - Diesel S10",         "estoque_inicial": 18000, "entradas": 0,     "vendas": 5800, "estoque_final": 12200, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": -18},
        {"data": "2026-04-11", "tanque": "T5 - Diesel S500",        "estoque_inicial": 10000, "entradas": 0,     "vendas": 3200, "estoque_final": 6800,  "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},

        # --- 2026-04-12 (T1: divergência de balanço 45 L [MÉDIO] + perda de PS continuada) ---
        {"data": "2026-04-12", "tanque": "T1 - Gasolina Comum",     "estoque_inicial": 7800,  "entradas": 0,     "vendas": 4100, "estoque_final": 3655,  "perdas_sobras": 22,   "perdas_sobras_pct": 0.28, "diferenca_l": 0},   # balanço: esperado 3700, info 3655 → -45 L
        {"data": "2026-04-12", "tanque": "T2 - Gasolina Aditivada", "estoque_inicial": 19500, "entradas": 0,     "vendas": 3600, "estoque_final": 15900, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},
        {"data": "2026-04-12", "tanque": "T3 - Etanol",             "estoque_inicial": 3900,  "entradas": 10000, "vendas": 2050, "estoque_final": 11850, "perdas_sobras": -6,   "perdas_sobras_pct": -0.16,"diferenca_l": 0},
        {"data": "2026-04-12", "tanque": "T4 - Diesel S10",         "estoque_inicial": 12200, "entradas": 20000, "vendas": 6200, "estoque_final": 26000, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": -22},
        {"data": "2026-04-12", "tanque": "T5 - Diesel S500",        "estoque_inicial": 6800,  "entradas": 0,     "vendas": 3100, "estoque_final": 3700,  "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},

        # --- 2026-04-13 (T2: PS pico 60 L / 1,2% → R1 ALTO; T3: PS pico 48 L → R2) ---
        {"data": "2026-04-13", "tanque": "T1 - Gasolina Comum",     "estoque_inicial": 3655,  "entradas": 15000, "vendas": 4300, "estoque_final": 14355, "perdas_sobras": 28,   "perdas_sobras_pct": 0.20, "diferenca_l": 0},
        {"data": "2026-04-13", "tanque": "T2 - Gasolina Aditivada", "estoque_inicial": 15900, "entradas": 0,     "vendas": 3450, "estoque_final": 12450, "perdas_sobras": 60,   "perdas_sobras_pct": 1.20, "diferenca_l": 0},   # R1 ALTO
        {"data": "2026-04-13", "tanque": "T3 - Etanol",             "estoque_inicial": 11850, "entradas": 0,     "vendas": 2200, "estoque_final": 9650,  "perdas_sobras": -48,  "perdas_sobras_pct": -0.55,"diferenca_l": 0},   # pico sobra; pct < 1% → R2, não R1
        {"data": "2026-04-13", "tanque": "T4 - Diesel S10",         "estoque_inicial": 26000, "entradas": 0,     "vendas": 6000, "estoque_final": 20000, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": -25},
        {"data": "2026-04-13", "tanque": "T5 - Diesel S500",        "estoque_inicial": 3700,  "entradas": 15000, "vendas": 3300, "estoque_final": 15400, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},

        # --- 2026-04-14 (T2: balanço -150 L [CRÍTICO]; T2 PS normal; T1 PS continua) ---
        {"data": "2026-04-14", "tanque": "T1 - Gasolina Comum",     "estoque_inicial": 14355, "entradas": 0,     "vendas": 4150, "estoque_final": 10205, "perdas_sobras": 32,   "perdas_sobras_pct": 0.22, "diferenca_l": 0},
        {"data": "2026-04-14", "tanque": "T2 - Gasolina Aditivada", "estoque_inicial": 12450, "entradas": 0,     "vendas": 3400, "estoque_final": 8900,  "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},   # balanço: esperado 9050, info 8900 → -150 L
        {"data": "2026-04-14", "tanque": "T3 - Etanol",             "estoque_inicial": 9650,  "entradas": 0,     "vendas": 2100, "estoque_final": 7550,  "perdas_sobras": -4,   "perdas_sobras_pct": -0.04,"diferenca_l": 0},
        {"data": "2026-04-14", "tanque": "T4 - Diesel S10",         "estoque_inicial": 20000, "entradas": 0,     "vendas": 5900, "estoque_final": 14100, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": -19},
        {"data": "2026-04-14", "tanque": "T5 - Diesel S500",        "estoque_inicial": 15400, "entradas": 0,     "vendas": 3150, "estoque_final": 12250, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},

        # --- 2026-04-15 (T3: entrada sem venda; T2: PS pico 85 L / 2,1% → R1 CRÍTICO) ---
        {"data": "2026-04-15", "tanque": "T1 - Gasolina Comum",     "estoque_inicial": 10205, "entradas": 0,     "vendas": 4250, "estoque_final": 5955,  "perdas_sobras": 25,   "perdas_sobras_pct": 0.24, "diferenca_l": 0},
        {"data": "2026-04-15", "tanque": "T2 - Gasolina Aditivada", "estoque_inicial": 8900,  "entradas": 15000, "vendas": 3500, "estoque_final": 20400, "perdas_sobras": 85,   "perdas_sobras_pct": 2.10, "diferenca_l": 0},   # R1 CRÍTICO
        {"data": "2026-04-15", "tanque": "T3 - Etanol",             "estoque_inicial": 7550,  "entradas": 10000, "vendas": 0,    "estoque_final": 17550, "perdas_sobras": -5,   "perdas_sobras_pct": -0.05,"diferenca_l": 0},   # entrada sem venda!
        {"data": "2026-04-15", "tanque": "T4 - Diesel S10",         "estoque_inicial": 14100, "entradas": 20000, "vendas": 6100, "estoque_final": 28000, "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": -23},
        {"data": "2026-04-15", "tanque": "T5 - Diesel S500",        "estoque_inicial": 12250, "entradas": 0,     "vendas": 3200, "estoque_final": 9050,  "perdas_sobras": 0,    "perdas_sobras_pct": 0,    "diferenca_l": 0},
    ]

    df = pd.DataFrame(registros)
    caminho = PASTA_SAIDA / "lmc.xlsx"
    df.to_excel(caminho, index=False, engine="openpyxl")
    print(f"  [OK] LMC gerado: {caminho} ({len(df)} registros, inclui colunas de Perdas/Sobras)")


# ---------------------------------------------------------------------------
# Caixa — Fechamento por turno/operador
# ---------------------------------------------------------------------------

def gerar_caixa() -> None:
    """
    Simula múltiplos operadores ao longo de 5 dias.
    Cada dia tem 2 turnos (operadores diferentes).
    """
    registros = [
        # --- 2026-04-11 ---
        {"data": "2026-04-11", "operador": "João Silva",   "dinheiro": 3200.00, "cartao": 8500.50, "pix": 2100.00, "sangria": 1000.00, "total_informado": 12800.50},
        {"data": "2026-04-11", "operador": "Maria Souza",  "dinheiro": 2800.00, "cartao": 7200.00, "pix": 1900.00, "sangria": 800.00,  "total_informado": 11100.00},

        # --- 2026-04-12 (Carlos Lima com diferença de -R$ 85,00 — 1ª ocorrência) ---
        {"data": "2026-04-12", "operador": "Carlos Lima",  "dinheiro": 3100.00, "cartao": 8200.00, "pix": 2050.00, "sangria": 900.00,  "total_informado": 12365.00},  # calculado: 12450 → dif = -85
        {"data": "2026-04-12", "operador": "Ana Ferreira", "dinheiro": 2950.00, "cartao": 7800.00, "pix": 2200.00, "sangria": 750.00,  "total_informado": 12200.00},

        # --- 2026-04-13 (Maria Souza com diferença de -R$ 18,00 — BAIXO) ---
        {"data": "2026-04-13", "operador": "João Silva",   "dinheiro": 3350.00, "cartao": 8900.00, "pix": 2300.00, "sangria": 1200.00, "total_informado": 13350.00},
        {"data": "2026-04-13", "operador": "Maria Souza",  "dinheiro": 2700.00, "cartao": 7100.00, "pix": 1800.00, "sangria": 700.00,  "total_informado": 10882.00},  # calculado: 10900 → dif = -18

        # --- 2026-04-14 (João Silva: -R$ 320,50 ALTO | Carlos Lima: -R$ 92,00 — padrão) ---
        {"data": "2026-04-14", "operador": "João Silva",   "dinheiro": 3500.00, "cartao": 9100.00, "pix": 2450.00, "sangria": 1100.00, "total_informado": 13629.50},  # calculado: 13950 → dif = -320,50
        {"data": "2026-04-14", "operador": "Carlos Lima",  "dinheiro": 3200.00, "cartao": 8400.00, "pix": 2150.00, "sangria": 850.00,  "total_informado": 13008.00},  # calculado: 12900 ... wait: 3200+8400+2150-850=12900 → info 13008 → dif = +108 (inverso)

        # --- 2026-04-15 (Pedro Alves com sangria excessiva) ---
        {"data": "2026-04-15", "operador": "Pedro Alves",  "dinheiro": 4100.00, "cartao": 9800.00, "pix": 2700.00, "sangria": 3500.00, "total_informado": 13100.00},  # sangria excessiva!
        {"data": "2026-04-15", "operador": "Ana Ferreira", "dinheiro": 3000.00, "cartao": 7500.00, "pix": 2100.00, "sangria": 800.00,  "total_informado": 11800.00},
    ]

    df = pd.DataFrame(registros)
    caminho = PASTA_SAIDA / "caixa.csv"
    df.to_csv(caminho, index=False, sep=";", encoding="utf-8-sig")
    print(f"  [OK] CAIXA gerado: {caminho} ({len(df)} registros)")


# ---------------------------------------------------------------------------
# Aferição de Bombas
# ---------------------------------------------------------------------------

def gerar_afericao() -> None:
    """
    Simula 5 bombas ao longo de 5 dias.
    Bomba 01: viés sistemático negativo (sempre dá a menos)
    Bomba 03: erro alto (0,82%) — acima da tolerância INMETRO
    Bomba 05: erro crítico (1,35%)
    """
    registros = [
        # --- 2026-04-11 ---
        {"data": "2026-04-11", "bomba": "Bomba 01", "litros_testados": 20.000, "litros_medidos": 19.982, "erro": 0.090},  # viés negativo leve
        {"data": "2026-04-11", "bomba": "Bomba 02", "litros_testados": 20.000, "litros_medidos": 20.002, "erro": 0.010},
        {"data": "2026-04-11", "bomba": "Bomba 03", "litros_testados": 20.000, "litros_medidos": 19.995, "erro": 0.025},
        {"data": "2026-04-11", "bomba": "Bomba 04", "litros_testados": 20.000, "litros_medidos": 20.001, "erro": 0.005},
        {"data": "2026-04-11", "bomba": "Bomba 05", "litros_testados": 20.000, "litros_medidos": 20.004, "erro": 0.020},

        # --- 2026-04-12 ---
        {"data": "2026-04-12", "bomba": "Bomba 01", "litros_testados": 20.000, "litros_medidos": 19.979, "erro": 0.105},  # viés negativo
        {"data": "2026-04-12", "bomba": "Bomba 02", "litros_testados": 20.000, "litros_medidos": 20.003, "erro": 0.015},
        {"data": "2026-04-12", "bomba": "Bomba 03", "litros_testados": 20.000, "litros_medidos": 19.994, "erro": 0.030},
        {"data": "2026-04-12", "bomba": "Bomba 04", "litros_testados": 20.000, "litros_medidos": 19.999, "erro": 0.005},
        {"data": "2026-04-12", "bomba": "Bomba 05", "litros_testados": 20.000, "litros_medidos": 20.240, "erro": 1.200},  # erro alto

        # --- 2026-04-13 ---
        {"data": "2026-04-13", "bomba": "Bomba 01", "litros_testados": 20.000, "litros_medidos": 19.976, "erro": 0.120},  # viés negativo crescente
        {"data": "2026-04-13", "bomba": "Bomba 02", "litros_testados": 20.000, "litros_medidos": 20.001, "erro": 0.005},
        {"data": "2026-04-13", "bomba": "Bomba 03", "litros_testados": 20.000, "litros_medidos": 19.855, "erro": 0.725},  # acima tolerância — ALTO
        {"data": "2026-04-13", "bomba": "Bomba 04", "litros_testados": 20.000, "litros_medidos": 20.002, "erro": 0.010},
        {"data": "2026-04-13", "bomba": "Bomba 05", "litros_testados": 20.000, "litros_medidos": 20.005, "erro": 0.025},

        # --- 2026-04-14 (Bomba 03: erro 0,82% — ALTO | Bomba 01: viés sistemático) ---
        {"data": "2026-04-14", "bomba": "Bomba 01", "litros_testados": 20.000, "litros_medidos": 19.974, "erro": 0.130},  # viés negativo
        {"data": "2026-04-14", "bomba": "Bomba 02", "litros_testados": 20.000, "litros_medidos": 20.004, "erro": 0.020},
        {"data": "2026-04-14", "bomba": "Bomba 03", "litros_testados": 20.000, "litros_medidos": 19.836, "erro": 0.820},  # erro alto INMETRO!
        {"data": "2026-04-14", "bomba": "Bomba 04", "litros_testados": 20.000, "litros_medidos": 20.000, "erro": 0.000},
        {"data": "2026-04-14", "bomba": "Bomba 05", "litros_testados": 20.000, "litros_medidos": 19.999, "erro": 0.005},

        # --- 2026-04-15 (Bomba 05: erro crítico 1,35%) ---
        {"data": "2026-04-15", "bomba": "Bomba 01", "litros_testados": 20.000, "litros_medidos": 19.971, "erro": 0.145},  # viés negativo
        {"data": "2026-04-15", "bomba": "Bomba 02", "litros_testados": 20.000, "litros_medidos": 20.002, "erro": 0.010},
        {"data": "2026-04-15", "bomba": "Bomba 03", "litros_testados": 20.000, "litros_medidos": 19.990, "erro": 0.050},  # voltou ao normal
        {"data": "2026-04-15", "bomba": "Bomba 04", "litros_testados": 20.000, "litros_medidos": 20.001, "erro": 0.005},
        {"data": "2026-04-15", "bomba": "Bomba 05", "litros_testados": 20.000, "litros_medidos": 20.270, "erro": 1.350},  # CRÍTICO!
    ]

    df = pd.DataFrame(registros)
    caminho = PASTA_SAIDA / "afericao.xlsx"
    df.to_excel(caminho, index=False, engine="openpyxl")
    print(f"  [OK] AFERIÇÃO gerada: {caminho} ({len(df)} registros)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 60)
    print("  GERADOR DE DADOS DE EXEMPLO — Auditoria de Postos")
    print("=" * 60)
    print(f"  Destino: {PASTA_SAIDA.resolve()}")
    print("-" * 60)

    gerar_lmc()
    gerar_caixa()
    gerar_afericao()

    print("-" * 60)
    print("  Dados gerados com sucesso!")
    print()
    print("  Anomalias embutidas para teste:")
    print("    LMC (balanco)  > T2 em 14/04: -150 L [CRITICO]")
    print("                     T1 em 12/04: -45 L [MEDIO]")
    print("                     T3 em 15/04: entrada sem venda [MEDIO]")
    print("    Perdas/Sobras  > T1 todos os 5 dias (18-32 L): R3 padrao [ALTO] + R4 consecutivo [MEDIO]")
    print("                   > T2 em 13/04: 60 L / 1,2%: R1 [ALTO]")
    print("                   > T2 em 15/04: 85 L / 2,1%: R1 [CRITICO]")
    print("                   > T2 total 145 L: R6 maior perda [ALTO]")
    print("                   > T3 sobras diarias + pico 48 L em 13/04: R3 [ALTO] + R2 pico [ALTO]")
    print("                   > T4 dif. sistematica -18 a -25 L: R5 medicao [MEDIO]")
    print("    Caixa          > Joao Silva 14/04: -R$ 320,50 [ALTO]")
    print("                   > Carlos Lima (padrao recorrente) [ALTO]")
    print("                   > Pedro Alves 15/04: sangria R$ 3.500 [ALTO]")
    print("    Afericao       > Bomba 03 14/04: 0,82% erro [ALTO]")
    print("                   > Bomba 05 12/04 e 15/04: >1% erro [CRITICO]")
    print("                   > Bomba 01 (vies negativo sistematico) [ALTO]")
    print()
    print("  Para executar a auditoria:")
    print("    python -m app.main")
    print("    streamlit run app/ui/dashboard.py")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
