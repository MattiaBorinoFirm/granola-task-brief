#!/usr/bin/env python3
"""Il brief giornaliero, dall'inizio alla fine.

Era il corpo di un prompt eseguito da un agente su un Mac; qui è uno
script che gira ovunque ci sia Python e tre segreti. Il modello resta, ma fa
solo la parte che richiede giudizio: leggere linguaggio libero e decidere.
Documento, tabella, urgenze e ID li produce questo file.

    brief.py --dry-run        fa tutto tranne salvare e spedire
    brief.py --lista          stampa a schermo il messaggio integrale
    brief.py --solo-invio     rispedisce la lista com'è, senza modificarla
    brief.py                  esecuzione vera

Segreti attesi nell'ambiente:
    GEMINI_API_KEY      la chiave della Gemini API
    GRANOLA_API_KEY     la chiave `grn_` della Granola API
    MAIL_APP_PASSWORD   la password per app della casella bot
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import granola
import mailbox as posta
import statodoc
import tabella

QUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(QUI)
STATO = os.path.join(REPO, "stato", "task-document.md")
PROMPT = os.path.join(REPO, "prompts", "estrazione-task.md")

MODELLO = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Quanto far ragionare il modello prima di rispondere: minimal|low|medium|high,
# oppure "off" per non mandare affatto il parametro. I livelli accettati
# cambiano da modello a modello, e "off" è la via d'uscita se uno lo rifiuta.
LIVELLO_PENSIERO = os.environ.get("GEMINI_THINKING", "low").strip().lower()

# Lo schema è imposto all'API, non raccomandato al modello: la risposta o è
# conforme o non arriva. Elimina un'intera classe di guasti — JSON avvolto nei
# backtick, chiavi mancanti, virgole di troppo.
SCHEMA = {
    "type": "object",
    "properties": {
        "chiusure": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "frase": {"type": "string"}},
            "required": ["id"]}},
        "rinvii": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "scadenza": {"type": "string"},
                           "frase": {"type": "string"}},
            "required": ["id", "scadenza"]}},
        "nuovi_da_mail": {"type": "array", "items": {
            "type": "object",
            "properties": {"cliente": {"type": "string"},
                           "descrizione": {"type": "string"},
                           "scadenza": {"type": "string"}},
            "required": ["cliente", "descrizione", "scadenza"]}},
        "nuovi_da_riunioni": {"type": "array", "items": {
            "type": "object",
            "properties": {"cliente": {"type": "string"},
                           "descrizione": {"type": "string"},
                           "scadenza": {"type": "string"},
                           "origine": {"type": "string"}},
            "required": ["cliente", "descrizione", "scadenza", "origine"]}},
        "chiusure_dedotte": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "motivo": {"type": "string"}},
            "required": ["id"]}},
        "da_chiarire": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["chiusure", "rinvii", "nuovi_da_mail", "nuovi_da_riunioni",
                 "chiusure_dedotte", "da_chiarire"],
}

CHIAVI = ("chiusure", "rinvii", "nuovi_da_mail", "nuovi_da_riunioni",
          "chiusure_dedotte", "da_chiarire")

# Quanto indietro si leggono le riunioni, e quanto indietro si mostrano al
# modello le chiusure che servono a non riproporle.
GIORNI_RIUNIONI = 10
GIORNI_COMPLETATI = 30


class Problema(Exception):
    """Errore che ferma l'esecuzione, da riportare senza traceback."""


def guasto(elenco, messaggio):
    """Registra un guasto non fatale: va nella mail e anche nel log."""
    elenco.append(messaggio)
    print(f"GUASTO:        {messaggio}")


# --- il prompt -------------------------------------------------------------


