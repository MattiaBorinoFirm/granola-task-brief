# Task Granola

Struttura del documento di stato, che vive in `stato/task-document.md` ed è
versionato in git. È la fonte di verità del sistema: la mail è solo una vista,
il documento è lo stato. `git log -- stato/task-document.md` ne mostra tutta
la storia, un commit per esecuzione.

---

```
# Task Granola
Ultimo aggiornamento: 2026-09-14 09:00
Prossimo ID libero: 031

## APERTI

- [ ] (024) [Borealis] Rivedere il file macchine di Rossi e dare feedback
      sul perimetro consolidato — scadenza 2026-09-15 — origine: SAL
      infrastruttura, 2026-09-09
- [ ] (027) [Orion] Tabella scenari e vantaggi dell'agente —
      scadenza: nessuna — origine: riunione Orion, 2026-09-10
- [ ] (030) [interno] Prenotare la sala per il kickoff — scadenza 2026-09-16
      — origine: mail 13/09

## COMPLETATI

- [x] (019) [Zenith] Convertire le slide nel template aziendale —
      chiuso 2026-09-12 — via mail
- [x] (021) [Vertex] Verificare la documentazione della procedura di accesso —
      chiuso 2026-09-11 — dedotto dalle riunioni, confermato
```

## Regole di formato

**ID.** Tre cifre, progressivi, mai riusati. Sono l'aggancio fra le mie
risposte in linguaggio libero e i task: senza ID l'abbinamento diventa
indovinare. Il contatore `Prossimo ID libero` in testa evita collisioni fra
esecuzioni.

**Origine.** Sempre presente. O `riunione <nome>, <data>` oppure `mail GG/MM`.
Serve a capire da dove è sbucato un task che non riconosco.

**Scadenza.** `nessuna` se non è stata detta. Non inventarne.

**Completati.** Crescono per sempre. Non è disordine: è l'indice di
deduplicazione. `scripts/salva-stato.sh` rifiuta qualunque scrittura in cui il
numero di completati sia sceso. Quando il documento diventa scomodo da leggere,
si archivia a mano l'anno precedente in un secondo file — mai automaticamente.

**Da chiarire.** Terza sezione, facoltativa: ci finiscono le ambiguità che il
brief ha già segnalato, così non si perdono fra una mattina e l'altra.
