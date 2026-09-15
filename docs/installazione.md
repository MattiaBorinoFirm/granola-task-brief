# Installazione

Dall'inizio alla prima mail. Serve mezz'ora.

## 1. Il repository

Fai una **copia privata** di questo repository — fork, oppure "Use this
template", oppure un clone ripubblicato. Privata, non pubblica: lo stato
conterrà i tuoi task veri, con nomi di clienti e di persone.

Il documento di stato `stato/task-document.md` arriva vuoto. Non toccarlo: ci
pensa l'automazione dal primo giro.

Due impostazioni del repository, da controllare subito perché il guasto che
provocano si vede solo al primo giro vero:

- **Settings → Actions → General → Workflow permissions**: deve essere
  *Read and write permissions*. Il workflow dichiara `contents: write` perché
  ricommitta lo stato dei task, ma una dichiarazione non può alzare un permesso
  che il repository tiene basso: con l'impostazione di sola lettura il brief
  arriva e il commit dello stato fallisce.
- Se hai fatto un **fork**, le Actions sui fork nascono disattivate: vai in
  **Actions** e abilitale, altrimenti il `workflow_dispatch` dello scheduler
  riceve un `204` e non parte niente.

## 2. Le credenziali

Tre secret, in **Settings → Secrets and variables → Actions → New repository
secret**. Nessuno di questi valori va mai nel codice.

| Secret | Cos'è | Dove si prende |
|---|---|---|
| `GRANOLA_API_KEY` | chiave `grn_` della Granola API | app desktop Granola, impostazioni → API keys (richiede piano Business) |
| `GEMINI_API_KEY` | chiave della Gemini API | aistudio.google.com/apikey |
| `MAIL_APP_PASSWORD` | password per app della casella bot | impostazioni Google dell'account bot, dopo aver attivato la verifica in due passaggi |

### Variabili facoltative

`GEMINI_MODEL` (Settings → Variables) sceglie il modello; se non c'è vale
`gemini-3.5-flash-lite`. `GEMINI_THINKING` regola quanto ragiona prima di
rispondere, fra `minimal`, `low` (default), `medium`, `high` e `off`.

`off` non è un livello: fa omettere del tutto il parametro. È la via d'uscita se
un modello rifiuta il livello richiesto — i valori accettati non sono gli stessi
per tutti.

La risposta del modello è vincolata da uno **schema JSON imposto all'API**
(`response_format`), non raccomandato a parole: o è conforme, o la chiamata
fallisce in modo visibile invece di produrre un documento storto.

## 3. La casella dedicata

Serve una casella mail **creata apposta**, non la tua personale. Gmail gratuito
va benissimo: attiva la verifica in due passaggi e genera una password per app.

Il brief parte da lì e le tue risposte tornano lì. L'automazione non tocca mai
la tua posta personale.

## 4. Il file da compilare

**È l'unico.** `scripts/config.json`:

```json
{
  "bot_address": "LA-TUA-CASELLA-BOT@gmail.com",
  "recipient": "IL-TUO-INDIRIZZO@example.com",
  "proprietario": "NOME COGNOME",
  "nome": "NOME",
  "omonimo": "",
  "contesto": "lavora su più clienti e progetti",
  "subject": "Task del giorno",
  ...
}
```

| campo | cos'è |
|---|---|
| `bot_address` | la casella dedicata, che manda e riceve |
| `recipient` | dove vuoi ricevere il brief. **Usa lo stesso indirizzo con cui compari come autore nelle note Granola** |
| `proprietario` | nome e cognome per esteso: serve al modello per capire quali task sono tuoi |
| `nome` | come ti chiamano nelle note, di solito il nome di battesimo |
| `omonimo` | se nelle riunioni compare un tuo omonimo, scrivilo qui e il modello imparerà a non confondervi. Lascialo vuoto se non serve: la regola sparisce da sola |
| `contesto` | una mezza riga su come lavori, che completa la frase «…, che ___». Serve al modello per capire cosa sia un «cliente» nelle tue riunioni |

Il prompt è un **modello**: questi valori vengono sostituiti a ogni esecuzione.
Non devi aprire `prompts/estrazione-task.md` per metterci il tuo nome.

## 5. Chi fa partire il brief

**Non il cron di GitHub.** Il workflow espone solo `workflow_dispatch`, e a
chiamarlo è uno scheduler esterno.

