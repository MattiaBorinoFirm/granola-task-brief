# Granola Task Brief

Un brief giornaliero dei tuoi task, estratti dalle note delle riunioni di
[Granola](https://granola.ai) e tenuti aggiornati **rispondendo a una mail**.

Niente app da aprire, niente board da curare: la lista arriva in casella, e per
chiudere un task rispondi al messaggio. Gira interamente su GitHub Actions,
senza macchine accese.

> Questa è la versione pubblica, pensata perché chiunque possa installarla sul
> proprio account. I dati di esempio sono di fantasia; lo stato dei task nasce
> vuoto e resta nel **tuo** repository.

## Come funziona

Due volte al giorno un workflow di GitHub Actions:

1. legge il documento di stato `stato/task-document.md`;
2. legge le tue risposte nel thread mail — via IMAP, su una casella dedicata —
   e ne ricava chiusure, rinvii e task nuovi;
3. rilegge le note Granola **degli ultimi 10 giorni** via API REST, tiene solo i
   task in carico a te e scarta quelli già presenti o già chiusi;
4. riscrive il documento e lo committa;
5. manda la mail via SMTP, solo al tuo indirizzo, nello stesso thread.

```
Granola API (10gg, sola lettura) ┐
                                 ├─→ [GitHub Actions] ─→ Gemini API
casella bot, IMAP ───────────────┘          │
                                            ├─→ stato (git, committato)
                                            └─→ SMTP ─→ te ─┐
        ▲                                                   │
        └───────────────────────────────────────────────────┘
```

A far partire il workflow **non è il cron di GitHub** ma uno scheduler esterno
che chiama `workflow_dispatch` via API. Non è un vezzo: vedi
[`docs/installazione.md`](docs/installazione.md), dove è spiegato il perché con
le misure che l'hanno motivato.

## Le cinque decisioni che reggono il sistema

**Gli ID.** Le risposte via mail sono in linguaggio libero, quindi serve un
aggancio stabile fra una frase e un task. Senza ID l'abbinamento è
interpretazione pura, e gli errori restano invisibili.

**La posta sta su una casella sua.** Il brief parte da un indirizzo creato
apposta e le risposte tornano lì. Così l'automazione non ha in mano la tua
posta personale, e il vincolo sul destinatario non è una riga di prompt ma una
riga di configurazione che il modello non può scavalcare.

**I completati non si potano mai.** La finestra Granola ripassa ogni giorno
sulle stesse riunioni. L'unica cosa che impedisce a un task chiuso di risorgere
è trovarlo ancora fra i completati. Non è una regola scritta nel prompt:
`salva-stato.sh` si rifiuta di scrivere un documento in cui i completati sono
diminuiti.

Al modello però se ne mostrano solo **gli ultimi 30 giorni**, non tutti. Un task
può risorgere soltanto da una riunione ancora dentro la finestra di 10 giorni:
passata quella, la sua chiusura non protegge più da niente e resterebbe solo a
gonfiare il prompt — che senza taglio crescerebbe all'infinito, di circa 57.000
token in un anno, peggiorando proprio il confronto che dovrebbe aiutare. Il
rapporto fra le due finestre non è lasciato al caso: `brief.py` si rifiuta di
partire se il taglio dei completati non supera quello delle riunioni.

**La deduplica è codice, non una richiesta.** Il prompt chiede al modello di non
riproporre task già presenti, e per un po' è bastato — finché quattro giri
ravvicinati sugli stessi verbali non hanno prodotto gli stessi task in tripla
copia. Delegare un'invariante al modello significa non averla. Ora `brief.py`
confronta ogni task nuovo con gli aperti dello stesso cliente e scarta le
copie, dicendolo nel riepilogo: una soglia può sbagliare, e un task buttato via
in silenzio sarebbe peggio del doppione che evita.

**Il modello decide, il codice esegue.** Il modello riceve stato, risposte e
note e restituisce **solo un JSON di decisioni**. Il documento, la tabella HTML,
le urgenze e gli ID li produce Python, in modo deterministico. Tutto ciò che si
può verificare non viene chiesto a un modello: gli ID non si riusano perché lo
garantisce un contatore, non perché il prompt lo raccomanda.

## Cosa serve

- Una **chiave API Granola** (`grn_`), generabile da un membro di un workspace
  su piano Business. *Il connettore MCP di Granola non serve: si autentica solo
  via OAuth da browser, quindi è inutilizzabile da un runner.*
- Una **chiave API Gemini**, per la chiamata al modello.
- Una **casella mail dedicata** (Gmail gratuito va benissimo), con verifica in
  due passaggi e una password per app.
- Un **repository GitHub privato** con Actions attive — privato perché lo stato
  conterrà i tuoi task veri.
- Un account su uno **scheduler esterno** gratuito (per esempio cron-job.org).

## Installazione

Tutti i passi, in ordine, stanno in
[`docs/installazione.md`](docs/installazione.md).

In sintesi: fai un fork o una copia privata di questo repository, compila
`scripts/config.json` con la tua identità e i tuoi indirizzi, metti tre secret
nel repository (`GRANOLA_API_KEY`, `GEMINI_API_KEY`, `MAIL_APP_PASSWORD`) e
configura lo scheduler esterno perché chiami il workflow agli orari che
preferisci.

**L'unico file da personalizzare è `scripts/config.json`.** Il prompt è un
modello: nome, indirizzo ed eventuale omonimo da non confondere vengono
sostituiti a ogni esecuzione a partire da lì.

## Costo

Misurato su esecuzioni vere, con ~25 task in archivio e ~15 riunioni in
finestra: **~19K token in ingresso e 0,1–0,3K in uscita**. Con
`gemini-3.5-flash-lite` a 0,30 $/1M in ingresso e 2,50 $/1M in uscita fanno
**~0,006 $ a giro**, sotto i 0,20 $ al mese.

L'uscita è così piccola perché il modello restituisce solo decisioni: il
documento e la tabella, che sono la parte voluminosa, li scrive Python.

I minuti di Actions consumati sono ~2 al giorno — una sessantina al mese sui
2000 della quota gratuita dei repository privati.

Il modello si cambia dalla variabile di repository `GEMINI_MODEL` senza toccare
il codice, e `GEMINI_THINKING` regola quanto ragiona.

**Il modello leggero è un punto di equilibrio scelto, non un dettaglio.** Le
chiusure che gli **dici tu** le abbina agli ID giusti in modo affidabile; quelle
che deve **dedurre dalle riunioni** cambiano fra un'esecuzione e l'altra a
parità di input. Per questo ogni chiusura arriva nel brief con la frase su cui
si è basata: è lì che si vede. Se le chiusure sbagliate diventano fastidiose,
`GEMINI_MODEL` si alza di un gradino senza toccare una riga.

## Le due skill

Dentro Claude Code, nel repo, sono disponibili due comandi:

- **`/brief-ora`** — anticipa il giro schedulato. Non è una rispedizione:
  rilegge Granola e le risposte, fa interpretare al modello e **aggiorna lo
  stato**, quindi può chiudere o creare task.
- **`/brief-correggi`** — corregge la lista quando il brief ha sbagliato: un
  task chiuso per errore, un typo, una scadenza sbagliata. Modifica il
  documento passando dal parser, lo committa come *correzione manuale* e
  rispedisce la versione corretta.

Entrambe stampano a schermo il messaggio integrale, reso dalla stessa funzione
che compone il corpo della mail: quello che leggi non assomiglia a quello che
arriva in casella, è quello. Lo stesso comando si usa da solo:

```bash
python3 scripts/brief.py --lista
```

Non tocca niente e non manda niente. Sopra il messaggio elenca le chiusure, con
quelle **dedotte dalle riunioni** in una sezione a parte: il corpo della mail le
riporta solo nel giro in cui avvengono, ma sono quelle da rileggere e servono
sempre sott'occhio.

La correzione usa `salva-stato.sh --correzione`, che dichiara nel commit che a
scrivere è stata una persona e accetta che i completati diminuiscano — cosa
necessaria per riaprire un task, e invece sempre sintomo di guasto quando capita
all'automazione. La guardia resta quindi intatta dove serve.

Conservare `Ultimo aggiornamento` durante una correzione non è un dettaglio: è
il campo che distingue le risposte già lavorate dalle nuove, e farlo avanzare
farebbe saltare in silenzio una risposta arrivata nel frattempo.

## Limiti noti

- **Granola è in sola lettura.** Niente viene scritto nelle note: lo stato dei
  task vive solo in `stato/task-document.md`.
- **L'interpretazione del linguaggio libero sbaglia.** Il sistema non lo
  nasconde: ogni chiusura viene rendicontata nella mail del giorno dopo insieme
  alla frase su cui si è basata. Vedere gli errori è più utile che evitarli.
- **I task senza proprietario chiaro non entrano.** Finiscono in "Da chiarire".
  È voluto: riempire la lista di task altrui la rende inutile in una settimana.
- **L'esecuzione non manda mail a nessuno tranne te.** Il destinatario sta in
  `scripts/config.json` e lo script non accetta indirizzi sulla riga di comando.
  Se serve girare qualcosa a un collega, resta una cosa da fare a mano.
- **Le chiusure dedotte dalle riunioni non sono ripetibili.** Osservato: a
  parità di stato e di note, due esecuzioni consecutive hanno dedotto la
  chiusura di due task diversi. Le chiusure ricavate dalle tue risposte sono
  invece risultate stabili. Per questo le deduzioni finiscono in una sezione a
  parte del brief, con il motivo: sono da rileggere, non da fidarsi.
- **Le note senza summary vengono saltate.** L'API restituisce solo note già
  elaborate; una riunione registrata da pochi minuti può non esserci ancora.
- **Un'esecuzione saltata si recupera da sola.** Riunioni a 10 giorni, risposte
  a 14: una settimana di ferie rientra senza perdere niente.
- **Il brief dipende da un token che scade.** Lo scheduler esterno chiama l'API
  di GitHub con un token a scadenza: quando scade, il brief smette di arrivare
  **senza che nessuno lo segnali**. Le notifiche di fallimento dello scheduler e
  un promemoria in calendario sono parte dell'installazione, non un optional.
- **Un giro che fallisce dopo aver salvato non avvisa.** Lo stato viene
  committato prima dell'invio, di proposito: se l'SMTP rifiuta, il lavoro non è
  perso e si rispedisce con `--solo-invio`. Ma il fallimento resta visibile solo
  in Actions.

## Struttura

```
.github/workflows/brief-giornaliero.yml   il giro completo, avviato da fuori
prompts/estrazione-task.md     il system prompt, con i segnaposto dell'identità
scripts/brief.py               l'esecuzione: raccoglie, interroga, applica, manda
scripts/statodoc.py            il formato del documento di stato: legge e scrive
scripts/tabella.py             il brief: tabella HTML e fallback testo
scripts/granola.py             le note delle riunioni dalla API REST Granola
scripts/mailbox.py             invio e rilettura sulla casella dedicata
scripts/salva-stato.sh         scrive e committa il documento di stato
.claude/skills/                le due skill: brief-ora e brief-correggi
scripts/config.json            identità, indirizzi, host, finestre
requirements.txt               l'unica dipendenza: il client Gemini
stato/task-document.md         lo stato vero, un commit per esecuzione
stato/thread.json              gli header che tengono insieme il thread mail
templates/task-document.md     documento di stato vuoto, per ripartire
docs/come-rispondere.md        cosa viene capito bene nelle risposte
docs/installazione.md          i passi, in ordine
```

## Licenza

MIT, vedi [`LICENSE`](LICENSE): prendilo, copialo, adattalo.