def istruzioni(cfg=None):
    """Il system prompt: la parte dopo il separatore, che è quella operativa.

    Il prompt è un modello: chi è l'intestatario dei task, e in che contesto
    lavora, stanno in config.json e non incollati nel testo. Serve a installare il sistema modificando un solo
    file invece di andare a caccia del proprio nome dentro un prompt — ed è la
    ragione per cui questo repository può esistere anche in versione pubblica.

    L'omonimo è facoltativo: senza, la regola che dice di non confondere i due
    sparisce invece di restare lì a citare un nome che non esiste.
    """
    with open(PROMPT) as fh:
        testo = fh.read()
    testo = testo.split("\n---\n", 1)[1] if "\n---\n" in testo else testo

    cfg = cfg or {}
    for segnaposto, campo, ripiego in (
            ("{{PROPRIETARIO}}", "proprietario", "l'intestatario dei task"),
            ("{{NOME}}", "nome", "l'intestatario"),
            ("{{INDIRIZZO}}", "recipient", "indirizzo non configurato"),
            ("{{CONTESTO}}", "contesto", "lavora su più clienti e progetti")):
        testo = testo.replace(segnaposto, str(cfg.get(campo) or ripiego))

    omonimo = str(cfg.get("omonimo") or "").strip()
    if omonimo:
        testo = testo.replace("{{OMONIMO}}", omonimo)
    else:
        # Niente omonimo da distinguere: via la riga, invece di lasciarla
        # parlare di una persona che nelle note non comparirà mai. Per questo
        # nel prompt la regola sta tutta su una riga: spezzata in due, qui ne
        # resterebbe orfana la seconda metà.
        testo = "\n".join(r for r in testo.splitlines() if "{{OMONIMO}}" not in r)
    return testo.strip()


def _riassunto_task(t):
    stato = "completato" if t.completato else "aperto"
    riga = f"({t.id}) [{t.cliente}] {t.descrizione}"
    if not t.completato:
        riga += f" | scadenza: {t.scadenza or 'nessuna'}"
        if t.origine:
            riga += f" | origine: {t.origine}"
    else:
        riga += f" | chiuso il {t.chiuso_il}"
    return f"- {riga} [{stato}]"


def completati_da_mostrare(doc, oggi, finestra_riunioni):
    """Le chiusure che il modello deve ancora vedere per non riproporle.

    Un task può risorgere soltanto da una riunione ancora dentro la finestra:
    passata quella, la sua riunione il modello non la legge più e la chiusura
    non serve più a niente. Mostrarle tutte per sempre farebbe crescere il
    prompt senza limite — e una lista lunga peggiora proprio il confronto che
    dovrebbe aiutare.

    Il documento le conserva comunque tutte: qui si sceglie solo cosa spedire.
    Si filtra sulla data di chiusura, che non è mai anteriore a quella della
    riunione, quindi il taglio è più prudente di quanto sembri.
    """
    if GIORNI_COMPLETATI <= finestra_riunioni:
        raise Problema(
            f"Configurazione incoerente: i completati verrebbero nascosti dopo "
            f"{GIORNI_COMPLETATI} giorni\nmentre le riunioni si leggono indietro "
            f"di {finestra_riunioni}. Un task chiuso potrebbe essere riproposto "
            f"da una\nriunione che il modello vede ancora. "
            f"GIORNI_COMPLETATI deve superare la finestra."
        )

    confine = oggi - timedelta(days=GIORNI_COMPLETATI)
    recenti = []
    for t in doc.completati:
        try:
            chiuso = date.fromisoformat(t.chiuso_il)
        except (TypeError, ValueError):
            recenti.append(t)   # data illeggibile: nel dubbio si mostra
            continue
        if chiuso >= confine:
            recenti.append(t)
    return recenti


def componi_richiesta(doc, risposte, riunioni, oggi, finestra_riunioni=GIORNI_RIUNIONI):
    pezzi = [f"Oggi è {oggi.isoformat()}.", "", "## Stato attuale dei task", ""]
    pezzi.append("### Aperti")
    pezzi += [_riassunto_task(t) for t in doc.aperti] or ["(nessuno)"]
    recenti = completati_da_mostrare(doc, oggi, finestra_riunioni)
    pezzi += ["", f"### Chiusi negli ultimi {GIORNI_COMPLETATI} giorni "
                  "(non riproporre questi task)"]
    pezzi += [_riassunto_task(t) for t in recenti] or ["(nessuno)"]
    if doc.da_chiarire:
        pezzi += ["", "### Già segnalati come da chiarire"]
        pezzi += [f"- {v}" for v in doc.da_chiarire]

    pezzi += ["", "## Risposte via mail", ""]
    if risposte:
        for quando, corpo in risposte:
            etichetta = quando.strftime("%Y-%m-%d %H:%M") if quando else "data ignota"
            pezzi.append(f"### Risposta del {etichetta}\n\n{corpo}\n")
    else:
        pezzi.append("(nessuna risposta nuova da lavorare)")

    pezzi += ["", "## Note delle riunioni recenti", ""]
    pezzi.append(granola.come_testo(riunioni) if riunioni else "(nessuna nota)")

    return "\n".join(pezzi)


