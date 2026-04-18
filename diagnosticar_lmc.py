"""
diagnosticar_lmc.py — Inspeciona a estrutura bruta de qualquer Excel de LMC.

Uso:
    python diagnosticar_lmc.py caminho/para/arquivo.xlsx

O script:
  1. Mostra as primeiras linhas brutas (como o pandas lê, sem interpretar)
  2. Detecta em qual linha está o cabeçalho real
  3. Identifica marcadores de produto ("Produto: ...")
  4. Marca linhas de total / subtotal
  5. Remove linhas inválidas e exibe o resultado limpo
  6. Salva o resultado em data/relatorios/lmc_limpo.csv para inspeção
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ARQUIVO_PADRAO = Path("data/entradas/lmc.xlsx")
SAIDA = Path("data/relatorios/lmc_limpo.csv")

PALAVRAS_CABECALHO = {
    "data", "abertura", "entrada", "saida", "fechamento",
    "estoque", "medidor", "folha", "escritural", "afericao",
}

PALAVRAS_TOTAL = {
    "total", "subtotal", "sub-total", "sub total",
    "acumulado", "soma", "resumo", "consolidado",
}

PREFIXOS_PRODUTO = ("produto", "combustivel", "tanque")

SEP = "-" * 72


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sem_acento(texto: str) -> str:
    n = unicodedata.normalize("NFD", texto.lower().strip())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def _celula(val) -> str:
    return "" if pd.isna(val) else str(val).strip()


def _linha_vazia(row: pd.Series) -> bool:
    return all(_celula(v) == "" for v in row)


def _linha_total(row: pd.Series) -> bool:
    textos = [_sem_acento(_celula(v)) for v in row if _celula(v)]
    return any(p in t for t in textos for p in PALAVRAS_TOTAL)


def _linha_produto(row: pd.Series) -> str | None:
    for v in row:
        t = _sem_acento(_celula(v))
        for pref in PREFIXOS_PRODUTO:
            if t.startswith(pref) and len(t) > len(pref) + 1:
                nome = re.sub(rf"^{pref}\s*[:–\-]?\s*", "", _celula(v), flags=re.IGNORECASE)
                return nome.strip() or "Desconhecido"
    return None


def _score_cabecalho(row: pd.Series) -> int:
    """Conta quantas palavras-chave de cabeçalho a linha contém."""
    textos = [_sem_acento(_celula(v)) for v in row]
    return sum(1 for t in textos if any(kw in t for kw in PALAVRAS_CABECALHO))


def _encontrar_cabecalho(df: pd.DataFrame) -> int:
    melhor_linha, melhor_score = 0, 0
    for i, row in df.head(30).iterrows():
        s = _score_cabecalho(row)
        if s > melhor_score:
            melhor_score, melhor_linha = s, int(i)
    return melhor_linha


# ---------------------------------------------------------------------------
# Diagnóstico principal
# ---------------------------------------------------------------------------

def diagnosticar(caminho: Path) -> None:
    print(f"\n{SEP}")
    print(f"  DIAGNÓSTICO LMC: {caminho.name}")
    print(SEP)

    # 1. Carga bruta
    sufixo = caminho.suffix.lower()
    if sufixo in (".xlsx", ".xls"):
        df_raw = pd.read_excel(caminho, header=None, dtype=str)
    elif sufixo == ".csv":
        df_raw = pd.read_csv(caminho, header=None, dtype=str, sep=None, engine="python")
    else:
        print(f"  Formato não suportado: {sufixo}")
        return

    df_raw = df_raw.fillna("")

    print(f"\n  Total de linhas brutas : {len(df_raw)}")
    print(f"  Total de colunas brutas: {len(df_raw.columns)}")

    # 2. Primeiras linhas brutas
    print(f"\n{SEP}")
    print("  LINHAS BRUTAS (primeiras 10)")
    print(SEP)
    with pd.option_context("display.max_columns", None, "display.width", 140, "display.max_colwidth", 30):
        print(df_raw.head(10).to_string(index=True))

    # 3. Detectar cabeçalho
    idx_cab = _encontrar_cabecalho(df_raw)
    print(f"\n{SEP}")
    print(f"  CABEÇALHO DETECTADO na linha {idx_cab}")
    print(SEP)
    cab_row = df_raw.iloc[idx_cab]
    for i, v in enumerate(cab_row):
        if _celula(v):
            print(f"    col {i:>2}: {v!r}")

    # 4. Varredura de linhas
    print(f"\n{SEP}")
    print("  CLASSIFICACAO DAS LINHAS (apos cabecalho)")
    print(SEP)
    print(f"  {'Linha':<6} {'Tipo':<20} {'Conteudo resumido'}")
    print(f"  {'-'*5} {'-'*20} {'-'*44}")

    produto_atual = "(nenhum)"
    linhas_dados: list[dict] = []
    nomes_col = [_celula(v) or f"col_{i}" for i, v in enumerate(df_raw.iloc[idx_cab])]

    for i in range(idx_cab + 1, len(df_raw)):
        row = df_raw.iloc[i]
        resumo = " | ".join(v for v in [_celula(c) for c in row] if v)[:60]

        if _linha_vazia(row):
            print(f"  {i:<6} {'VAZIA':<20} (vazia)")
            continue

        if _linha_total(row):
            print(f"  {i:<6} {'TOTAL/SUBTOTAL':<20} {resumo}")
            continue

        nome_prod = _linha_produto(row)
        if nome_prod:
            produto_atual = nome_prod
            print(f"  {i:<6} {'PRODUTO':<20} → {nome_prod}")
            continue

        print(f"  {i:<6} {f'DADO [{produto_atual[:12]}]':<20} {resumo}")
        rec = {col: _celula(val) for col, val in zip(nomes_col, row)}
        rec["__produto__"] = produto_atual
        linhas_dados.append(rec)

    # 5. Resultado limpo
    print(f"\n{SEP}")
    print(f"  RESULTADO LIMPO: {len(linhas_dados)} linhas de dados")
    print(SEP)

    if not linhas_dados:
        print("  Nenhuma linha de dado encontrada.")
        return

    df_limpo = pd.DataFrame(linhas_dados)

    # Remove colunas completamente vazias
    df_limpo = df_limpo.loc[:, (df_limpo != "").any(axis=0)]

    with pd.option_context("display.max_columns", None, "display.width", 140, "display.max_colwidth", 20):
        print(df_limpo.to_string(index=False))

    # 6. Salvar CSV limpo
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    df_limpo.to_csv(SAIDA, index=False, encoding="utf-8-sig")
    print(f"\n  Arquivo salvo em: {SAIDA}")

    # 7. Resumo final
    print(f"\n{SEP}")
    print("  RESUMO")
    print(SEP)
    produtos = df_limpo["__produto__"].unique() if "__produto__" in df_limpo.columns else []
    print(f"  Produtos/tanques encontrados ({len(produtos)}):")
    for p in produtos:
        n = len(df_limpo[df_limpo["__produto__"] == p])
        print(f"    • {p}  →  {n} linha(s)")
    print(f"\n  Colunas disponíveis após limpeza:")
    for c in df_limpo.columns:
        nao_vazios = (df_limpo[c] != "").sum()
        print(f"    • {c:<30} ({nao_vazios}/{len(df_limpo)} preenchidos)")
    print(f"\n{SEP}\n")


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        caminho = Path(sys.argv[1])
    else:
        caminho = ARQUIVO_PADRAO

    if not caminho.exists():
        print(f"\nArquivo não encontrado: {caminho}")
        print("Uso: python diagnosticar_lmc.py caminho/para/arquivo.xlsx")
        sys.exit(1)

    diagnosticar(caminho)
