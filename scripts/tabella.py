#!/usr/bin/env python3
"""Il brief: tabella HTML e fallback in testo semplice.

Prima lo componeva il modello a ogni esecuzione, ~20K token di HTML scritti a
mano ogni mattina. Qui è codice: l'urgenza è aritmetica sulle date, il
raggruppamento è un sort, e la mail di domani ha la stessa forma di quella di
oggi perché è la stessa funzione a produrla.

Solo libreria standard.
"""

import html
from datetime import date

# Ordine di gravità: guida sia il colore sia l'ordinamento dei clienti.
SCADUTA, OGGI, ALTA, MEDIA, BASSA, NESSUNA = range(6)

ETICHETTE = {
    SCADUTA: "Scaduta", OGGI: "Oggi", ALTA: "Alta",
    MEDIA: "Media", BASSA: "Bassa", NESSUNA: "Nessuna",
}

# Solo style inline: niente CSS esterno, niente script. I client di posta
# buttano via il resto, e una mail non deve eseguire nulla.
COLORI = {
    SCADUTA: ("#fdecea", "#b3261e"),
    OGGI:    ("#fdecea", "#b3261e"),
    ALTA:    ("#fff4e5", "#a15c00"),
    MEDIA:   ("#f5f5f5", "#3c4043"),
    BASSA:   ("#f5f5f5", "#3c4043"),
    NESSUNA: ("#f5f5f5", "#80868b"),
}

TITOLO_MAX = 48


def urgenza(task, oggi=None):
    """L'urgenza di un task rispetto a oggi. Aritmetica, non opinione."""
    oggi = oggi or date.today()
    scadenza = task.scadenza_data

    if scadenza is None:
        testo = f"{task.scadenza} {task.origine}".lower()
        return ALTA if "priorità alta" in testo or "priorita alta" in testo else NESSUNA

    mancano = (scadenza - oggi).days
    if mancano < 0:
        return SCADUTA
    if mancano == 0:
        return OGGI
    if mancano <= 2:
        return ALTA
    if mancano <= 7:
        return MEDIA
    return BASSA


def titolo(task):
    """Poche parole per riconoscere il task a colpo d'occhio.

    Derivato dalla descrizione invece che chiesto al modello: così è stabile
    fra un giorno e l'altro e non costa token. Si taglia alla prima pausa
    forte, che nella pratica è dove finisce il verbo principale.
    """
    testo = task.descrizione.strip()
    for pausa in (": ", "; ", ", "):
        if 0 < testo.find(pausa) <= TITOLO_MAX:
            testo = testo[:testo.find(pausa)]
            break
    if len(testo) > TITOLO_MAX:
        tagliato = testo[:TITOLO_MAX].rsplit(" ", 1)[0]
        testo = tagliato + "…"
    return testo


def _per_cliente(task_list, oggi):
    """Raggruppa per cliente, i clienti più urgenti per primi."""
    gruppi = {}
    for t in task_list:
        gruppi.setdefault(t.cliente, []).append(t)
    for task_cliente in gruppi.values():
        task_cliente.sort(key=lambda t: (urgenza(t, oggi), t.id))
    return sorted(
        gruppi.items(),
        key=lambda voce: (min(urgenza(t, oggi) for t in voce[1]), voce[0].lower()),
    )


# --- HTML ------------------------------------------------------------------

_TD = "padding:6px 10px;border-bottom:1px solid #e8eaed;vertical-align:top;"


def _tabella_html(task_list, oggi):
    if not task_list:
        return ""
    righe = [
        '<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;'
        'width:100%;font-size:14px;margin:8px 0 20px;">',
        '<tr style="text-align:left;background:#f1f3f4;">'
        f'<th style="{_TD}">Cliente</th><th style="{_TD}">Titolo</th>'
        f'<th style="{_TD}">Descrizione</th><th style="{_TD}">Scadenza</th>'
        f'<th style="{_TD}">Urgenza</th></tr>',
    ]
    for cliente, task_cliente in _per_cliente(task_list, oggi):
        for posizione, t in enumerate(task_cliente):
            grado = urgenza(t, oggi)
            sfondo, inchiostro = COLORI[grado]
            # Il nome del cliente solo sulla prima riga del gruppo: si legge
            # come una tabella divisa per cliente senza ripeterlo trenta volte.
            etichetta = html.escape(cliente) if posizione == 0 else ""
            righe.append(
                f'<tr><td style="{_TD}font-weight:600;">{etichetta}</td>'
                f'<td style="{_TD}white-space:nowrap;">({t.id}) {html.escape(titolo(t))}</td>'
                f'<td style="{_TD}">{html.escape(t.descrizione)}</td>'
                f'<td style="{_TD}white-space:nowrap;">{html.escape(t.scadenza or "nessuna")}</td>'
                f'<td style="{_TD}background:{sfondo};color:{inchiostro};'
                f'font-weight:600;white-space:nowrap;">{ETICHETTE[grado]}</td></tr>'
            )
    righe.append("</table>")
    return "\n".join(righe)