# --- la chiamata al modello ------------------------------------------------


def _estrai_json(testo):
    """Il primo oggetto JSON bilanciato nel testo."""
    inizio = testo.find("{")
    if inizio < 0:
        raise Problema("Il modello non ha restituito JSON.")
    livello, in_stringa, fuga = 0, False, False
    for posizione in range(inizio, len(testo)):
        carattere = testo[posizione]
        if in_stringa:
            if fuga:
                fuga = False
            elif carattere == "\\":
                fuga = True
            elif carattere == '"':
                in_stringa = False
            continue
        if carattere == '"':
            in_stringa = True
        elif carattere == "{":
            livello += 1
        elif carattere == "}":
            livello -= 1
            if livello == 0:
                return json.loads(testo[inizio:posizione + 1])
    raise Problema("Il JSON del modello è troncato.")


def interroga(richiesta, cfg=None):
    try:
        from google import genai
        from google.genai import errors as genai_errors
    except ImportError:
        raise Problema("Manca il pacchetto `google-genai`: pip install google-genai")

    if not os.environ.get("GEMINI_API_KEY", "").strip():
        raise Problema("Manca la variabile d'ambiente GEMINI_API_KEY.")

    cliente = genai.Client()
    if not hasattr(cliente, "interactions"):
        # google-genai < 2.x non ha l'API Interactions. Su Python 3.9 pip non
        # può installare di meglio: la 2.x richiede 3.10+. È il caso del Mac,
        # non del runner, che gira su 3.12.
        raise Problema(
            "Il pacchetto `google-genai` installato è troppo vecchio: manca "
            "l'API\n`interactions`. Serve google-genai >= 2.23, che richiede "
            "Python >= 3.10.\n"
            f"Qui gira Python {sys.version.split()[0]}."
        )
    parametri = {
        "model": MODELLO,
        "system_instruction": istruzioni(cfg),
        "input": richiesta,
    }
    if LIVELLO_PENSIERO not in ("", "off", "no"):
        parametri["generation_config"] = {"thinking_level": LIVELLO_PENSIERO}

    try:
        interazione = cliente.interactions.create(
            **parametri,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": SCHEMA,
            },
        )
    except genai_errors.APIError as exc:
        raise Problema(f"La Gemini API ha rifiutato la richiesta: {exc}")

    testo = interazione.output_text or ""
    if not testo.strip():
        raise Problema("Il modello ha risposto vuoto.")

    # Con lo schema imposto il testo è già JSON valido; l'estrazione resta come
    # rete, per il caso in cui arrivi avvolto in qualcosa.
    try:
        decisioni = json.loads(testo)
    except json.JSONDecodeError:
        decisioni = _estrai_json(testo)

    for chiave in CHIAVI:
        valore = decisioni.get(chiave)
        decisioni[chiave] = valore if isinstance(valore, list) else []

    uso = getattr(interazione, "usage", None)
    if uso is not None:
        print(f"Modello:       {MODELLO} "
              f"({uso.total_input_tokens} token in, "
              f"{uso.total_output_tokens} out, "
              f"{uso.total_thought_tokens} di pensiero)")
    else:
        print(f"Modello:       {MODELLO}")
    return decisioni


# --- applicazione delle decisioni ------------------------------------------


def _testo(valore):
    return " ".join(str(valore or "").split())


def _norma(valore):
    """Il testo ridotto a ciò che conta per un confronto: minuscole, niente
    punteggiatura. Il modello riformula e ripunteggia, la sostanza resta."""
    return re.sub(r"[^a-z0-9 ]", "", str(valore or "").lower()).strip()


def _somigliano(a, b, soglia=0.7):
    """Due ambiguità sono la stessa cosa detta in modo diverso?"""
    return difflib.SequenceMatcher(None, _norma(a), _norma(b)).ratio() >= soglia


