#!/bin/bash
# Mette il nuovo documento di stato nel repo e lo committa, da solo.
#
#   salva-stato.sh [--correzione] <file-con-il-nuovo-contenuto>
#
# --correzione dichiara che a scrivere è una persona, non l'esecuzione
# automatica. Fa due cose: marca il commit come correzione manuale, così nello
# storico le due cose non si confondono, e accetta che i completati
# diminuiscano — cosa necessaria per riaprire un task chiuso per sbaglio, e
# che dall'automazione è invece sempre il sintomo di un'estrazione andata male.
#
# Committa esclusivamente stato/task-document.md: qualunque altra modifica in
# corso nel repo resta dov'è, non staged e non committata. Poi pubblica su
# GitHub, che è la copia buona dello stato: il clone locale è una copia di
# lavoro e non deve accumulare commit che non escono.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$REPO/stato/task-document.md"

CORREZIONE=0
if [ "${1:-}" = "--correzione" ]; then
    CORREZIONE=1
    shift
fi

if [ $# -ne 1 ]; then
    echo "uso: salva-stato.sh [--correzione] <file-con-il-nuovo-contenuto>" >&2
    exit 2
fi

SORGENTE="$1"

if [ ! -s "$SORGENTE" ]; then
    echo "ERRORE: '$SORGENTE' non esiste o è vuoto. Non sovrascrivo lo stato." >&2
    exit 1
fi

# Il documento senza task aperti è quasi sempre il sintomo di un'estrazione
# andata storta, non di una giornata senza impegni. Meglio fermarsi.
if ! grep -q '^Prossimo ID libero:' "$SORGENTE"; then
    echo "ERRORE: in '$SORGENTE' manca la riga 'Prossimo ID libero:'." >&2
    echo "Non sembra un documento di stato valido: non sovrascrivo." >&2
    exit 1
fi

APERTI_NUOVI=$(grep -c '^- \[ \]' "$SORGENTE" || true)
COMPLETATI_NUOVI=$(grep -c '^- \[x\]' "$SORGENTE" || true)

if [ -f "$DEST" ]; then
    COMPLETATI_VECCHI=$(grep -c '^- \[x\]' "$DEST" || true)
    if [ "$COMPLETATI_NUOVI" -lt "$COMPLETATI_VECCHI" ]; then
        if [ "$CORREZIONE" -eq 0 ]; then
            echo "ERRORE: i completati scenderebbero da $COMPLETATI_VECCHI a $COMPLETATI_NUOVI." >&2
            echo "La sezione completati non si pota mai: è l'indice di deduplicazione." >&2
            echo "Non sovrascrivo. Il documento precedente resta intatto." >&2
            echo "" >&2
            echo "Se è una correzione voluta — per esempio riaprire un task chiuso" >&2
            echo "per sbaglio — rilancia con --correzione." >&2
            exit 1
        fi
        echo "ATTENZIONE: i completati scendono da $COMPLETATI_VECCHI a $COMPLETATI_NUOVI."
        echo "Consentito perché richiesto come correzione manuale."
    fi
fi

mkdir -p "$(dirname "$DEST")"
cp "$SORGENTE" "$DEST"

cd "$REPO"
if git diff --quiet -- stato/task-document.md 2>/dev/null && \
   ! git ls-files --others --exclude-standard --error-unmatch stato/task-document.md >/dev/null 2>&1; then
    echo "Stato invariato rispetto all'ultimo commit: niente da committare."
else
    git add -- stato/task-document.md
    if [ "$CORREZIONE" -eq 1 ]; then
        MESSAGGIO="Correzione manuale dello stato: $APERTI_NUOVI aperti, $COMPLETATI_NUOVI completati"
    else
        MESSAGGIO="Stato task $(date +%Y-%m-%d): $APERTI_NUOVI aperti, $COMPLETATI_NUOVI completati"
    fi
    git commit -q -m "$MESSAGGIO" -- stato/task-document.md

    echo "Stato salvato e committato: $APERTI_NUOVI aperti, $COMPLETATI_NUOVI completati."
    git --no-pager log --oneline -1
fi

# Il push si tenta comunque, anche quando non c'è un commit nuovo: così un push
# fallito ieri si recupera oggi invece di lasciare il locale alla deriva.
RAMO="$(git rev-parse --abbrev-ref HEAD)"
if git push -q origin "$RAMO"; then
    echo "Stato pubblicato su GitHub ($RAMO)."
else
    # Non è un errore fatale: il commit è già al sicuro e il brief deve partire
    # lo stesso. Va però detto forte, altrimenti la deriva passa inosservata.
    echo "ATTENZIONE: push su origin/$RAMO non riuscito, motivo qui sopra." >&2
    echo "Il commit è al sicuro in locale, ma GitHub non è allineato." >&2
fi
