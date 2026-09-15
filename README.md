# Granola Task Brief

Brief giornaliero dei task estratti dalle note di riunione di
[Granola](https://granola.ai) e aggiornati rispondendo a un messaggio di posta
elettronica. L'esecuzione avviene interamente su GitHub Actions, senza
infrastruttura dedicata.

Lo stato dei task risiede nel repository dell'utente. I dati di esempio
inclusi sono fittizi e il documento di stato viene distribuito vuoto.

## Funzionamento

A ogni esecuzione il workflow di GitHub Actions:

1. legge il documento di stato `stato/task-document.md`;
2. recupera via IMAP le risposte presenti nel thread di posta, sulla casella
   dedicata, e ne ricava chiusure, rinvii e nuovi task;
3. recupera via API REST le note Granola degli ultimi 10 giorni, seleziona i
   task in carico all'intestatario e scarta quelli già presenti o già chiusi;
4. riscrive il documento di stato e lo committa;
5. invia il messaggio via SMTP all'indirizzo configurato, nello stesso thread.

```
Granola API (10gg, sola lettura) ┐
                                 ├─→ [GitHub Actions] ─→ Gemini API
casella bot, IMAP ───────────────┘          │
                                            ├─→ stato (git, committato)
                                            └─→ SMTP ─→ utente ─┐
        ▲                                                       │
        └───────────────────────────────────────────────────────┘
```

L'avvio non è affidato allo scheduler di GitHub. Il workflow espone
unicamente `workflow_dispatch` e viene invocato da uno scheduler esterno
tramite le API di GitHub; la configurazione è descritta in
[`docs/installazione.md`](docs/installazione.md).

## Architettura

Il modello riceve il documento di stato, le risposte e le note di riunione, e
restituisce esclusivamente un oggetto JSON contenente le decisioni. La
generazione del documento, della tabella HTML, delle urgenze e degli
identificativi è affidata al codice Python.

Le invarianti del sistema sono implementate nel codice:

- **Identificativi.** Tre cifre, progressivi, mai riutilizzati. Il contatore
  `Prossimo ID libero` in testa al documento previene le collisioni fra
  esecuzioni.
- **Casella dedicata.** Il brief è inviato da un indirizzo dedicato e le
  risposte sono raccolte sulla stessa casella. Il destinatario è definito in
  `scripts/config.json` e non è accettato da riga di comando.
- **Completati.** Non vengono mai rimossi: `scripts/salva-stato.sh` rifiuta
  ogni scrittura in cui il numero dei task completati risulti diminuito. Al
  modello sono mostrati i completati degli ultimi 30 giorni; `scripts/brief.py`
  non viene eseguito se la finestra dei completati non è superiore a quella
  delle riunioni.
- **Deduplica.** `scripts/brief.py` confronta ogni nuovo task con quelli
  aperti dello stesso cliente e scarta i duplicati, riportandoli nel
  riepilogo di esecuzione.

## Prerequisiti

- Una **chiave API Granola** (`grn_`), generabile da un membro di un workspace
  su piano Business.
- Una **chiave API Gemini**.
- Una **casella di posta dedicata**, con verifica in due passaggi e una
  password per app.
- Un **repository GitHub privato** con GitHub Actions abilitato.
- Un account presso uno **scheduler esterno** (ad esempio cron-job.org).

## Installazione

La procedura completa è documentata in
[`docs/installazione.md`](docs/installazione.md).

In sintesi: creare una copia privata del repository, compilare
`scripts/config.json` con identità e indirizzi, configurare i tre secret di
repository (`GRANOLA_API_KEY`, `GEMINI_API_KEY`, `MAIL_APP_PASSWORD`) e
impostare lo scheduler esterno perché invochi il workflow agli orari
desiderati.

`scripts/config.json` è l'unico file da personalizzare. Il system prompt è un
modello: nome, indirizzo ed eventuale omonimo da distinguere sono sostituiti a
ogni esecuzione a partire dalla configurazione.

## Costo

Valori misurati su esecuzioni reali, con circa 25 task in archivio e 15
riunioni in finestra: **~19K token in ingresso e 0,1–0,3K in uscita**. Con
`gemini-3.5-flash-lite`, a 0,30 $/1M token in ingresso e 2,50 $/1M in uscita,
il costo è di **circa 0,006 $ per esecuzione**, inferiore a 0,20 $ al mese.

Il consumo di GitHub Actions è di circa 2 minuti al giorno, ovvero circa 60
minuti al mese sui 2000 della quota gratuita per repository privati.

Il modello è configurabile tramite la variabile di repository `GEMINI_MODEL`;
`GEMINI_THINKING` ne regola il livello di ragionamento.

## Comandi

All'interno del repository, in Claude Code, sono disponibili due skill:

- **`/brief-ora`** — anticipa l'esecuzione pianificata. Rilegge le note
  Granola e le risposte, invoca il modello e **aggiorna il documento di
  stato**; può pertanto chiudere o creare task.
- **`/brief-correggi`** — corregge il documento quando il brief contiene un
  errore: un task chiuso per sbaglio, un errore di battitura, una scadenza
  errata. Modifica il documento tramite il parser, lo committa come correzione
  manuale e invia la versione aggiornata.

Entrambe stampano il messaggio integrale, generato dalla stessa funzione che
compone il corpo della mail. Il medesimo output è ottenibile con:

```bash
python3 scripts/brief.py --lista
```

Il comando è di sola lettura e non effettua invii. Il riepilogo che precede il
messaggio elenca le chiusure, riportando in una sezione separata quelle
dedotte dalle riunioni.

La correzione utilizza `scripts/salva-stato.sh --correzione`, che registra nel
commit l'origine manuale della modifica e consente la diminuzione del numero
dei completati, operazione necessaria per riaprire un task. Il campo
`Ultimo aggiornamento` è conservato durante una correzione.

## Limiti noti

- **Granola è utilizzato in sola lettura.** Nessun dato è scritto nelle note:
  lo stato dei task risiede unicamente in `stato/task-document.md`.
- **L'interpretazione del linguaggio naturale può produrre errori.** Ogni
  chiusura è rendicontata nel brief successivo insieme alla frase su cui si
  basa.
- **I task il cui proprietario non è determinabile non vengono acquisiti** e
  sono riportati nella sezione «Da chiarire».
- **L'invio è limitato all'indirizzo configurato** in `scripts/config.json`;
  lo script non accetta destinatari da riga di comando.
- **Le chiusure dedotte dalle riunioni non sono riproducibili.** A parità di
  stato e di note, due esecuzioni consecutive hanno dedotto la chiusura di
  task differenti; le chiusure ricavate dalle risposte dell'utente sono
  invece risultate stabili. Le deduzioni sono riportate in una sezione
  separata del brief, con la relativa motivazione.
- **Le note prive di summary elaborato non sono restituite dall'API** e non
  vengono acquisite: una riunione registrata da pochi minuti può non essere
  ancora disponibile.
- **Un'esecuzione non effettuata viene recuperata automaticamente.** La
  finestra delle riunioni è di 10 giorni, quella delle risposte di 14.
- **Il token utilizzato dallo scheduler esterno ha una scadenza.** Alla
  scadenza l'invio del brief si interrompe senza segnalazione: la
  configurazione delle notifiche di fallimento dello scheduler e di un
  promemoria di rinnovo è parte della procedura di installazione.
- **Il documento di stato è committato prima dell'invio.** In caso di errore
  SMTP il lavoro non viene perso e l'invio è ripetibile con `--solo-invio`; il
  fallimento è rilevabile unicamente dai log di GitHub Actions.

## Struttura

```
.github/workflows/brief-giornaliero.yml   il workflow, avviato dall'esterno
prompts/estrazione-task.md     system prompt, con i segnaposto dell'identità
scripts/brief.py               esecuzione: raccolta, interrogazione, invio
scripts/statodoc.py            lettura e scrittura del documento di stato
scripts/tabella.py             composizione del brief: tabella HTML e testo
scripts/granola.py             recupero delle note dalla API REST Granola
scripts/mailbox.py             invio e rilettura sulla casella dedicata
scripts/salva-stato.sh         scrittura e commit del documento di stato
.claude/skills/                le skill brief-ora e brief-correggi
scripts/config.json            identità, indirizzi, host, finestre temporali
requirements.txt               dipendenze: il client Gemini
stato/task-document.md         documento di stato, un commit per esecuzione
stato/thread.json              header di continuità del thread di posta
templates/task-document.md     documento di stato vuoto, per l'inizializzazione
docs/come-rispondere.md        formati riconosciuti nelle risposte
docs/installazione.md          procedura di installazione
```

## Licenza

Distribuito con licenza MIT. Vedere [`LICENSE`](LICENSE).