def _citata(frase, testo, soglia=0.6):
    """La frase attribuita all'intestatario compare davvero in ciò che ha scritto?

    Non è il confronto fra stringhe intere di _somigliano: qui una frase breve
    va cercata dentro un testo lungo. Il prompt chiede le parole esatte, ma il
    modello accorcia e riformula, quindi pretendere la corrispondenza letterale
    respingerebbe anche le chiusure buone. Si misura invece quante parole della
    frase ricompaiono, nello stesso ordine, nelle risposte.

    Il confronto è per parole e non per caratteri di proposito. A caratteri,
    una sola parola infilata in mezzo — «a Rossi **stamattina** e» —
    spezza il blocco comune e dimezza il punteggio di una citazione per il
    resto fedele; e, all'opposto, due frasi senza alcun rapporto condividono
    comunque parecchie lettere sparse. Le parole non hanno nessuno dei due
    difetti.

    autojunk=False perché difflib, oltre i 200 elementi, scarta d'ufficio
    quelli molto frequenti: qui sarebbero gli articoli e le preposizioni, che
    in una citazione sono segnale, non rumore.
    """
    parole_frase = _norma(frase).split()
    parole_testo = _norma(testo).split()
    if not parole_frase or not parole_testo:
        return False
    confronto = difflib.SequenceMatcher(None, parole_frase, parole_testo,
                                        autojunk=False)
    comuni = sum(blocco.size for blocco in confronto.get_matching_blocks())
    return comuni >= soglia * len(parole_frase)


def _stesso_impegno(a, b, soglia=0.75):
    """Due descrizioni sono lo stesso impegno detto due volte?

    Non è il confronto di _somigliano, che rapporta le parti comuni alla somma
    delle due lunghezze: lì una riformulazione molto più prolissa dello stesso
    task scende sotto soglia proprio perché è più lunga. Qui si misura il
    contenimento — quanto della descrizione più corta ricompare nell'altra —
    che è la forma che prende un doppione quando il modello riscrive.

    Per parole e non per caratteri, per la stessa ragione di _citata: una
    parola infilata in mezzo spezzerebbe il blocco comune, e due frasi
    estranee condividono comunque molte lettere sparse.

    La soglia è misurata sui task veri di questo documento, non scelta a occhio.
    Fra impegni legittimamente distinti dello stesso cliente il contenimento
    non supera 0.57; fra copie dello stesso task vale 1.00, sia quando il testo
    è identico sia quando una è la riformulazione accorciata dell'altra. 0.75
    sta in mezzo con margine da entrambi i lati.
    """
    parole_a, parole_b = _norma(a).split(), _norma(b).split()
    if not parole_a or not parole_b:
        return False
    confronto = difflib.SequenceMatcher(None, parole_a, parole_b, autojunk=False)
    comuni = sum(blocco.size for blocco in confronto.get_matching_blocks())
    return comuni >= soglia * min(len(parole_a), len(parole_b))


def _scadenza(valore):
    valore = _testo(valore) or "nessuna"
    return valore if re.search(r"\d{4}-\d{2}-\d{2}", valore) else "nessuna"


