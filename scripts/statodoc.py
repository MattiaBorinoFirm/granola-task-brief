#!/usr/bin/env python3
"""Il documento di stato: come si legge e come si riscrive.

Finché il brief lo produceva un modello, il formato viveva come descrizione a
parole dentro il prompt e nessuno lo verificava. Qui diventa codice: una sola
definizione, usata sia per rileggere il documento di ieri sia per scrivere
quello di oggi.

Formato di una riga task (le righe possono andare a capo, rientrate):

    - [ ] (001) [Cliente] descrizione — scadenza 2026-09-14 — origine: riunione X, 2026-09-11
    - [x] (008) [Cliente] descrizione — chiuso 2026-09-12 — via mail
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

# Il documento è sempre datato ora di Roma, ovunque giri. Sul Mac coincideva
# con l'ora locale e non si notava; su un runner l'ora locale è UTC, e senza
# questo il campo 'Ultimo aggiornamento' sarebbe indietro di un'ora o due.
# Non è cosmesi: è il campo su cui si decide quali risposte sono già lavorate.
FUSO = ZoneInfo("Europe/Rome")


def ora_locale():
    return datetime.now(FUSO)

INTESTAZIONE = "# Task Granola"
TRATTINO = "—"

# Larghezza a cui si mandano a capo le righe lunghe, per tenere il diff di git
# leggibile: una modifica di poche parole non deve riscrivere tutto il paragrafo.
COLONNE = 82

_RIGA = re.compile(r"^- \[( |x)\] \((\d{3})\)\s*(.*)$")
_CLIENTE = re.compile(r"^\[([^\]]+)\]\s*(.*)$", re.S)
_DATA = re.compile(r"(\d{4}-\d{2}-\d{2})")
_PROSSIMO_ID = re.compile(r"^Prossimo ID libero:\s*(\d+)\s*$", re.M)
_AGGIORNAMENTO = re.compile(r"^Ultimo aggiornamento:\s*(.+?)\s*$", re.M)


class FormatoNonValido(Exception):
    """Il documento non è nella forma attesa: meglio fermarsi che indovinare."""


@dataclass
class Task:
    id: str
    cliente: str
    descrizione: str
    scadenza: str = "nessuna"      # testo come compare nel documento
    origine: str = ""
    completato: bool = False
    chiuso_il: str = ""
    chiuso_via: str = ""

    @property
    def scadenza_data(self):
        """La scadenza come data vera, o None se non ce n'è una."""
        trovata = _DATA.search(self.scadenza or "")
        if not trovata:
            return None
        try:
            return date.fromisoformat(trovata.group(1))
        except ValueError:
            return None

    def riga(self):
        spunta = "x" if self.completato else " "
        testo = f"[{self.cliente}] {self.descrizione}"
        if self.completato:
            testo += f" {TRATTINO} chiuso {self.chiuso_il}"
            if self.chiuso_via:
                testo += f" {TRATTINO} {self.chiuso_via}"
        else:
            scadenza = self.scadenza or "nessuna"
            # "scadenza: nessuna" ma "scadenza 2026-09-14": la differenza è nel
            # documento originale e si mantiene, per non sporcare il diff.
            if _DATA.search(scadenza):
                testo += f" {TRATTINO} scadenza {scadenza}"
            else:
                testo += f" {TRATTINO} scadenza: {scadenza}"
            if self.origine:
                testo += f" {TRATTINO} origine: {self.origine}"
        return _avvolgi(f"- [{spunta}] ({self.id}) {testo}")


@dataclass
class Documento:
    prossimo_id: int = 1
    aggiornato_il: str = ""
    aperti: list = field(default_factory=list)
    completati: list = field(default_factory=list)
    da_chiarire: list = field(default_factory=list)

    def nuovo_id(self):
        """Assegna il prossimo ID e avanza il contatore. Mai riusati."""
        assegnato = f"{self.prossimo_id:03d}"
        self.prossimo_id += 1
        return assegnato

    def per_id(self, ident):
        for t in self.aperti + self.completati:
            if t.id == ident:
                return t
        return None


def _avvolgi(riga, rientro="      "):
    """Manda a capo una riga lunga, rientrando le continuazioni.

    Sei spazi per i task, che allineano la continuazione sotto il testo dopo
    `- [ ] (001) `; due per le voci di "Da chiarire", che sono elenchi normali.
    """
    parole = riga.split()
    if not parole:
        return riga
    righe, corrente = [], parole[0]
    for parola in parole[1:]:
        if len(corrente) + 1 + len(parola) > COLONNE:
            righe.append(corrente)
            corrente = rientro + parola
        else:
            corrente += " " + parola
    righe.append(corrente)
    return "\n".join(righe)


def _unisci_continuazioni(righe):
    """Ricompone le righe mandate a capo in una riga logica per task."""
    logiche = []
    for riga in righe:
        if not riga.strip():
            continue
        if riga.startswith("- ") or not logiche:
            logiche.append(riga.rstrip())
        else:
            logiche[-1] += " " + riga.strip()
    return logiche