Non è un vezzo, è una misura. Nell'installazione dove questo sistema è nato,
`on: schedule` ha consegnato **un solo run in quattro giorni**, con **4 ore e 51
minuti di ritardo** sull'orario previsto: un brief che dice «oggi» e arriva a
mezzogiorno non è un brief. Sono stati provati tre minuti diversi (0, 7 e 23) su
due workflow, per escludere la congestione del minuto tondo; il ritardo non
dipendeva da quello. Escluse anche le cause ordinarie: workflow `active`,
repository né fork né archiviato, minuti Actions non esauriti — i dispatch
manuali riuscivano sempre.

Sul tuo account potrebbe andare meglio. Ma il dispatch è l'unica strada che si
è dimostrata puntuale, e uno scheduler esterno gestisce anche il fuso orario,
ora legale compresa, senza i cron gemelli che servirebbero altrimenti.

### La configurazione dello scheduler

Va bene qualunque servizio che sappia fare una POST con header personalizzati —
[cron-job.org](https://cron-job.org) è gratuito e li supporta.

| campo | valore |
|---|---|
| URL | `https://api.github.com/repos/TUO-UTENTE/TUO-REPO/actions/workflows/brief-giornaliero.yml/dispatches` |
| metodo | `POST` |
| corpo | `{"ref": "main"}` |
| orari | quelli che preferisci, nel tuo fuso |

Header:

```
Accept: application/vnd.github+json
Authorization: Bearer IL_TUO_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
User-Agent: un-nome-qualsiasi
```

Lo `User-Agent` non è decorativo: senza, l'API di GitHub risponde `403`.

**Attiva le notifiche di fallimento** del servizio. Non saltarlo: è la difesa
contro il giorno in cui il token scade.

### Il token, e la trappola

Token **fine-grained**, ristretto al **solo** repository, con il **solo**
permesso `Actions: Read and write`. Non può leggere il codice né i secret; può
però leggere i log delle esecuzioni, che contengono il testo dei task.

**I token scadono.** Quel giorno le chiamate cominciano a rispondere `401` e il
brief si ferma **in silenzio** — esattamente il modo di fallire che questa
architettura vuole eliminare. Due difese, entrambe necessarie: le notifiche di
fallimento dello scheduler, e un promemoria in calendario qualche giorno prima
della scadenza.

Se il brief smette di arrivare, guarda qui per primo. Il log delle esecuzioni
dello scheduler mostra la risposta di GitHub: `401`/`403` è il token, `404` di
solito è il permesso che non vede il repository (su un repo privato GitHub
risponde 404 anche per i permessi), `204` è stata accettata.

## 6. Il fuso orario

Le date del documento di stato e delle scadenze sono calcolate in
**Europe/Rome**, scritto in `scripts/statodoc.py` (`FUSO = ZoneInfo(...)`) e
richiamato nel workflow per la data del commit. Se lavori altrove, cambia
quella riga e la riga `TZ=` in `.github/workflows/brief-giornaliero.yml`: sono
le uniche due occorrenze.

Gli orari di partenza non stanno qui — li decide lo scheduler esterno, punto 5.

## 7. Le skill di Claude Code (facoltative)

In `.claude/skills/` ci sono due comandi, disponibili se apri il repository con
Claude Code:

- `/brief-ora` dispaccia il workflow e ti riporta cosa ha deciso il modello;
- `/brief-correggi` corregge la lista quando il brief ha sbagliato e rispedisce
  la versione corretta.

Non servono a far funzionare l'automazione: senza Claude Code, il giro parte
lo stesso dallo scheduler, e le stesse cose si fanno a mano con
`gh workflow run brief-giornaliero.yml` e `python3 scripts/brief.py --lista`.

## 8. La prima prova

Prima di aspettare lo scheduler, prova a mano: **Actions → Brief task
giornaliero → Run workflow**, con la casella *prova* spuntata. Non salva niente
e non manda niente, ma esegue tutto il resto e stampa cosa avrebbe deciso.

Se va, ripeti senza *prova*: dovresti ricevere la prima mail.

## Perché non i connettori

**Granola.** Il connettore MCP di Granola si autentica **solo** con OAuth da
browser: la documentazione dice esplicitamente che per MCP «non esiste API key
o service account». Su un runner non c'è un browser dove completare il login,
quindi è irraggiungibile da CI su qualunque piano. La Granola API REST è
l'esatto opposto — solo chiave Bearer — ed è quella che usa `scripts/granola.py`.

**Posta.** Lo strumento di invio del connettore Gmail manda sempre e solo
dall'account autenticato e non espone alcun campo `from`: il mittente lo decide
quale account è collegato, non il prompt. Affiancarne uno sulla casella dedicata
avrebbe dato all'esecuzione automatica pieni poteri sulla posta personale. Da
qui la scelta: **la posta non passa da nessun connettore**, ma da SMTP e IMAP
diretti.

## Il thread delle mail

La casella bot manda il brief al tuo indirizzo. Tu rispondi. La risposta torna
nella casella bot, e l'esecuzione successiva la rilegge lì in IMAP. Per capire
quali risposte sono nuove confronta la loro data con il campo
`Ultimo aggiornamento` del documento di stato: niente flag da spostare.

Il threading è tenuto da `stato/thread.json`, versionato nel repo e
ricommittato dopo ogni invio. Se si perdesse, il thread si spezzerebbe in due:
fastidioso, non grave, e si riannoda da solo.

## Il documento di stato

`stato/task-document.md`, versionato in git: un commit per esecuzione, scritto
da `scripts/salva-stato.sh`. Git dà lo storico —
`git log -p -- stato/task-document.md` mostra quando un task è nato, quando è
stato chiuso e come è cambiato.

Il formato non è descritto a parole in un prompt: è codice, in
`scripts/statodoc.py`, che lo legge e lo riscrive con la stessa definizione.

## Le tre finestre

| Finestra | Valore | Dove | A cosa serve |
|---|---|---|---|
| Riunioni Granola | 10 giorni | `GIORNI_RIUNIONI` in `brief.py` | quanto indietro si cercano task nuovi |
| Completati mostrati | 30 giorni | `GIORNI_COMPLETATI` in `brief.py` | quanto indietro si ricorda al modello di non riproporli |
| Risposte via mail | 14 giorni | `reply_lookback_days` in `config.json` | quanto indietro si rileggono le tue risposte |

Le prime due sono legate: un task chiuso può risorgere solo da una riunione
ancora leggibile, quindi il taglio dei completati **deve** superare la finestra
delle riunioni. `brief.py` lo verifica e si rifiuta di partire se la relazione
si rompe, invece di produrre in silenzio task duplicati.

La terza è indipendente e più larga di quanto sembri necessario, di proposito.
Non serve a evitare che una risposta venga lavorata due volte — a quello pensa
il confronto con `Ultimo aggiornamento` — ma è solo il limite della ricerca
IMAP. Allargarla non produce doppioni e copre un fermo di due settimane.

## Un'insidia dell'API Granola

La documentazione descrive un campo `summary` nelle note; l'API restituisce
`summary_markdown` e `summary_text`. Cercare il nome documentato non produce un
errore: produce **zero note, in silenzio**, perché le note senza sommario
vengono scartate per tenere basso il payload.

`granola.py check` esiste per questo: stampa le chiavi della risposta grezza e i
campi delle prime note, così la differenza fra "lista vuota", "note senza
sommario" e "campo con un altro nome" si vede in un colpo d'occhio. Si lancia
anche sul runner, con l'interruttore *diagnostica* di Run workflow.

## Provare in locale

Tutto gira anche sulla tua macchina, purché le variabili siano esportate:

```bash
export GRANOLA_API_KEY=grn_...
export GEMINI_API_KEY=...
export MAIL_APP_PASSWORD=...
python3 scripts/granola.py check      # la chiave Granola vede le note?
python3 scripts/mailbox.py check      # password, IMAP e SMTP rispondono?
python3 scripts/brief.py --dry-run    # il giro completo, senza conseguenze
python3 scripts/brief.py --lista      # il messaggio a schermo, senza spedirlo
```

`--dry-run` scrive brief HTML, fallback testo e nuovo documento di stato in una
cartella temporanea e ne stampa il percorso.

Attenzione a Python: `google-genai` 2.x richiede **Python ≥ 3.10**. Con una
versione più vecchia il giro completo non parte, mentre `--lista`,
`--solo-invio` e `granola.py check` continuano a funzionare.

## Se qualcosa va storto

| sintomo | causa più probabile |
|---|---|
| nessuna mail, nessun run in Actions | lo scheduler esterno: token scaduto o job disattivato |
| run fallito sull'ultimo passo | SMTP: password per app sbagliata o verifica in due passaggi non attiva |
| «zero riunioni» senza errori | chiave Granola, o note senza sommario: lancia `granola.py check` |
| task doppi | due pianificatori attivi insieme: deve essercene uno solo |
| la mail arriva ma la lista è vuota | `recipient` non coincide con l'indirizzo con cui compari nelle note |
| lo stato non viene committato, il resto sì | permessi del workflow in sola lettura: vedi il punto 1 |
| `UnicodeEncodeError` lanciando gli script a mano | console Windows in cp1252: `set PYTHONIOENCODING=utf-8` prima del comando. Non riguarda il runner |