def applica(doc, decisioni, oggi, risposte, posta_letta):
    """Porta le decisioni nel documento. Qui vivono le invarianti."""
    brief = {"aperti": [], "nuovi_riunioni": [], "nuovi_mail": [],
             "fatti": [], "dedotti": [], "da_chiarire": [], "doppioni": [],
             "guasti": []}

    aperti = {t.id: t for t in doc.aperti}
    chiusi = {t.id for t in doc.completati}

    def chiudi(ident, via, nota):
        task = aperti.get(ident)
        if task is None:
            # Un ID che non è aperto è un errore di abbinamento del modello,
            # non un task da chiudere: si segnala invece di eseguirlo.
            if ident not in chiusi:
                brief["da_chiarire"].append(
                    f"Il modello ha citato l'ID ({ident}), che non risulta fra i "
                    f"task aperti: {nota}"
                )
            return None
        task.completato = True
        task.chiuso_il = oggi.isoformat()
        task.chiuso_via = via
        doc.aperti.remove(task)
        doc.completati.append(task)
        del aperti[ident]
        return task

    # Una chiusura "via mail" richiede una mail. Il prompt lo impone già, ma
    # una regola scritta a parole vale quanto la buona volontà del modello: in
    # un giro osservato, con zero risposte in ingresso, ne ha dichiarate due
    # citando come prova le frasi delle note di riunione da cui quei task erano
    # nati. Qui la regola è codice, e il modello non può scavalcarla.
    #
    # Il danno che previene è il peggiore possibile qui: la chiusura finisce nel
    # canale che il resto del sistema tratta come affidabile, quello che a chi
    # corregge viene detto di non trattare come sospetto.
    testo_risposte = "\n".join(corpo for _, corpo in risposte)
    respinte = []

    for voce in decisioni["chiusure"]:
        ident = _testo(voce.get("id"))
        frase = _testo(voce.get("frase"))
        citazione = f"({ident}) «{frase or 'nessuna frase riportata'}»"

        if not posta_letta:
            respinte.append(f"{citazione} — la casella non è stata letta")
            continue
        if not risposte:
            respinte.append(f"{citazione} — non è arrivata nessuna risposta")
            continue
        if not _citata(frase, testo_risposte):
            respinte.append(f"{citazione} — questa frase non compare fra le tue")
            continue

        task = chiudi(ident, "via mail", frase or "nessuna frase riportata")
        if task:
            brief["fatti"].append(
                f"({task.id}) {tabella.titolo(task)} — sulla tua frase: «{frase}»"
                if frase else f"({task.id}) {tabella.titolo(task)}"
            )

    if respinte:
        # Nel log e nella mail, non solo nel documento: una chiusura respinta è
        # un malfunzionamento del giro, e va vista mentre accade.
        guasto(brief["guasti"],
               f"Respinte {len(respinte)} chiusure via mail non verificabili. "
               "I task restano aperti.")
        brief["da_chiarire"] += [f"Chiusura via mail respinta: {r}"
                                 for r in respinte]

    for voce in decisioni["chiusure_dedotte"]:
        ident = _testo(voce.get("id"))
        motivo = _testo(voce.get("motivo"))
        task = chiudi(ident, "dedotto dalle riunioni", motivo or "nessun motivo")
        if task:
            brief["dedotti"].append(
                f"({task.id}) {tabella.titolo(task)} — {motivo}. "
                "Se sbaglio, rispondi e lo riapro."
            )

    for voce in decisioni["rinvii"]:
        task = aperti.get(_testo(voce.get("id")))
        if task is None:
            continue
        nuova = _scadenza(voce.get("scadenza"))
        if nuova != "nessuna":
            task.scadenza = nuova

    def aggiungi(voce, origine_default):
        descrizione = _testo(voce.get("descrizione"))
        if not descrizione:
            return None
        cliente = _testo(voce.get("cliente")) or "interno"

        # Il prompt chiede al modello di deduplicare, e il modello a volte non
        # lo fa: due giri ravvicinati sugli stessi verbali hanno prodotto lo
        # stesso task tre volte, con descrizioni identiche parola per parola.
        # Delegare un'invariante al modello significa non averla.
        #
        # Il confronto include il cliente perché la descrizione da sola non
        # basta: «ricontattare il referente per sbloccare la fatturazione» è
        # un task diverso a seconda di chi sia il cliente, e nel documento ce
        # ne sono due che si somigliano allo 0.75 proprio per questo.
        #
        # Lo scarto non è silenzioso. Una soglia può sbagliare, e un task
        # buttato via senza dirlo sarebbe un danno peggiore del doppione che
        # evita: chi legge il brief deve poterlo vedere e riaprirlo.
        for gia in doc.aperti:
            if (_norma(gia.cliente) == _norma(cliente)
                    and _stesso_impegno(gia.descrizione, descrizione)):
                brief["doppioni"].append(
                    f"[{cliente}] {descrizione} — già presente come "
                    f"({gia.id}), non aggiunto")
                return None

        task = statodoc.Task(
            id=doc.nuovo_id(),
            cliente=cliente,
            descrizione=descrizione,
            scadenza=_scadenza(voce.get("scadenza")),
            origine=_testo(voce.get("origine")) or origine_default,
        )
        doc.aperti.append(task)
        return task

    origine_mail = f"mail {oggi.strftime('%d/%m')}"
    for voce in decisioni["nuovi_da_mail"]:
        task = aggiungi(voce, origine_mail)
        if task:
            task.origine = origine_mail
            brief["nuovi_mail"].append(task)

    for voce in decisioni["nuovi_da_riunioni"]:
        task = aggiungi(voce, "riunione non indicata")
        if task:
            brief["nuovi_riunioni"].append(task)

    # Le ambiguità si accumulano ma non all'infinito. Il confronto non può
    # essere fra stringhe esatte: il modello riformula la stessa ambiguità ogni
    # giorno con parole diverse, e l'elenco si riempirebbe di doppioni.
    nuove = [_testo(v) for v in decisioni["da_chiarire"] if _testo(v)]
    unione = []
    for voce in doc.da_chiarire + nuove + brief["da_chiarire"]:
        if not any(_somigliano(voce, gia) for gia in unione):
            unione.append(voce)
    doc.da_chiarire = unione[-20:]
    brief["da_chiarire"] = doc.da_chiarire

    # Un task appena estratto compare nella sua sezione, non anche fra gli aperti.
    appena_nati = {t.id for t in brief["nuovi_riunioni"] + brief["nuovi_mail"]}
    brief["aperti"] = [t for t in doc.aperti if t.id not in appena_nati]
    return brief


