#!/usr/bin/env python3
"""Posta della casella bot: invio del brief e rilettura delle risposte.

Solo libreria standard. La password per app arriva dalla variabile d'ambiente
MAIL_APP_PASSWORD (su un runner) o dal portachiavi di macOS (in locale), e non
viene mai scritta su disco né stampata.

    mailbox.py check                 verifica password, SMTP e IMAP
    mailbox.py read-replies          stampa le risposte recenti, come testo
    mailbox.py send --body-file F    manda il brief in testo semplice
    mailbox.py send --html-file F --text-file F2
                                      manda il brief in HTML, con F2 come
                                      fallback testo per i client che non
                                      renderizzano HTML
"""

import argparse
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parsedate_to_datetime

import imaplib

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, os.pardir, "stato", "thread.json")
# Dov'era prima che l'esecuzione si spostasse su un runner: se c'è ancora,
# viene letto una volta sola per non spezzare il thread nella migrazione.
STATE_LEGACY = os.path.expanduser("~/.local/state/granola-task-bot/state.json")


ENV_PASSWORD = "MAIL_APP_PASSWORD"

# Nessuna connessione deve poter bloccare l'esecuzione a tempo indefinito: un
# brief che non arriva è meglio di un job appeso che scade dopo un quarto d'ora
# senza aver spedito né segnalato niente.
TIMEOUT = 30


class Problema(Exception):
    """Errore atteso, da riportare all'utente senza traceback."""


# --- configurazione e stato ------------------------------------------------


def leggi_config():
    try:
        with open(CONFIG_PATH) as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        raise Problema(f"Manca il file di configurazione {CONFIG_PATH}.")
    except json.JSONDecodeError as exc:
        raise Problema(f"{CONFIG_PATH} non è JSON valido: {exc}")

    if not cfg.get("bot_address"):
        raise Problema(
            "In scripts/config.json il campo 'bot_address' è vuoto.\n"
            "Va compilato con l'indirizzo della casella dedicata prima di poter\n"
            "mandare o leggere posta."
        )
    for campo in ("recipient", "subject", "keychain_service"):
        if not cfg.get(campo):
            raise Problema(f"In scripts/config.json manca il campo '{campo}'.")
    return cfg


def leggi_stato():
    for percorso in (STATE_PATH, STATE_LEGACY):
        try:
            with open(percorso) as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return {}


def scrivi_stato(stato):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(stato, fh, indent=2)
    os.replace(tmp, STATE_PATH)