def _sezioni(testo):
    """Spezza il documento nelle sue sezioni ## TITOLO."""
    trovate, corrente = {}, None
    for riga in testo.splitlines():
        if riga.startswith("## "):
            corrente = riga[3:].strip().upper()
            trovate[corrente] = []
        elif corrente is not None:
            trovate[corrente].append(riga)
    return trovate


def _scomponi_coda(resto, completato):
    """Separa descrizione, scadenza/chiusura e origine da destra verso sinistra.

    Da destra perché il separatore è lo stesso trattino che può comparire dentro
    la descrizione: gli ultimi due campi hanno un'etichetta che li identifica,
    la descrizione è tutto quello che avanza.
    """
    scadenza, origine, chiuso_il, chiuso_via = "nessuna", "", "", ""

    if TRATTINO + " origine:" in resto:
        resto, origine = resto.rsplit(TRATTINO + " origine:", 1)
        origine = origine.strip()

    for etichetta in (TRATTINO + " scadenza:", TRATTINO + " scadenza"):
        if etichetta in resto:
            resto, scadenza = resto.rsplit(etichetta, 1)
            scadenza = scadenza.strip() or "nessuna"
            break

    if completato and TRATTINO + " chiuso" in resto:
        resto, chiusura = resto.rsplit(TRATTINO + " chiuso", 1)
        chiusura = chiusura.strip()
        if TRATTINO in chiusura:
            chiuso_il, chiuso_via = [p.strip() for p in chiusura.split(TRATTINO, 1)]
        else:
            chiuso_il = chiusura

    return resto.strip(), scadenza, origine, chiuso_il, chiuso_via


def _leggi_task(riga):
    trovata = _RIGA.match(riga)
    if not trovata:
        return None
    spunta, ident, resto = trovata.groups()
    completato = spunta == "x"

    resto, scadenza, origine, chiuso_il, chiuso_via = _scomponi_coda(resto, completato)

    cliente = "interno"
    cliente_trovato = _CLIENTE.match(resto)
    if cliente_trovato:
        cliente, resto = cliente_trovato.groups()

    return Task(
        id=ident,
        cliente=cliente.strip(),
        descrizione=" ".join(resto.split()),
        scadenza=scadenza,
        origine=origine,
        completato=completato,
        chiuso_il=chiuso_il,
        chiuso_via=chiuso_via,
    )


def data_documento(doc):
    """La data di 'Ultimo aggiornamento' come datetime, o None.

    Serve a chi corregge il documento a mano: una correzione non deve far
    avanzare quel campo, perché è il riferimento che distingue le risposte già
    lavorate da quelle nuove. Spostarlo in avanti farebbe saltare in silenzio
    una risposta arrivata nel frattempo.
    """
    try:
        return datetime.strptime(doc.aggiornato_il, "%Y-%m-%d %H:%M").replace(tzinfo=FUSO)
    except (TypeError, ValueError):
        return None


def leggi(testo):
    """Legge il documento di stato. Solleva FormatoNonValido se non lo è."""
    if not testo.strip():
        raise FormatoNonValido("Il documento di stato è vuoto.")

    prossimo = _PROSSIMO_ID.search(testo)
    if not prossimo:
        raise FormatoNonValido(
            "Manca la riga 'Prossimo ID libero:'. Non è un documento di stato "
            "valido, e ricostruirlo da zero farebbe risorgere i task già chiusi."
        )

    doc = Documento(prossimo_id=int(prossimo.group(1)))
    aggiornamento = _AGGIORNAMENTO.search(testo)
    if aggiornamento:
        doc.aggiornato_il = aggiornamento.group(1)

    sezioni = _sezioni(testo)
    for riga in _unisci_continuazioni(sezioni.get("APERTI", [])):
        task = _leggi_task(riga)
        if task:
            doc.aperti.append(task)
    for riga in _unisci_continuazioni(sezioni.get("COMPLETATI", [])):
        task = _leggi_task(riga)
        if task:
            task.completato = True
            doc.completati.append(task)
    for riga in _unisci_continuazioni(sezioni.get("DA CHIARIRE", [])):
        if riga.startswith("- "):
            doc.da_chiarire.append(" ".join(riga[2:].split()))

    return doc


def scrivi(doc, adesso=None):
    """Rende il documento nella sua forma canonica."""
    adesso = adesso or ora_locale()
    parti = [
        INTESTAZIONE,
        f"Ultimo aggiornamento: {adesso.strftime('%Y-%m-%d %H:%M')}",
        f"Prossimo ID libero: {doc.prossimo_id:03d}",
        "",
        "## APERTI",
        "",
    ]
    parti += [t.riga() for t in doc.aperti] or ["_(nessun task aperto)_"]
    parti += ["", "## COMPLETATI", ""]
    parti += [t.riga() for t in doc.completati] or ["_(nessun task completato)_"]
    parti += ["", "## DA CHIARIRE", ""]
    parti += [_avvolgi(f"- {v}", rientro="  ") for v in doc.da_chiarire] or ["_(niente da chiarire)_"]
    return "\n".join(parti) + "\n"
