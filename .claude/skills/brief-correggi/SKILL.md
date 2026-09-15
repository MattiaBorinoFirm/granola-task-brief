---
name: brief-correggi
description: Corregge la lista dei task e rispedisce subito la versione corretta. Usala quando l'utente dice che il brief ha sbagliato - un task chiuso per errore da riaprire, un typo o una descrizione da sistemare, una scadenza o un cliente sbagliati, un task inventato da togliere, una voce di "Da chiarire" da rimuovere. Modifica stato/task-document.md rispettando le invarianti, lo committa e manda la lista aggiornata.
---

# Correggere la lista dei task

Il brief sbaglia: è previsto, ed è il motivo per cui ogni chiusura arriva con
la frase su cui si è basata. Questa skill rimette le cose a posto **senza
aggirare le invarianti** del sistema.

Le chiusure dedotte dalle riunioni sono le più fragili — non sono nemmeno
riproducibili fra un'esecuzione e l'altra — quindi sono il caso più frequente
di correzione.

## Cosa fare

Dalla radice del repo.

### 1. Allinea, poi **mostra il messaggio integrale**

```
git pull && python3 scripts/brief.py --lista
```

Il giro in cloud potrebbe aver riscritto il documento pochi minuti fa, quindi
prima ci si allinea.

**Va stampato sempre, senza aspettare che lo si chieda.** Chiedere «cosa vuoi
correggere?» a chi non ha davanti i task è una domanda irrispondibile:
presuppone di ricordare a memoria venti task aperti e nove chiusi.

Quello che compare non assomiglia alla mail: **è** la mail, resa dalla stessa
funzione che ne compone il corpo — descrizioni per intero, scadenze, urgenze,
raggruppate per cliente. Sopra ci sono le chiusure, che il corpo della mail non
riporta fuori dal giro in cui avvengono.

Guarda in particolare la sezione **CHIUSI PER DEDUZIONE**: sono le chiusure che
il modello ha ricavato dalle riunioni anziché dalle tue risposte via mail, e in
esecuzioni ripetute sugli stessi input ne produce di diverse ogni volta. Sono
il candidato più probabile di correzione. Le chiusure che arrivano dalle mail
si sono invece rivelate stabili: mostrale, ma non trattarle come sospette.

Se l'utente non ha detto cosa correggere, è a questo punto che glielo chiedi —
con la lista già davanti.

### 2. Modifica passando dal parser, mai a mano

Il formato del documento è definito in `scripts/statodoc.py`. Modificare il
testo a occhio rischia di produrre righe che il parser poi non rilegge. Carica,
modifica in memoria, riscrivi:

```python
import sys; sys.path.insert(0, "scripts")
import statodoc

doc = statodoc.leggi(open("stato/task-document.md").read())

t = doc.per_id("021")          # il task da correggere

# riaprire un task chiuso per errore
doc.completati.remove(t); t.completato = False
t.chiuso_il = ""; t.chiuso_via = ""
doc.aperti.append(t)

# oppure: correggere testo, scadenza, cliente
# t.descrizione = "..."
# t.scadenza = "2026-09-30"      (oppure "nessuna")
# t.cliente = "Borealis"

# oppure: chiudere a mano un task aperto
# doc.aperti.remove(t); t.completato = True
# t.chiuso_il = statodoc.ora_locale().date().isoformat()
# t.chiuso_via = "correzione manuale"; doc.completati.append(t)

# oppure: togliere una voce da "Da chiarire"
# doc.da_chiarire = [v for v in doc.da_chiarire if "testo da togliere" not in v]

testo = statodoc.scrivi(doc, statodoc.data_documento(doc))
open("/tmp/stato-corretto.md", "w").write(testo)
```

**`statodoc.data_documento(doc)` non è facoltativo.** Conserva il campo
`Ultimo aggiornamento`. Se lo lasci avanzare, tutte le risposte arrivate fra
l'ultimo giro e adesso verranno considerate già lavorate e **saltate per
sempre**.

### 3. Mostra il diff e fallo confermare

```
diff stato/task-document.md /tmp/stato-corretto.md
```

Aspetta il via libera prima di salvare.

### 4. Salva

```
./scripts/salva-stato.sh --correzione /tmp/stato-corretto.md
```

**Il flag va sempre**, anche per un semplice typo. Dichiara che a scrivere è
una persona e non l'esecuzione automatica, e fa due cose: marca il commit come
`Correzione manuale dello stato: …`, così nello storico non si confonde con un
giro del mattino, e accetta che i completati diminuiscano — necessario per
riaprire un task, e invece sempre sintomo di guasto quando capita
all'automazione.

Il flag **non** disattiva gli altri controlli: se lo script rifiuta per altri
motivi (documento vuoto, riga `Prossimo ID libero:` mancante), leggi cosa dice
e correggi il documento, non cercare di aggirarlo.

### 5. Rispedisci sempre

```
python3 scripts/brief.py --solo-invio
```

Rende la lista corretta e la manda nel thread. Non chiama il modello, non legge
Granola, non rilegge la posta: nessuna interpretazione, quindi nessun rischio
di introdurre un errore nuovo mentre ne correggi uno.

### 6. Conserva il filo del thread

L'invio ha modificato `stato/thread.json`. Se resta indietro, la catena del
thread diverge da quella che userà il giro in cloud:

```
git add stato/thread.json
git commit -m "Filo del thread dopo la rispedizione"
git push
```

Due commit per correzione — documento e filo — sono attesi, non un errore.

### 7. Mostra com'è rimasto

```
python3 scripts/brief.py --lista
```

Chiudere il giro con il messaggio aggiornato rende visibile l'effetto della
correzione, invece di lasciare l'utente a fidarsi di un «fatto». È anche
l'occasione in cui si notano i difetti di resa: guardare il messaggio per
intero mostra cose che un riassunto nasconde.

## Regole ferme

- **Gli ID non si riusano e non si rinumerano mai.** Nemmeno togliendo un task:
  il buco nella numerazione è corretto e va lasciato.
- **Tocca solo ciò che l'utente ha nominato.** Non sistemare altri task che ti
  sembrano sbagliati: segnalali e basta.
- **Non potare i completati** se non come riapertura esplicita, con il flag.
- **Se non è chiaro quale task**, chiedi invece di indovinare. È lo stesso
  principio che regge tutto il resto del sistema: un abbinamento sbagliato fra
  una frase e un task è il danno peggiore che si possa fare qui.
- Non modificare `scripts/config.json`, il workflow o gli script per far
  passare una correzione.

## Se invece serve rifare il giro

Correggere è un'altra cosa dal rieseguire. Se l'utente vuole che il sistema
rilegga Granola e le risposte e ricalcoli tutto, è la skill `brief-ora`.