# --- esecuzione ------------------------------------------------------------


def risposte_nuove(cfg, doc, guasti):
    """Le risposte più recenti dell'ultimo aggiornamento, e se si è letto.

    Il secondo valore non è un dettaglio: una lista vuota perché la casella era
    vuota e una lista vuota perché IMAP ha rifiutato l'accesso sono due fatti
    opposti, e confonderli costa caro due volte — sul confine temporale che si
    può far avanzare, e sulle chiusure che si possono eseguire.
    """
    try:
        tutte = posta.raccogli_risposte(cfg, cfg.get("reply_lookback_days", 4))
    except posta.Problema as exc:
        guasto(guasti, f"Non ho potuto leggere le risposte via IMAP: {exc}")
        return [], False

    if not doc.aggiornato_il:
        return tutte, True
    try:
        confine = datetime.strptime(doc.aggiornato_il, "%Y-%m-%d %H:%M")
        confine = confine.replace(tzinfo=statodoc.FUSO)
    except ValueError:
        return tutte, True
    return [(q, c) for q, c in tutte if q is None or q > confine], True


def salva(nuovo_testo, guasti):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(nuovo_testo)
        percorso = fh.name
    try:
        esito = subprocess.run(
            [os.path.join(QUI, "salva-stato.sh"), percorso],
            capture_output=True, text=True, cwd=REPO,
        )
        print(esito.stdout.strip())
        if esito.returncode != 0:
            # salva-stato.sh si rifiuta di scrivere quando le invarianti non
            # tengono: non lo si aggira, si riporta e si va avanti col brief.
            guasto(guasti, f"Lo stato NON è stato salvato: {esito.stderr.strip()}")
            return False
        return True
    finally:
        os.unlink(percorso)


def mostra_lista():
    """Stampa a schermo il messaggio integrale. Non tocca niente, non spedisce.

    Quello che compare qui non assomiglia alla mail: **è** la mail, resa dalla
    stessa `tabella.componi_testo()` che ne produce il corpo. Due rese separate
    divergerebbero col tempo, e il senso di guardarla è poterla valutare
    sapendo che è quella che arriva in casella.

    Sopra il messaggio va però qualcosa che il messaggio non ha: le chiusure,
    e in particolare quelle **dedotte dalle riunioni**, che il modello produce
    in modo non riproducibile e che sono il candidato più probabile di
    correzione. Il corpo della mail le elenca solo nel giro in cui avvengono;
    qui servono sempre.
    """
    try:
        with open(STATO) as fh:
            doc = statodoc.leggi(fh.read())
    except FileNotFoundError:
        raise Problema(f"Manca il documento di stato {STATO}.")
    except statodoc.FormatoNonValido as exc:
        raise Problema(str(exc))

    oggi = statodoc.ora_locale().date()
    dedotti = [t for t in doc.completati if "dedotto" in (t.chiuso_via or "")]
    altri = [t for t in doc.completati if t not in dedotti]

    print(f"Stato al {doc.aggiornato_il or 'data assente'} — "
          f"{len(doc.aperti)} aperti, {len(doc.completati)} completati")

    if dedotti:
        print(f"\nCHIUSI PER DEDUZIONE — da rileggere ({len(dedotti)})")
        for t in dedotti:
            print(f"  ({t.id}) [{t.cliente}] {tabella.titolo(t)} — chiuso {t.chiuso_il}")

    if altri:
        print(f"\nALTRI CHIUSI ({len(altri)})")
        for t in altri:
            print(f"  ({t.id}) [{t.cliente}] {tabella.titolo(t)} — "
                  f"chiuso {t.chiuso_il}, {t.chiuso_via or 'motivo non indicato'}")

    print("\n" + "─" * 72)
    print(tabella.componi_testo({
        "aperti": doc.aperti,
        "nuovi_riunioni": [], "nuovi_mail": [], "fatti": [], "dedotti": [],
        "da_chiarire": doc.da_chiarire,
        "guasti": [],
    }, oggi))
    return 0


