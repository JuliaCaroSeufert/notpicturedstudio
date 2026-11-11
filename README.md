# notpicturedstudio

System für vollsynthetische Werbebilder. Stand: **Schritte 0, 0b und 1** (Ablauf mit Test-Engine; FLUX-Adapter vorbereitet, aber noch nicht auf einer GPU gelaufen).

Dokumente: [`docs/HANDOFF.md`](docs/HANDOFF.md), [`docs/LIZENZPRUEFUNG.md`](docs/LIZENZPRUEFUNG.md), [`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md), [`docs/ANFORDERUNGEN.md`](docs/ANFORDERUNGEN.md).

## Einrichten

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

## Ausprobieren

Beispiel-Shooting mit zwei Motiven und je sechs Varianten erzeugen:

```bash
.venv/bin/nps run --demo --out out --safety-gate mock_only
```

Stand ansehen (zeigt die Kennung jeder Variante):

```bash
.venv/bin/nps status --out out --campaign demo-herbst
```

Eine Variante intern freigeben; sie wird gekennzeichnet und zur Fassung V1 des Motivs:

```bash
.venv/bin/nps approve --out out --campaign demo-herbst --asset KENNUNG --by "Dein Name"
```

Fassung dem Kunden zeigen und seine Entscheidung festhalten (mit `--changes "..."` als Änderungswunsch, ohne als Abnahme):

```bash
.venv/bin/nps release --out out --campaign demo-herbst --shooting kinderzimmer --motif stapeln --version 1 --by "Dein Name"
```

```bash
.venv/bin/nps customer --out out --campaign demo-herbst --shooting kinderzimmer --motif stapeln --version 1 --by "Dein Name"
```

Audit-Kette prüfen:

```bash
.venv/bin/nps verify --out out
```

Tests:

```bash
.venv/bin/python -m pytest
```

Ergebnis in `out/`: `audit.jsonl` (Hash-Kette), `dossier-<kampagne>.json`, `assets/<kennung>/final.png`.

## Erster Lauf mit dem echten Modell (EU-GPU)

Braucht eine GPU mit mindestens 16 GB Speicher und Zugriff auf `huggingface.co` für den Download von rund 16 GB.

```bash
.venv/bin/pip install -e ".[gpu]"
```

```bash
.venv/bin/python scripts/gpu_smoke.py --out smoke
```

Das Skript erzeugt zweimal dasselbe Stillleben ohne Menschen und prüft, ob beide Läufe identisch sind. Über `nps run --engine flux2-klein-4b` wird mit dem echten Modell noch nichts ausgeliefert: Beide Platzhalter-Gates blockieren seine Ausgabe, bis das Safety-Gate aus Schritt 3 steht.

## Stand

| Baustein | Stand |
|---|---|
| Struktur | Kampagne → Shooting → Motiv → Variante → Fassung (V1, V2, …). Ein registriertes Shooting ist eingefroren; Änderungen am Briefing brauchen ein neues Shooting |
| Brief-Prüfung | Nur ein Kind von 2 bis 10 Jahren. Windel-, Bade-, Schwimm- und Unterwäsche-Kategorien sowie entsprechende Begriffe im Text werden abgelehnt |
| Engines | Test-Engine (abstrakte Farbflächen, keine Menschen) und FLUX.2 [klein] 4B (nur Text-zu-Bild; auf einer GPU noch nicht gelaufen) |
| Produkt-Treue | Produkt wird in Originalgröße eingesetzt; Pixelvergleich nach dem Einsetzen und nochmals am fertigen Bild |
| Safety-Gate | Platzhalter. Standard `block_all` blockiert alles; `mock_only` lässt nur die Test-Engine durch |
| Interne Freigabe | mit Namen; macht eine Variante zur nächsten Fassung. Eine neue Fassung ist nur nach einem Änderungswunsch des Kunden möglich |
| Kunde | sieht nur freigegebene Fassungen; Abnahme oder Änderungswunsch wird protokolliert |
| Korrekturen | bisher nur durch Auswahl einer anderen oder neu erzeugten Variante; gezielte Änderung eines Bildbereichs folgt |
| Kennzeichnung | nur sichtbares Label links unten; C2PA und Wasserzeichen folgen in Schritt 2 |
| Audit | Hash-Kette als Datei; Postgres und qualifizierte Zeitstempel folgen später |
| Dossier | JSON, ausschließlich aus der Audit-Kette erzeugt |
