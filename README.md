# notpicturedstudio

System für vollsynthetische Werbebilder. Stand: **Schritt 0** (minimales End-to-End ohne GPU und ohne echtes Bildmodell).

Dokumente: [`docs/HANDOFF.md`](docs/HANDOFF.md), [`docs/LIZENZPRUEFUNG.md`](docs/LIZENZPRUEFUNG.md), [`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md), [`docs/ANFORDERUNGEN.md`](docs/ANFORDERUNGEN.md).

## Einrichten

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

## Ausprobieren

Beispiel-Brief bis zum gekennzeichneten Bild:

```bash
.venv/bin/nps run --demo --out out --safety-gate mock_only --approve-as "Dein Name"
```

Audit-Kette prüfen:

```bash
.venv/bin/nps verify --out out
```

Tests:

```bash
.venv/bin/python -m pytest
```

Ergebnis in `out/`: `audit.jsonl` (Hash-Kette), `dossier-<kampagne>.json`, `assets/<id>/final.png`.

## Was Schritt 0 kann und was nicht

| Baustein | Stand |
|---|---|
| Brief-Prüfung | Nur Kinder von 2 bis 10 Jahren. Windel-, Bade-, Schwimm- und Unterwäsche-Kategorien sowie entsprechende Begriffe im Text werden abgelehnt |
| Engine | nur Test-Engine: abstrakte Farbflächen, deterministisch, keine Menschen |
| Produkt-Treue | Produkt wird in Originalgröße eingesetzt; Pixelvergleich nach dem Einsetzen und nochmals am fertigen Bild |
| Safety-Gate | Platzhalter. Standard `block_all` blockiert alles; `mock_only` lässt nur die Test-Engine durch |
| Review | Freigabe mit Namen ist Pflicht; ohne sie entsteht kein fertiges Bild |
| Kennzeichnung | nur sichtbares Label; C2PA und Wasserzeichen folgen in Schritt 2 |
| Audit | Hash-Kette als Datei; Postgres und qualifizierte Zeitstempel folgen später |
| Dossier | JSON, ausschließlich aus der Audit-Kette erzeugt |