def solo_invio():
    """Rispedisce la lista corrente, senza interpretare e senza modificare.

    Non chiama il modello, non legge Granola, non legge la posta in arrivo: si
    limita a rendere il documento com'è e a spedirlo. Serve quando la lista la
    vuoi adesso — prima di una riunione, o dopo una correzione — e non c'è
    niente di nuovo da capire.

    Non costa niente in API e non può sbagliare un'interpretazione, perché non
    ne fa nessuna.
    """
    cfg = posta.leggi_config()
    oggi = statodoc.ora_locale().date()

    try:
        with open(STATO) as fh:
            doc = statodoc.leggi(fh.read())
    except FileNotFoundError:
        raise Problema(f"Manca il documento di stato {STATO}.")
    except statodoc.FormatoNonValido as exc:
        raise Problema(str(exc))

    print(f"Stato:         {len(doc.aperti)} aperti, {len(doc.completati)} completati")
    print(f"Aggiornato al: {doc.aggiornato_il or 'data assente'}")

    brief = {
        "aperti": doc.aperti,
        "nuovi_riunioni": [], "nuovi_mail": [], "fatti": [], "dedotti": [],
        "da_chiarire": doc.da_chiarire,
        "guasti": [],
    }

    with tempfile.TemporaryDirectory() as cartella:
        via_html = os.path.join(cartella, "brief.html")
        via_testo = os.path.join(cartella, "brief.txt")
        with open(via_html, "w") as fh:
            fh.write(tabella.componi_html(brief, oggi))
        with open(via_testo, "w") as fh:
            fh.write(tabella.componi_testo(brief, oggi))
        posta.send(cfg, html_file=via_html, text_file=via_testo)

    print("Il documento di stato non è stato toccato.")
    return 0


