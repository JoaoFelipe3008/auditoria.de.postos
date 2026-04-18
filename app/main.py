"""
main.py — Ponto de entrada do Sistema de Auditoria de Postos de Combustíveis.

Modos de execução:
  1. Auditoria de pasta única:
       python -m app.main
       python -m app.main --pasta data/entradas --posto "Posto Central"

  2. Auditoria de múltiplos postos:
       python -m app.main --multi --pasta data/postos

  3. Com configurações customizadas:
       python -m app.main --lmc-tolerancia-alto 200 --caixa-tolerancia-alto 1000

Saída:
  - Relatório TXT impresso no terminal
  - Arquivos TXT, CSV e JSON salvos em data/relatorios/
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

# Força saída UTF-8 no terminal Windows (evita UnicodeEncodeError com cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.models.schemas import ConfiguracaoTolerancia
from app.services.auditoria_service import AuditoriaMultiPostoService, AuditoriaService
from app.services.relatorio_service import RelatorioService

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------

def configurar_logging(verbose: bool = False) -> None:
    nivel = logging.DEBUG if verbose else logging.INFO
    formato = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    logging.basicConfig(
        level=nivel,
        format=formato,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Silenciar logs muito verbosos de bibliotecas externas
    logging.getLogger("openpyxl").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Parser de argumentos CLI
# ---------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auditoria-postos",
        description="Sistema de Auditoria Operacional para Postos de Combustíveis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python -m app.main
  python -m app.main --pasta data/entradas --posto "Posto Norte"
  python -m app.main --multi --pasta data/postos
  python -m app.main --verbose --lmc-tolerancia-alto 150
        """,
    )

    # Localização dos dados
    parser.add_argument(
        "--pasta",
        type=Path,
        default=Path("data/entradas"),
        help="Pasta com os arquivos de entrada (padrão: data/entradas)",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("data/relatorios"),
        help="Pasta onde os relatórios serão salvos (padrão: data/relatorios)",
    )
    parser.add_argument(
        "--posto",
        type=str,
        default="Posto Exemplo",
        help="Nome do posto auditado (padrão: 'Posto Exemplo')",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Auditar múltiplos postos em subpastas da --pasta informada",
    )

    # Tolerâncias customizáveis
    grp = parser.add_argument_group("Tolerâncias")
    grp.add_argument("--lmc-tolerancia-baixo",  type=float, default=30.0)
    grp.add_argument("--lmc-tolerancia-medio",  type=float, default=100.0)
    grp.add_argument("--lmc-tolerancia-alto",   type=float, default=300.0)
    grp.add_argument("--caixa-tolerancia-baixo", type=float, default=10.0)
    grp.add_argument("--caixa-tolerancia-medio", type=float, default=100.0)
    grp.add_argument("--caixa-tolerancia-alto",  type=float, default=500.0)
    grp.add_argument("--afericao-tolerancia-baixo", type=float, default=0.3)
    grp.add_argument("--afericao-tolerancia-medio", type=float, default=0.5)
    grp.add_argument("--afericao-tolerancia-alto",  type=float, default=1.0)
    grp.add_argument("--limite-sangria", type=float, default=2000.0,
                     help="Valor em R$ para sinalizar sangria excessiva")

    # Debug
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Exibir logs detalhados de debug")

    return parser


# ---------------------------------------------------------------------------
# Fluxo principal — posto único
# ---------------------------------------------------------------------------

def executar_auditoria_simples(args: argparse.Namespace, cfg: ConfiguracaoTolerancia) -> int:
    """Executa auditoria em uma única pasta e retorna código de saída."""
    logger = logging.getLogger(__name__)

    pasta = args.pasta
    if not pasta.exists():
        logger.error("Pasta de entrada não encontrada: %s", pasta)
        print(f"\n[ERRO] Pasta '{pasta}' não encontrada.")
        print("       Gere os dados de exemplo com: python generate_examples.py")
        return 1

    service = AuditoriaService(
        posto=args.posto,
        cfg=cfg,
        limite_sangria=args.limite_sangria,
    )
    relatorio_svc = RelatorioService(pasta_saida=args.saida)

    resultado = service.auditar_pasta(pasta)

    # Exibir no terminal
    relatorio_svc.imprimir_no_terminal(resultado)

    # Salvar em disco
    arquivos = relatorio_svc.salvar_todos(resultado)

    print("\n" + "=" * 80)
    print("  ARQUIVOS GERADOS:")
    for fmt, caminho in arquivos.items():
        print(f"    [{fmt.upper()}] {caminho}")
    print("=" * 80)

    # Retornar código de saída não-zero se houver críticos
    if resultado.divergencias_criticas > 0:
        return 2   # Divergências críticas encontradas
    if resultado.divergencias_alto_risco > 0:
        return 1   # Divergências de alto risco encontradas
    return 0


# ---------------------------------------------------------------------------
# Fluxo principal — múltiplos postos
# ---------------------------------------------------------------------------

def executar_auditoria_multi(args: argparse.Namespace, cfg: ConfiguracaoTolerancia) -> int:
    logger = logging.getLogger(__name__)

    pasta = args.pasta
    if not pasta.exists():
        logger.error("Pasta raiz não encontrada: %s", pasta)
        return 1

    multi_svc = AuditoriaMultiPostoService(cfg=cfg, limite_sangria=args.limite_sangria)
    relatorio_svc = RelatorioService(pasta_saida=args.saida)

    resultados = multi_svc.auditar_todos(pasta)

    if not resultados:
        print("[AVISO] Nenhum posto auditado. Verifique se a pasta possui subpastas com dados.")
        return 1

    # Exibir cada relatório individualmente
    for resultado in resultados:
        relatorio_svc.imprimir_no_terminal(resultado)
        relatorio_svc.salvar_todos(resultado)

    # Resumo consolidado
    print(relatorio_svc.resumo_multi_posto(resultados))

    criticos_total = sum(r.divergencias_criticas for r in resultados)
    return 2 if criticos_total > 0 else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = construir_parser()
    args = parser.parse_args()

    configurar_logging(verbose=args.verbose)

    cfg = ConfiguracaoTolerancia(
        lmc_tolerancia_baixo=args.lmc_tolerancia_baixo,
        lmc_tolerancia_medio=args.lmc_tolerancia_medio,
        lmc_tolerancia_alto=args.lmc_tolerancia_alto,
        caixa_tolerancia_baixo=args.caixa_tolerancia_baixo,
        caixa_tolerancia_medio=args.caixa_tolerancia_medio,
        caixa_tolerancia_alto=args.caixa_tolerancia_alto,
        afericao_tolerancia_baixo=args.afericao_tolerancia_baixo,
        afericao_tolerancia_medio=args.afericao_tolerancia_medio,
        afericao_tolerancia_alto=args.afericao_tolerancia_alto,
    )

    if args.multi:
        return executar_auditoria_multi(args, cfg)
    else:
        return executar_auditoria_simples(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
