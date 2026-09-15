---
name: brief-ora
description: Manda subito il brief dei task, lanciando in cloud lo stesso giro schedulato. Usala quando l'utente chiede la lista task adesso, un brief anticipato, di rimandare la mail dei task, o di aggiornare i task dopo delle riunioni. Attenzione, non è una semplice rispedizione - rilegge Granola e le risposte via mail, fa interpretare al modello e aggiorna il documento di stato, quindi può chiudere task o crearne di nuovi.
---

# Brief dei task, adesso

Anticipa il giro che normalmente fa partire lo scheduler esterno.

**Non è una rispedizione della lista.** È l'esecuzione vera: rilegge le note
Granola degli ultimi 10 giorni, rilegge le risposte via mail, fa interpretare
tutto al modello, **riscrive e committa il documento di stato**, poi manda la
mail. Può chiudere task e crearne di nuovi.

Dillo all'utente in una riga prima di lanciare. Non serve però chiedere
conferma: invocare questa skill è già la richiesta.

Se l'utente vuole solo vedere cosa succederebbe senza conseguenze, esiste la
modalità di prova — vedi in fondo.

## Perché in cloud e non qui

Il giro gira su GitHub Actions, non in locale, per due motivi che non vanno
aggirati:

- le chiavi di Granola e Gemini vivono nei secret del repository, non in
  locale;
- `google-genai` 2.x richiede Python ≥ 3.10: se la macchina locale ne ha una
  più vecchia, la chiamata al modello qui non parte proprio.

Dispacciare il workflow garantisce anche che il giro manuale e quello
schedulato eseguano lo stesso identico codice.

## Cosa fare

Dalla radice del repo.

1. **Lancia il giro:**

   ```
   gh workflow run brief-giornaliero.yml --ref main
   ```

2. **Prendi l'id del run** appena creato:

   ```
   gh run list --workflow=brief-giornaliero.yml --limit 1 --json databaseId --jq '.[0].databaseId'
   ```

3. **Aspetta che finisca** con un ciclo sullo stato, non con attese a tempo
   fisso (un giro dura di solito 20–40 secondi, ma la latenza del modello
   varia):

   ```
   until [ "$(gh run view <ID> --json status --jq .status)" = "completed" ]; do sleep 5; done
   ```

4. **Leggi l'esito** dal log:

   ```
   gh run view <ID> --log | grep -E "Stato:|Risposte:|Riunioni:|Modello:|Decisioni:|Chiusi|Nuovi|Da chiarire|Stato salvato|Mail mandata|GUASTO|ERRORE"
   ```

5. **Riallinea il clone locale e mostra il messaggio aggiornato**, perché il
   run ha committato su `main`:

   ```
   git pull && python3 scripts/brief.py --lista
   ```

   Il riepilogo dice cosa il modello ha *deciso*; il messaggio dice com'è
   *rimasto* lo stato. Servono entrambi, e va stampato sempre: senza, per
   sapere cosa c'è adesso bisogna aprire la mail.

## Cosa riportare all'utente

Non limitarti a "fatto". Dal log ricava e riporta:

- quanti task sono stati **chiusi da mail** e quali — con la frase su cui il
  modello si è basato, perché è lì che si vede un errore di interpretazione;
- quante **chiusure dedotte** dalle riunioni, e quali: sono le meno affidabili
  e vanno segnalate come da rileggere;
- quali **task nuovi** sono stati creati;
- **il messaggio risultante**, stampato al passo 5: è quello che l'utente valuta;
- eventuali righe `GUASTO:` — riportale come sono, senza reinterpretarle: un
  guasto non ferma il giro ma toglie una fonte (per esempio Granola
  irraggiungibile significa nessun task nuovo estratto quel giorno).

Se qualcosa sembra sbagliato, la correzione si fa con la skill
`brief-correggi`, non modificando il documento a mano.

## Modalità di prova

Se l'utente vuole vedere le decisioni **senza** salvare né spedire:

```
gh workflow run brief-giornaliero.yml --ref main -f prova=true
```

Il log stampa le stesse righe, ma il documento non viene toccato e non parte
nessuna mail.

## Regole

- Il destinatario non si sceglie: sta in `scripts/config.json` e gli script non
  accettano indirizzi sulla riga di comando. Se l'utente chiede di mandarlo a
  qualcun altro, spiega che va fatto a mano.
- Non modificare il workflow, gli script o la configurazione per far girare il
  brief: se qualcosa non funziona, riportalo.
- Non usare connettori di posta come ripiego se il giro fallisce.
