#!/usr/bin/env python3
"""
simulador_opcoes.py
===================
Simulador de estrategias de opcoes da B3 (calls e puts).

O QUE FAZ (funciona 100% de graca):
  - Compra de CALL, Venda de CALL
  - Compra de PUT,  Venda de PUT
  - Covered Call (comprar a acao + vender call)  -> renda tipo "dividendo"
  - Cash-Secured Put (vender put com caixa reservado)
  Para cada estrategia calcula: ponto de equilibrio (break-even),
  lucro maximo, prejuizo maximo, e uma tabela de resultado (payoff)
  para varios precos da acao no vencimento.

  Tambem tem uma calculadora Black-Scholes: dado o preco da acao,
  strike, prazo, taxa de juros e volatilidade, estima o "preco justo"
  do premio e as gregas (delta, gamma, theta, vega).

DADOS:
  - Preco atual da acao: puxado de graca da brapi.dev (precisa de BRAPI_TOKEN).
    Se nao houver token, voce informa o preco na mao com --preco.
  - Strike e premio da opcao: voce informa (--strike, --premio). Esses numeros
    voce pega no home broker, no opcoes.net.br ou no StatusInvest.

EXEMPLOS:
  python simulador_opcoes.py VALE3 --tipo call --op compra --strike 60 --premio 2.50
  python simulador_opcoes.py VALE3 --tipo put  --op venda  --strike 55 --premio 1.80 --preco 58
  python simulador_opcoes.py PETR4 --estrategia covered_call --strike 40 --premio 1.20
  python simulador_opcoes.py --bs --preco 58 --strike 60 --dias 30 --vol 0.35   (so Black-Scholes)
"""

import os
import sys
import math
import argparse
import urllib.request
import urllib.parse
import urllib.error

BRAPI_URL = "https://brapi.dev/api/quote/"


# ----------------------------------------------------------------------
# 1) Buscar preco atual da acao (brapi, gratis)
# ----------------------------------------------------------------------
def preco_atual(ticker, token=None):
    token = token or os.environ.get("BRAPI_TOKEN")
    if not token:
        return None
    url = BRAPI_URL + urllib.parse.quote(ticker) + "?" + urllib.parse.urlencode({"token": token})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "simulador_opcoes/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            import json
            dados = json.loads(resp.read().decode("utf-8"))
        res = (dados.get("results") or [{}])[0]
        return res.get("regularMarketPrice")
    except Exception:
        return None


# ----------------------------------------------------------------------
# 2) Payoff (resultado no vencimento) de uma unica perna
# ----------------------------------------------------------------------
def payoff_opcao(preco_venc, tipo, op, strike, premio, qtd=1):
    """Resultado de UMA opcao no vencimento, por acao (multiplicar por 100 = 1 contrato)."""
    tipo = tipo.lower()
    op = op.lower()
    if tipo == "call":
        valor_intrinseco = max(preco_venc - strike, 0.0)
    else:  # put
        valor_intrinseco = max(strike - preco_venc, 0.0)

    if op == "compra":   # paguei o premio
        return (valor_intrinseco - premio) * qtd
    else:                # venda: recebi o premio
        return (premio - valor_intrinseco) * qtd