def esegui(prova, giorni):
    oggi = statodoc.ora_locale().date()
    guasti = []
    cfg = posta.leggi_config()

    try:
        with open(STATO) as fh:
            doc = statodoc.leggi(fh.read())
    except FileNotFoundError:
        raise Problema(f"Manca il documento di stato {STATO}.")
    except statodoc.FormatoNonValido as exc:
        raise Problema(
            f"{exc}\nNon riscrivo niente. Le versioni precedenti sono in git:\n"
            "  git log -- stato/task-document.md"
        )
    mostrati = len(completati_da_mostrare(doc, oggi, giorni))
    print(f"Stato:         {len(doc.aperti)} aperti, {len(doc.completati)} completati "
          f"({mostrati} mostrati al modello)")

    risposte, posta_letta = risposte_nuove(cfg, doc, guasti)
    print(f"Risposte:      {len(risposte)} da lavorare"
          f"{'' if posta_letta else ' (casella NON letta)'}")

    try:
        riunioni = granola.riunioni(giorni)
    except granola.Problema as exc:
        guasto(guasti, f"Non ho potuto leggere le note Granola: {exc}")
        riunioni = []
    print(f"Riunioni:      {len(riunioni)} negli ultimi {giorni} giorni")

    decisioni = interroga(componi_richiesta(doc, risposte, riunioni, oggi, giorni),
                          cfg)
    brief = applica(doc, decisioni, oggi, risposte, posta_letta)
    brief["guasti"] += guasti
    print(f"Decisioni:     {len(brief['fatti'])} chiusi da mail, "
          f"{len(brief['dedotti'])} chiusi per deduzione, "
          f"{len(brief['nuovi_riunioni'])} nuovi dalle riunioni, "
          f"{len(brief['nuovi_mail'])} dalle tue risposte")

    # Quali task sono stati toccati, sempre: un conteggio non basta a capire
    # cosa ha deciso il modello, e cercarlo nella mail dopo il fatto è tardi.
    for titolo_sezione, voci in (
        ("Chiusi da mail", brief["fatti"]),
        ("Chiusi per deduzione", brief["dedotti"]),
        ("Nuovi dalle riunioni", [f"[{t.cliente}] {t.descrizione}"
                                  for t in brief["nuovi_riunioni"]]),
        ("Nuovi dalle tue risposte", [f"[{t.cliente}] {t.descrizione}"
                                      for t in brief["nuovi_mail"]]),
        ("Da chiarire", brief["da_chiarire"]),
        ("Doppioni scartati", brief["doppioni"]),
    ):
        if voci:
            print(f"\n  {titolo_sezione}:")
            for voce in voci:
                print(f"    - {voce}")
    print()

    # 'Ultimo aggiornamento' è il confine che separa le risposte già lavorate
    # da quelle nuove. Farlo avanzare quando la casella non è stata letta rende
    # invisibili per sempre le risposte di quella finestra: il giro successivo
    # le considera già lavorate e non le guarda più. Se la lettura non c'è
    # stata si conserva il valore precedente, e il prossimo giro riparte da lì.
    quando = statodoc.ora_locale()
    if not posta_letta:
        precedente = statodoc.data_documento(doc)
        if precedente is None:
            guasto(brief["guasti"],
                   "Casella non letta e 'Ultimo aggiornamento' illeggibile: il "
                   "confine avanza lo stesso, le risposte di questa finestra "
                   "vanno rilette a mano.")
        else:
            quando = precedente
            guasto(brief["guasti"],
                   "Casella non letta: lascio 'Ultimo aggiornamento' a "
                   f"{precedente.strftime('%Y-%m-%d %H:%M')}, così le risposte "
                   "di questa finestra le rilegge il prossimo giro.")

    nuovo_stato = statodoc.scrivi(doc, quando)

    if prova:
        cartella = tempfile.mkdtemp(prefix="brief-")
        for nome, contenuto in (
            ("brief.html", tabella.componi_html(brief, oggi)),
            ("brief.txt", tabella.componi_testo(brief, oggi)),
            ("task-document.md", nuovo_stato),
        ):
            with open(os.path.join(cartella, nome), "w") as fh:
                fh.write(contenuto)
        print(f"\nProva: niente salvato, niente spedito. File in {cartella}")
        return 0

    # Prima lo stato, poi la mail: se l'invio fallisce il lavoro non è perso.
    # Il brief si compone dopo il salvataggio, così un rifiuto di salva-stato.sh
    # finisce nella mail invece di restare solo nel log del runner.
    salva(nuovo_stato, brief["guasti"])

    with tempfile.TemporaryDirectory() as cartella:
        via_html = os.path.join(cartella, "brief.html")
        via_testo = os.path.join(cartella, "brief.txt")
        with open(via_html, "w") as fh:
            fh.write(tabella.componi_html(brief, oggi))
        with open(via_testo, "w") as fh:
            fh.write(tabella.componi_testo(brief, oggi))
        posta.send(cfg, html_file=via_html, text_file=via_testo)
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true",
                   help="non salva lo stato e non manda la mail")
    p.add_argument("--lista", action="store_true",
                   help="stampa a schermo il messaggio integrale, senza toccare niente")
    p.add_argument("--solo-invio", action="store_true",
                   help="rispedisce la lista com'è: niente modello, niente modifiche")
    p.add_argument("--days", type=int, default=GIORNI_RIUNIONI,
                   help=f"finestra delle riunioni Granola (default {GIORNI_RIUNIONI})")
    args = p.parse_args()

    if sum([args.lista, args.solo_invio, args.dry_run]) > 1:
        p.error("--lista, --solo-invio e --dry-run sono alternativi")

    try:
        if args.lista:
            sys.exit(mostra_lista())
        sys.exit(solo_invio() if args.solo_invio else esegui(args.dry_run, args.days))
    except (Problema, posta.Problema, granola.Problema) as exc:
        sys.stdout.flush()
        print(f"\nERRORE: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
