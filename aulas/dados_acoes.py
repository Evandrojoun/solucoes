#!/usr/bin/env python3
"""
dados_acoes.py
================
Busca dados de acoes da B3 (cotacao, fundamentos e dividendos) usando a
API gratuita da brapi.dev. Funciona como substituto pratico do StatusInvest,
que nao tem API oficial.

COMO USAR
---------
1) Pegue um token gratuito em: https://brapi.dev  (crie conta -> Dashboard -> copie o token)
2) Guarde o token numa variavel de ambiente chamada BRAPI_TOKEN, por exemplo:
       Linux/Mac:  export BRAPI_TOKEN="seu_token_aqui"
       Windows:    setx BRAPI_TOKEN "seu_token_aqui"
   (ou passe com --token na linha de comando)

3) Rode pela linha de comando:
       python dados_acoes.py VALE3
       python dados_acoes.py VALE3 PETR4 ITUB4
       python dados_acoes.py VALE3 --json      (saida crua em JSON, boa pro agente)

4) Ou importe no seu proprio codigo / agente:
       from dados_acoes import buscar_acao
       dados = buscar_acao("VALE3")

O agente (Claude Code + AIOS) pode simplesmente rodar este script e ler o
resultado, ou chamar buscar_acao() diretamente.
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error

BASE_URL = "https://brapi.dev/api/quote/"


def buscar_acao(ticker, token=None):
    """Busca cotacao + fundamentos + dividendos de um ticker da B3.

    Retorna um dicionario com os dados. Lanca RuntimeError em caso de erro.
    """
    token = token or os.environ.get("BRAPI_TOKEN")
    if not token:
        raise RuntimeError(
            "Token da brapi nao encontrado. Defina a variavel de ambiente "
            "BRAPI_TOKEN ou passe token=... . Pegue um gratis em https://brapi.dev"
        )

    params = {
        "token": token,
        "range": "1mo",        # historico de precos do ultimo mes
        "interval": "1d",      # granularidade diaria
        "fundamental": "true",  # traz indicadores fundamentalistas
        "dividends": "true",    # traz historico de proventos/dividendos
    }
    url = BASE_URL + urllib.parse.quote(ticker) + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={"User-Agent": "dados_acoes/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Erro HTTP {e.code} ao buscar {ticker}: {corpo}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Falha de conexao ao buscar {ticker}: {e.reason}")

    resultados = payload.get("results") or []
    if not resultados:
        raise RuntimeError(f"Nenhum dado retornado para '{ticker}'. Ticker existe?")
    return resultados[0]


def resumir(dados):
    """Monta um resumo legivel dos principais numeros de uma acao."""
    linhas = []
    nome = dados.get("longName") or dados.get("shortName") or dados.get("symbol")
    linhas.append(f"=== {dados.get('symbol')} - {nome} ===")
    linhas.append(f"Preco atual:        R$ {dados.get('regularMarketPrice')}")
    linhas.append(f"Variacao do dia:    {dados.get('regularMarketChangePercent')} %")
    linhas.append(f"Maxima do dia:      R$ {dados.get('regularMarketDayHigh')}")
    linhas.append(f"Minima do dia:      R$ {dados.get('regularMarketDayLow')}")
    linhas.append(f"Volume:             {dados.get('regularMarketVolume')}")
    linhas.append(f"Market Cap:         {dados.get('marketCap')}")
    linhas.append(f"P/L:                {dados.get('priceEarnings')}")
    linhas.append(f"LPA (EPS):          {dados.get('earningsPerShare')}")

    # Dividendos (quando disponiveis no plano)
    div = (dados.get("dividendsData") or {}).get("cashDividends") or []
    if div:
        linhas.append(f"Dividendos recentes: {len(div)} registro(s) no historico")
        ultimo = div[0]
        linhas.append(
            f"  Ultimo provento:  R$ {ultimo.get('rate')} "
            f"({ultimo.get('label')}) pago em {ultimo.get('paymentDate')}"
        )
    else:
        linhas.append("Dividendos:         (sem dados no plano atual)")

    return "\n".join(linhas)


def main():
    parser = argparse.ArgumentParser(
        description="Busca dados de acoes da B3 via brapi.dev (alternativa ao StatusInvest)."
    )
    parser.add_argument("tickers", nargs="+", help="Um ou mais tickers, ex: VALE3 PETR4")
    parser.add_argument("--token", help="Token da brapi (senao usa BRAPI_TOKEN)")
    parser.add_argument("--json", action="store_true", help="Imprime o JSON cru (bom pro agente)")
    args = parser.parse_args()

    saida = {}
    houve_erro = False
    for ticker in args.tickers:
        ticker = ticker.upper()
        try:
            dados = buscar_acao(ticker, token=args.token)
        except RuntimeError as e:
            houve_erro = True
            if args.json:
                saida[ticker] = {"erro": str(e)}
            else:
                print(f"[ERRO] {e}\n", file=sys.stderr)
            continue

        if args.json:
            saida[ticker] = dados
        else:
            print(resumir(dados))
            print()

    if args.json:
        print(json.dumps(saida, ensure_ascii=False, indent=2))

    sys.exit(1 if houve_erro else 0)


if __name__ == "__main__":
    main()