def resumo_estrategia(nome, pernas, acao_qtd=0, preco_entrada_acao=0.0):
    """Calcula break-even, lucro/prejuizo max varrendo uma faixa de precos.

    pernas: lista de dicts {tipo, op, strike, premio, qtd}
    acao_qtd: quantidade de acoes compradas junto (para covered call)
    """
    strikes = [p["strike"] for p in pernas] or [preco_entrada_acao or 1]
    base = max(strikes + [preco_entrada_acao or 0])
    # varre de 0 ate ~2x o maior strike
    passo = max(base * 0.01, 0.01)
    precos = [i * passo for i in range(0, int(base * 2 / passo) + 2)]

    def total(preco_venc):
        t = 0.0
        for p in pernas:
            t += payoff_opcao(preco_venc, p["tipo"], p["op"], p["strike"], p["premio"], p.get("qtd", 1))
        if acao_qtd:
            t += (preco_venc - preco_entrada_acao) * acao_qtd
        return t

    resultados = [(pv, total(pv)) for pv in precos]
    lucros = [r for _, r in resultados]
    lucro_max = max(lucros)
    prej_max = min(lucros)

    # break-even: onde o resultado cruza zero
    breakevens = []
    for i in range(1, len(resultados)):
        p0, r0 = resultados[i - 1]
        p1, r1 = resultados[i]
        if (r0 <= 0 <= r1) or (r0 >= 0 >= r1):
            if r1 != r0:
                be = p0 + (0 - r0) * (p1 - p0) / (r1 - r0)
                breakevens.append(round(be, 2))

    return {
        "nome": nome,
        "lucro_max": lucro_max,
        "prejuizo_max": prej_max,
        "break_even": sorted(set(breakevens)),
        "total_fn": total,
    }