def password(cfg):
    """La password per app. Mai stampata, mai salvata.

    Due sorgenti, nell'ordine: la variabile d'ambiente, che è come la riceve un
    runner da un secret, e il portachiavi di macOS, che è come la si tiene sul
    Mac. L'ambiente vince, così in CI non si va a cercare un `security` che non
    esiste.
    """
    dall_ambiente = os.environ.get(ENV_PASSWORD, "").strip()
    if dall_ambiente:
        return dall_ambiente

    try:
        esito = subprocess.run(
            [
                "security", "find-generic-password",
                "-s", cfg["keychain_service"],
                "-a", cfg["bot_address"],
                "-w",
            ],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        raise Problema(
            f"Nessuna password: la variabile {ENV_PASSWORD} non è impostata e "
            "il comando\n`security` non esiste (siamo fuori da macOS). Su un "
            "runner la password\narriva dal secret, non dal portachiavi."
        )
    except subprocess.CalledProcessError:
        raise Problema(
            "Password per app non trovata nel portachiavi.\n"
            "Depositala con questo comando (la digiti tu, lo script la legge soltanto):\n\n"
            f"  security add-generic-password -s {cfg['keychain_service']} "
            f"-a {cfg['bot_address']} -w\n"
        )
    return esito.stdout.strip()


def sorgente_password():
    """Da dove arriva la password, per dirlo in chiaro nel check."""
    if os.environ.get(ENV_PASSWORD, "").strip():
        return f"variabile d'ambiente {ENV_PASSWORD}"
    return "portachiavi di macOS"


# --- connessioni -----------------------------------------------------------


def connetti_imap(cfg):
    try:
        conn = imaplib.IMAP4_SSL(
            cfg["imap_host"], cfg["imap_port"],
            ssl_context=ssl.create_default_context(), timeout=TIMEOUT,
        )
        conn.login(cfg["bot_address"], password(cfg))
    except imaplib.IMAP4.error as exc:
        raise Problema(
            f"IMAP ha rifiutato l'accesso: {exc}\n"
            "Di solito significa password per app sbagliata, oppure verifica in due\n"
            "passaggi non attiva sulla casella."
        )
    except OSError as exc:
        raise Problema(
            f"Non riesco a raggiungere {cfg['imap_host']} entro {TIMEOUT}s: {exc}"
        )
    return conn


def connetti_smtp(cfg):
    try:
        conn = smtplib.SMTP_SSL(
            cfg["smtp_host"], cfg["smtp_port"],
            context=ssl.create_default_context(), timeout=TIMEOUT
        )
        conn.login(cfg["bot_address"], password(cfg))
    except smtplib.SMTPAuthenticationError:
        raise Problema(
            "SMTP ha rifiutato l'accesso.\n"
            "Di solito significa password per app sbagliata, oppure verifica in due\n"
            "passaggi non attiva sulla casella."
        )
    except OSError as exc:
        raise Problema(f"Non riesco a raggiungere {cfg['smtp_host']}: {exc}")
    return conn


# --- lettura delle risposte ------------------------------------------------


TAGLI = [
    re.compile(r"^\s*Il .* ha scritto:\s*$"),
    re.compile(r"^\s*On .* wrote:\s*$"),
    re.compile(r"^\s*-{2,}\s*Messaggio originale\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*_{5,}\s*$"),
]


def testo_visibile(msg):
    """Il corpo scritto davvero, senza la citazione del messaggio precedente."""
    parte = msg.get_body(preferencelist=("plain",))
    if parte is None:
        parte = msg.get_body(preferencelist=("html",))
        if parte is None:
            return ""
        grezzo = re.sub(r"<[^>]+>", " ", parte.get_content())
    else:
        grezzo = parte.get_content()

    righe = []
    for riga in grezzo.splitlines():
        if any(t.match(riga) for t in TAGLI):
            break
        if riga.lstrip().startswith(">"):
            continue
        righe.append(riga.rstrip())

    return "\n".join(righe).strip()


def raccogli_risposte(cfg, giorni):
    """Le risposte recenti nel thread, come dati: [(data, testo), ...].

    Separata dalla stampa perché il brief la importa: leggere di nuovo con un
    parser l'output pensato per gli occhi sarebbe un giro inutile e fragile.
    """
    conn = connetti_imap(cfg)
    raccolte = []
    try:
        conn.select("INBOX", readonly=True)
        dal = (datetime.now(timezone.utc) - timedelta(days=giorni)).strftime("%d-%b-%Y")
        stato, dati = conn.search(None, "SINCE", dal, "FROM", cfg["recipient"])
        if stato != "OK":
            raise Problema(f"Ricerca IMAP fallita: {stato}")

        atteso = cfg["subject"].lower()
        for num in dati[0].split():
            stato, dati_msg = conn.fetch(num, "(RFC822)")
            if stato != "OK" or not dati_msg or not isinstance(dati_msg[0], tuple):
                continue
            msg = message_from_bytes(dati_msg[0][1], policy=policy.default)

            if atteso not in (msg.get("Subject") or "").lower():
                continue

            try:
                quando = parsedate_to_datetime(msg.get("Date")).astimezone()
            except (TypeError, ValueError):
                quando = None

            corpo = testo_visibile(msg)
            if corpo:
                raccolte.append((quando, corpo))
    finally:
        try:
            conn.close()
        except imaplib.IMAP4.error:
            pass
        conn.logout()

    raccolte.sort(key=lambda v: (v[0] is None, v[0]))
    return raccolte


def read_replies(cfg, giorni):
    raccolte = raccogli_risposte(cfg, giorni)
    if not raccolte:
        print(
            f"Nessuna risposta da {cfg['recipient']} nel thread "
            f"'{cfg['subject']}' negli ultimi {giorni} giorni."
        )
        return
    for quando, corpo in raccolte:
        etichetta = quando.strftime("%Y-%m-%d %H:%M") if quando else "data sconosciuta"
        print(f"--- risposta del {etichetta} ---")
        print(corpo)
        print()


# --- invio -----------------------------------------------------------------


def _leggi_corpo(path, etichetta):
    try:
        with open(path) as fh:
            testo = fh.read()
    except FileNotFoundError:
        raise Problema(f"Il file {etichetta} non esiste: {path}")

    if not testo.strip():
        raise Problema(f"Il file {etichetta} è vuoto: non mando niente.")
    return testo


def send(cfg, body_file=None, html_file=None, text_file=None):
    if html_file:
        html = _leggi_corpo(html_file, "HTML")
        testo = _leggi_corpo(text_file, "di testo (fallback)")
    else:
        corpo = _leggi_corpo(body_file, "del corpo")

    stato = leggi_stato()
    catena = stato.get("references", [])

    msg = EmailMessage()
    msg["From"] = cfg["bot_address"]
    msg["To"] = cfg["recipient"]
    msg["Subject"] = cfg["subject"]
    msg["Date"] = formatdate(localtime=True)
    mio_id = make_msgid(domain=cfg["bot_address"].split("@")[-1])
    msg["Message-ID"] = mio_id
    if catena:
        msg["In-Reply-To"] = catena[-1]
        msg["References"] = " ".join(catena)

    if html_file:
        msg.set_content(testo)
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(corpo)

    conn = connetti_smtp(cfg)
    try:
        rifiutati = conn.send_message(msg)
    except smtplib.SMTPException as exc:
        raise Problema(f"Invio fallito: {exc}")
    finally:
        conn.quit()

    if rifiutati:
        raise Problema(f"Destinatario rifiutato dal server: {rifiutati}")

    # La catena tiene l'ancora e le ultime voci: basta a Gmail per il thread,
    # e impedisce all'header References di crescere senza limite.
    catena.append(mio_id)
    stato["references"] = catena[:1] + catena[-8:] if len(catena) > 9 else catena
    stato["ultimo_invio"] = datetime.now(timezone.utc).isoformat()
    scrivi_stato(stato)

    print(f"Mail mandata da {cfg['bot_address']} a {cfg['recipient']}.")


# --- verifica --------------------------------------------------------------


def check(cfg):
    print(f"Casella bot:   {cfg['bot_address']}")
    print(f"Destinatario:  {cfg['recipient']}")
    print(f"Thread:        {cfg['subject']}")

    password(cfg)
    print(f"Password:      trovata ({sorgente_password()})")

    conn = connetti_imap(cfg)
    conn.select("INBOX", readonly=True)
    conn.close()
    conn.logout()
    print(f"IMAP:          accesso riuscito su {cfg['imap_host']}")

    conn = connetti_smtp(cfg)
    conn.quit()
    print(f"SMTP:          accesso riuscito su {cfg['smtp_host']}")

    stato = leggi_stato()
    if stato.get("ultimo_invio"):
        print(f"Ultimo invio:  {stato['ultimo_invio']}")
    else:
        print("Ultimo invio:  mai (il primo brief aprirà il thread)")

    print("\nTutto a posto.")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("check", help="verifica portachiavi, SMTP e IMAP")

    p_read = sub.add_parser("read-replies", help="stampa le risposte recenti")
    p_read.add_argument("--days", type=int, default=None,
                        help="giorni da guardare indietro (default: da config.json)")

    p_send = sub.add_parser("send", help="manda il brief in coda al thread")
    p_send.add_argument("--body-file", help="file col corpo della mail, testo semplice")
    p_send.add_argument("--html-file", help="file col corpo della mail, HTML")
    p_send.add_argument("--text-file", help="fallback testo semplice per --html-file")

    args = p.parse_args()

    if args.comando == "send":
        if args.html_file and not args.text_file:
            p.error("--html-file richiede anche --text-file (fallback testo)")
        if not args.html_file and not args.body_file:
            p.error("serve --body-file, oppure --html-file insieme a --text-file")
        if args.html_file and args.body_file:
            p.error("--body-file e --html-file sono alternativi, non insieme")

    try:
        cfg = leggi_config()
        if args.comando == "check":
            check(cfg)
        elif args.comando == "read-replies":
            read_replies(cfg, args.days or cfg.get("reply_lookback_days", 4))
        elif args.comando == "send":
            send(cfg, body_file=args.body_file, html_file=args.html_file, text_file=args.text_file)
    except Problema as exc:
        # Svuota stdout prima di scrivere su stderr, altrimenti in un log
        # l'errore compare sopra le righe di contesto che lo spiegano.
        sys.stdout.flush()
        print(f"\nERRORE: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
