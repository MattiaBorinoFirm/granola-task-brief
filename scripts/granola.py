#!/usr/bin/env python3
"""Note delle riunioni dalla API REST pubblica di Granola.

Sostituisce il connettore MCP, che si autentica solo con OAuth da browser e
quindi non è raggiungibile da un runner. Qui si usa una chiave `grn_`, che è
una credenziale non interattiva.

Solo libreria standard.

    granola.py check              verifica la chiave e conta le note in finestra
    granola.py dump --days 7      stampa le note della finestra, come testo
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://public-api.granola.ai/v1"
PAGINA = 30          # massimo consentito dall'API
PAGINE_MAX = 20      # argine: 600 note sono molte più di una settimana


class Problema(Exception):
    """Errore atteso, da riportare senza traceback."""


def chiave():
    valore = os.environ.get("GRANOLA_API_KEY", "").strip()
    if not valore:
        raise Problema(
            "Manca la variabile d'ambiente GRANOLA_API_KEY.\n"
            "In locale: esportala nella shell. Su GitHub: è il secret\n"
            "GRANOLA_API_KEY nelle impostazioni del repository."
        )
    if not valore.startswith("grn_"):
        raise Problema(
            "GRANOLA_API_KEY non sembra una chiave Granola: dovrebbe iniziare "
            "per 'grn_'."
        )
    return valore


def _chiama(percorso, parametri=None, tentativi=4):
    url = f"{BASE}{percorso}"
    if parametri:
        url += "?" + urllib.parse.urlencode(parametri)

    richiesta = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {chiave()}",
        "Accept": "application/json",
        "User-Agent": "granola-task-brief/1.0",
    })

    for tentativo in range(tentativi):
        try:
            with urllib.request.urlopen(richiesta, timeout=30) as risposta:
                return json.loads(risposta.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise Problema(
                    "Granola ha rifiutato la chiave (401). Va rigenerata "
                    "dall'app desktop e riscritta nel secret."
                )
            if exc.code == 403:
                raise Problema(
                    "Granola ha risposto 403: la chiave è valida ma non ha "
                    "accesso a queste note. Controlla che allo spazio sia stato "
                    "concesso l'accesso via API."
                )
            # 429 e 5xx sono transitori: si riprova con attesa crescente.
            if exc.code == 429 or exc.code >= 500:
                if tentativo == tentativi - 1:
                    raise Problema(f"Granola risponde {exc.code} e non si riprende.")
                time.sleep(2 ** tentativo)
                continue
            raise Problema(f"Granola ha risposto {exc.code} su {percorso}.")
        except urllib.error.URLError as exc:
            if tentativo == tentativi - 1:
                raise Problema(f"Non riesco a raggiungere Granola: {exc.reason}")
            time.sleep(2 ** tentativo)
    raise Problema("Granola non risponde.")


def _testo(valore):
    """Il summary arriva come stringa o come struttura: qui diventa testo."""
    if valore is None:
        return ""
    if isinstance(valore, str):
        return valore.strip()
    if isinstance(valore, list):
        return "\n".join(_testo(v) for v in valore).strip()
    if isinstance(valore, dict):
        for campo in ("text", "content", "markdown", "value"):
            if campo in valore:
                return _testo(valore[campo])
        return ""
    return str(valore).strip()


def _persone(valore):
    """Normalizza attendees/owner in una lista di 'Nome <email>'."""
    if not valore:
        return []
    if isinstance(valore, dict):
        valore = [valore]
    if isinstance(valore, str):
        return [valore]
    fuori = []
    for voce in valore:
        if isinstance(voce, str):
            fuori.append(voce)
        elif isinstance(voce, dict):
            nome = (voce.get("name") or "").strip()
            mail = (voce.get("email") or "").strip()
            if nome and mail:
                fuori.append(f"{nome} <{mail}>")
            elif nome or mail:
                fuori.append(nome or mail)
    return fuori


def elenco_note(giorni):
    """I metadati delle note create nella finestra, dalla più recente."""
    da = (datetime.now(timezone.utc) - timedelta(days=giorni)).date().isoformat()
    note, cursore = [], None
    for _ in range(PAGINE_MAX):
        parametri = {"created_after": da, "page_size": PAGINA}
        if cursore:
            parametri["cursor"] = cursore
        risposta = _chiama("/notes", parametri)
        note.extend(risposta.get("notes") or [])
        cursore = risposta.get("cursor")
        if not risposta.get("hasMore") or not cursore:
            break
    return note


def dettaglio(note_id):
    """Il contenuto di una nota. Niente trascrizione: pesa e non serve."""
    risposta = _chiama(f"/notes/{note_id}")
    return risposta.get("note") if isinstance(risposta.get("note"), dict) else risposta


def riunioni(giorni):
    """Le riunioni della finestra, normalizzate per il prompt."""
    fuori = []
    for meta in elenco_note(giorni):
        note_id = meta.get("id")
        if not note_id:
            continue
        try:
            pieno = dettaglio(note_id)
        except Problema:
            pieno = {}

        # I nomi veri, visti in risposta: la documentazione parla di "summary",
        # l'API restituisce summary_markdown e summary_text. Il markdown per
        # primo perché conserva titoli ed elenchi, che aiutano l'estrazione.
        sommario = ""
        for campo in ("summary_markdown", "summary_text",
                      "summary", "ai_summary", "notes", "content"):
            sommario = _testo(pieno.get(campo))
            if sommario:
                break
        if not sommario:
            # Una nota senza summary non porta task: saltarla tiene il payload
            # basso, cosa che con la finestra di contesto di Haiku conta.
            continue

        proprietario = _persone(pieno.get("owner") or meta.get("owner"))
        fuori.append({
            "id": note_id,
            "titolo": (pieno.get("title") or meta.get("title") or "senza titolo").strip(),
            "data": (meta.get("created_at") or pieno.get("created_at") or "")[:10],
            "proprietario": proprietario[0] if proprietario else "",
            "partecipanti": _persone(pieno.get("attendees")),
            "sommario": sommario,
        })

    fuori.sort(key=lambda r: r["data"], reverse=True)
    return fuori


def come_testo(elenco):
    """Le riunioni in testo, che è la forma in cui le legge il modello."""
    pezzi = []
    for r in elenco:
        testa = f"### {r['titolo']} — {r['data']}"
        if r["proprietario"]:
            testa += f"\nNota di: {r['proprietario']}"
        if r["partecipanti"]:
            testa += f"\nPartecipanti: {', '.join(r['partecipanti'])}"
        pezzi.append(f"{testa}\n\n{r['sommario']}")
    return "\n\n---\n\n".join(pezzi)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="comando", required=True)
    p_check = sub.add_parser("check", help="verifica la chiave e conta le note")
    p_check.add_argument("--days", type=int, default=10)
    p_dump = sub.add_parser("dump", help="stampa le note della finestra")
    p_dump.add_argument("--days", type=int, default=10)
    args = p.parse_args()

    try:
        if args.comando == "check":
            chiave()
            print("Chiave:        presente e nella forma attesa")

            # Prima la risposta grezza: se l'involucro non si chiama "notes",
            # la lista risulterebbe vuota senza che nessun errore lo segnali.
            da = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()
            cruda = _chiama("/notes", {"created_after": da, "page_size": PAGINA})
            print(f"Risposta /notes: chiavi {sorted(cruda.keys())}")
            for nome, valore in sorted(cruda.items()):
                if isinstance(valore, list):
                    print(f"  '{nome}': lista di {len(valore)} elementi")
                    if valore and isinstance(valore[0], dict):
                        print(f"      campi del primo: {sorted(valore[0].keys())}")
                else:
                    print(f"  '{nome}': {type(valore).__name__} = {str(valore)[:60]}")

            grezze = elenco_note(args.days)
            print(f"Note elencate: {len(grezze)} create negli ultimi {args.days} giorni")
            if not grezze:
                print("\nL'API risponde ma la lista è vuota. Di solito significa una"
                      " di queste:\n"
                      "  - la chiave è personale e non vede le note dello spazio;\n"
                      "  - allo spazio non è stato concesso l'accesso via API;\n"
                      "  - nella finestra non ci sono note già elaborate.")
                return

            # Quando la lista non è vuota ma le note utili sono zero, la colpa è
            # del campo in cui cerco il sommario: qui si vede subito quale c'è.
            for meta in grezze[:3]:
                pieno = dettaglio(meta["id"])
                campi = sorted(k for k, v in pieno.items() if v not in (None, "", [], {}))
                print(f"  {meta.get('created_at','?')[:10]}  "
                      f"{(meta.get('title') or 'senza titolo')[:45]}")
                print(f"      campi con contenuto: {', '.join(campi)}")

            utili = riunioni(args.days)
            print(f"Note con summary: {len(utili)} (le altre vengono scartate)")
            if utili:
                print("\nTutto a posto.")
            else:
                print("\nLe note ci sono ma nessuna espone un sommario nei campi"
                      " che leggo.\nGuarda l'elenco dei campi qui sopra e"
                      " aggiorna la lista in riunioni().")
        elif args.comando == "dump":
            print(come_testo(riunioni(args.days)))
    except Problema as exc:
        sys.stdout.flush()
        print(f"\nERRORE: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