# ----------------------------------------------------------------------
# 3) Black-Scholes: preco justo do premio + gregas
# ----------------------------------------------------------------------
def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes(preco, strike, dias, vol, taxa=0.1075, tipo="call"):
    """Preco teorico e gregas. taxa = juros ao ano (Selic ~10.75% default)."""
    T = dias / 365.0
    if T <= 0 or vol <= 0:
        return None
    d1 = (math.log(preco / strike) + (taxa + 0.5 * vol ** 2) * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    if tipo == "call":
        preco_opcao = preco * _norm_cdf(d1) - strike * math.exp(-taxa * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (-(preco * _norm_pdf(d1) * vol) / (2 * math.sqrt(T))
                 - taxa * strike * math.exp(-taxa * T) * _norm_cdf(d2))
    else:
        preco_opcao = strike * math.exp(-taxa * T) * _norm_cdf(-d2) - preco * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1
        theta = (-(preco * _norm_pdf(d1) * vol) / (2 * math.sqrt(T))
                 + taxa * strike * math.exp(-taxa * T) * _norm_cdf(-d2))
    gamma = _norm_pdf(d1) / (preco * vol * math.sqrt(T))
    vega = preco * _norm_pdf(d1) * math.sqrt(T)
    return {
        "preco_justo": preco_opcao,
        "delta": delta,
        "gamma": gamma,
        "theta_dia": theta / 365.0,
        "vega_1pct": vega / 100.0,
    }


# ----------------------------------------------------------------------
# 4) Impressao
# ----------------------------------------------------------------------
def brl(v):
    if v is None:
        return "-"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_resultado(res, preco_ref):
    print(f"\n=== {res['nome']} ===")
    lm = res["lucro_max"]
    pm = res["prejuizo_max"]
    print(f"Lucro maximo:     {brl(lm) if lm < 1e8 else 'ilimitado'} (por acao)")
    print(f"Prejuizo maximo:  {brl(pm) if pm > -1e8 else 'muito alto / ilimitado'} (por acao)")
    be = res["break_even"]
    print(f"Ponto(s) de equilibrio: {', '.join(brl(b) for b in be) if be else 'nao cruza zero na faixa'}")
    print("\nResultado no vencimento (por acao) para alguns precos:")
    fn = res["total_fn"]
    faixa = [preco_ref * f for f in (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15)]
    print(f"  {'Preco acao':>12} | {'Resultado':>14}")
    print("  " + "-" * 30)
    for pv in faixa:
        print(f"  {brl(pv):>12} | {brl(fn(pv)):>14}")
    print("\n  (multiplique por 100 para 1 contrato; opcoes da B3 = lotes de 100)")


# ----------------------------------------------------------------------
# 5) CLI
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Simulador de estrategias de opcoes da B3.")
    ap.add_argument("ticker", nargs="?", help="Ticker da acao, ex: VALE3")
    ap.add_argument("--preco", type=float, help="Preco atual da acao (senao busca na brapi)")
    ap.add_argument("--token", help="Token da brapi (senao usa BRAPI_TOKEN)")

    ap.add_argument("--tipo", choices=["call", "put"], help="Tipo da opcao")
    ap.add_argument("--op", choices=["compra", "venda"], help="Comprar ou vender a opcao")
    ap.add_argument("--strike", type=float, help="Preco de exercicio (strike)")
    ap.add_argument("--premio", type=float, help="Premio da opcao (por acao)")

    ap.add_argument("--estrategia", choices=["covered_call", "cash_secured_put"],
                    help="Estrategias de renda (dividendos ativos)")

    ap.add_argument("--bs", action="store_true", help="So calcular Black-Scholes")
    ap.add_argument("--dias", type=int, default=30, help="Dias ate o vencimento (Black-Scholes)")
    ap.add_argument("--vol", type=float, default=0.35, help="Volatilidade anual, ex 0.35 = 35%%")
    ap.add_argument("--taxa", type=float, default=0.1075, help="Taxa de juros anual (Selic)")
    args = ap.parse_args()

    # Preco da acao
    preco = args.preco
    if preco is None and args.ticker:
        preco = preco_atual(args.ticker, token=args.token)
    if preco is None and not args.bs:
        preco = args.strike or 100.0
        print(f"[aviso] Sem preco da acao (sem token/--preco). Usando referencia R$ {preco:.2f} so para a tabela.")

    # ---- Modo Black-Scholes puro ----
    if args.bs:
        if not (args.preco and args.strike):
            print("Para --bs informe --preco e --strike.", file=sys.stderr)
            sys.exit(1)
        for tp in ("call", "put"):
            bs = black_scholes(args.preco, args.strike, args.dias, args.vol, args.taxa, tp)
            print(f"\n[Black-Scholes {tp.upper()}]  acao={brl(args.preco)} strike={brl(args.strike)} "
                  f"dias={args.dias} vol={args.vol*100:.0f}%")
            print(f"  Premio justo estimado: {brl(bs['preco_justo'])}")
            print(f"  Delta: {bs['delta']:+.3f}   Gamma: {bs['gamma']:.4f}   "
                  f"Theta/dia: {brl(bs['theta_dia'])}   Vega(1%): {brl(bs['vega_1pct'])}")
        return

    # ---- Estrategias de renda ----
    if args.estrategia == "covered_call":
        if not (args.strike and args.premio):
            print("Covered call precisa de --strike e --premio.", file=sys.stderr); sys.exit(1)
        pernas = [{"tipo": "call", "op": "venda", "strike": args.strike, "premio": args.premio}]
        res = resumo_estrategia("Covered Call (acao comprada + call vendida)",
                                pernas, acao_qtd=1, preco_entrada_acao=preco)
        imprimir_resultado(res, preco)
        print(f"\n  Renda imediata do premio: {brl(args.premio)} por acao "
              f"({(args.premio/preco*100):.2f}% sobre o preco atual).")
        return

    if args.estrategia == "cash_secured_put":
        if not (args.strike and args.premio):
            print("Cash-secured put precisa de --strike e --premio.", file=sys.stderr); sys.exit(1)
        pernas = [{"tipo": "put", "op": "venda", "strike": args.strike, "premio": args.premio}]
        res = resumo_estrategia("Cash-Secured Put (put vendida com caixa reservado)", pernas)
        imprimir_resultado(res, preco)
        print(f"\n  Renda imediata do premio: {brl(args.premio)} por acao. "
              f"Se cair abaixo de {brl(args.strike)}, voce compra a acao por {brl(args.strike)}.")
        return

    # ---- Perna unica (call/put compra/venda) ----
    if not (args.tipo and args.op and args.strike is not None and args.premio is not None):
        print("Informe --tipo, --op, --strike e --premio "
              "(ou use --estrategia / --bs).", file=sys.stderr)
        sys.exit(1)
    pernas = [{"tipo": args.tipo, "op": args.op, "strike": args.strike, "premio": args.premio}]
    nome = f"{args.op.capitalize()} de {args.tipo.upper()} strike {brl(args.strike)}"
    res = resumo_estrategia(nome, pernas)
    imprimir_resultado(res, preco)


if __name__ == "__main__":
    main()