def _elenco_html(voci):
    if not voci:
        return ""
    punti = "".join(f"<li style=\"margin:4px 0;\">{html.escape(v)}</li>" for v in voci)
    return f'<ul style="font-size:14px;padding-left:20px;margin:8px 0 20px;">{punti}</ul>'


def componi_html(brief, oggi=None):
    oggi = oggi or date.today()
    fuori = [
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,'
        'sans-serif;color:#202124;max-width:900px;">',
        f'<p style="font-size:14px;">Task del giorno — {oggi.strftime("%d/%m/%Y")}.</p>',
    ]

    def sezione(titolo_sezione, corpo):
        if corpo:
            fuori.append(
                f'<h3 style="font-size:15px;margin:24px 0 4px;">{titolo_sezione}</h3>'
            )
            fuori.append(corpo)

    sezione("Task aperti", _tabella_html(brief["aperti"], oggi))
    sezione("Nuovi dalle riunioni", _tabella_html(brief["nuovi_riunioni"], oggi))
    sezione("Aggiunti da te", _tabella_html(brief["nuovi_mail"], oggi))
    sezione("Ho segnato come fatto", _elenco_html(brief["fatti"]))
    sezione("Chiusi in base alle riunioni", _elenco_html(brief["dedotti"]))
    sezione("Da chiarire", _elenco_html(brief["da_chiarire"]))

    if brief["guasti"]:
        punti = "".join(f"<li>{html.escape(g)}</li>" for g in brief["guasti"])
        fuori.append(
            '<p style="font-size:13px;color:#b3261e;margin-top:24px;">'
            f'Problemi in questa esecuzione:<ul>{punti}</ul></p>'
        )

    fuori.append(
        '<p style="font-size:13px;color:#5f6368;margin-top:24px;">'
        'Rispondi pure come ti viene: la tabella è solo per leggere meglio, '
        'la mail resta un thread di testo.</p></div>'
    )
    return "\n".join(fuori)


# --- testo semplice --------------------------------------------------------


def _tabella_testo(task_list, oggi):
    if not task_list:
        return []
    righe = []
    for cliente, task_cliente in _per_cliente(task_list, oggi):
        righe.append(f"  {cliente}:")
        for t in task_cliente:
            # Niente titolo qui: è una troncatura della descrizione, e in una
            # riga di testo le due si ripeterebbero. Nella tabella HTML sono
            # colonne distinte e la ripetizione non c'è.
            righe.append(
                f"    ({t.id}) {t.descrizione} — "
                f"{t.scadenza or 'nessuna'} — {ETICHETTE[urgenza(t, oggi)]}"
            )
        righe.append("")
    return righe


def componi_testo(brief, oggi=None):
    oggi = oggi or date.today()
    fuori = [f"Task del giorno — {oggi.strftime('%d/%m/%Y')}", ""]

    def sezione(titolo_sezione, righe):
        if righe:
            fuori.append(titolo_sezione.upper())
            fuori.append("")
            fuori.extend(righe)
            fuori.append("")

    sezione("Task aperti", _tabella_testo(brief["aperti"], oggi))
    sezione("Nuovi dalle riunioni", _tabella_testo(brief["nuovi_riunioni"], oggi))
    sezione("Aggiunti da te", _tabella_testo(brief["nuovi_mail"], oggi))
    sezione("Ho segnato come fatto", [f"  - {v}" for v in brief["fatti"]])
    sezione("Chiusi in base alle riunioni", [f"  - {v}" for v in brief["dedotti"]])
    sezione("Da chiarire", [f"  - {v}" for v in brief["da_chiarire"]])

    if brief["guasti"]:
        sezione("Problemi in questa esecuzione", [f"  - {g}" for g in brief["guasti"]])

    fuori.append("Rispondi pure come ti viene.")
    return "\n".join(fuori)
