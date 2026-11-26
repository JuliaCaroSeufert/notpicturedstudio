# Handoff: Stand am 11.11.2026 (für die GPU-Session)

Dieses Dokument überträgt den Stand in eine neue Session, die direkt auf dem GPU-Rechner läuft. Die frühere Fassung (Stand nach der Recherche) liegt in der Git-Historie.

**Sprache:** Die Auftraggeberin schreibt Deutsch und wird geduzt. Sie ist keine Entwicklerin: Ergebnisse in Alltagssprache erklären, Entscheidungen als konkrete Fragen vorlegen.

**Arbeitsweise (von ihr so gewollt):** Modul für Modul, mit Tests und einem Checkpoint-Bericht nach jedem Schritt. Vor jedem neuen Schritt ihr OK abwarten. Vor jeder Modellfestlegung die Lizenz an der Quelle lesen und jedes Gating nennen. Bei Unsicherheit blockieren statt durchlassen.

**Branch:** `claude/hopeful-clarke-eyxge1`.

## 1. Dokumente

| Datei | Inhalt |
|---|---|
| `README.md` | Einrichtung, Befehle, Stand je Baustein |
| `docs/ANFORDERUNGEN.md` | Prozess-Entscheidungen der Auftraggeberin (gilt bei Widerspruch) |
| `docs/ARCHITEKTUR.md` | Module, Engine-Schnittstelle, Reihenfolge; Abschnitt 8 enthält alle späteren Anpassungen |
| `docs/LIZENZPRUEFUNG.md` | Bildmodelle und BFL-Bedingungen, an den Originaltexten gelesen |
| `docs/LIZENZPRUEFUNG_SCHRITT3.md` | Erkennungsmodelle, Messwerte, offene Kalibrierung |
| `docs/GPU_EINRICHTUNG.md` | Anleitung, nach der dieser Rechner eingerichtet wurde |

## 2. Was gebaut ist (177 Tests, alle ohne GPU)

- **Schritt 0/0b:** Kampagne → Shooting → Motiv → Variante (mind. 6) → Fassung (V1, V2 …); Audit-Hash-Kette; Zustand wird nur aus der Kette gelesen; Dossier als JSON.
- **Schritt 1:** FLUX.2-[klein]-4B-Adapter, nur Text-zu-Bild, Revisionen gepinnt. **Noch nie auf einer GPU gelaufen.**
- **Schritt 2:** Versiegeln mit sichtbarem Label (links unten), Wasserzeichen-Schnittstelle, C2PA-Signatur (Testzertifikat). TrustMark ist angebunden, aber **nie mit dem echten Modell gelaufen**.
- **Schritt 3:** Upload-Gate (YuNet, RT-DETR v2) und vorläufiges Safety-Gate (Freepik, Marqo), mit echten Modellen auf CPU getestet. Schwellen **nicht kalibriert**.
- **Schritt 4:** Register der Marken-Kinder (Kandidat → Vier-Augen → Trainingssatz → Training → Einfrieren → Vorrat/Marke → Mitwachsen). Training ist ein **Platzhalter**.

## 3. Geltende Entscheidungen für v1

- Nur ein Kind pro Bild, 2 bis 10 Jahre. Säuglinge, 11 bis 17 Jahre, Erwachsene, mehrere Personen: v2.
- Produkte stehen oder liegen neben dem Kind. Gehalten: v2. Getragene Kleidung: später.
- Windel-, Bade-, Schwimm- und Unterwäsche-Kontexte ausgeschlossen.
- Nur FLUX.2 [klein] 4B. Die zweite Engine (Qwen) und die Posen-Bibliothek werden in v1 nicht gebraucht. RefControl-LoRA ist gestrichen.
- Kein Sprachmodell für das Briefing; Formular von Hand.
- Marken-Kinder: Mischform aus internem Vorrat und exklusiver Sperre; Start mit Auswahl pro Kunde.
- Produktfoto darf als Ganzes angeglichen werden (Helligkeit, Farbstich), Farbe und Form des Produkts bleiben. Noch nicht gebaut.
- Upload-Gate: Gesicht → abgelehnt; größerer Personenbereich ohne Gesicht (ab 15 %) → Mensch entscheidet; kleiner Personenbereich → angenommen.
- Kein BFL-Konto, keine BFL-API. Abgleich gegen reale Personen bleibt abgeschaltet.

## 4. Aufgaben für die GPU-Session (in dieser Reihenfolge, jeweils mit Checkpoint)

1. **Umgebung:** Der Rechner ist eine IONOS Cloud GPU VM in Frankfurt (H200-S: eine H200 mit rund 141 GB Grafikspeicher, Ubuntu, Benutzer vermutlich `root`), 3,00 € pro Stunde. Scaleway und OVHcloud hat die Auftraggeberin nach schlechten Erfahrungen verworfen; später ist ein Monatsserver bei Hetzner geplant (GEX44 mit 20 GB, dann Speicherbedarf beachten). Stand bei der Einrichtung (26.11.2026): GPU ist eine **H200 NVL mit 141 GB**, Treiber `nvidia-driver-580-server-open` (580.178.04, CUDA 13.0) ist installiert, Systemupdates sind eingespielt, die Firewall `ufw` ist aktiv und lässt nur SSH durch. Achtung: Die zuletzt installierten torch-Pakete waren für CUDA 13.2 gebaut; falls torch die GPU mit dem 580er-Treiber nicht findet, das torch-Paket für CUDA 13.0 nehmen statt den Treiber zu wechseln. Dann `python3 -m venv .venv`, dann `.venv/bin/pip install -e ".[dev,gpu,detectors]"`, `nvidia-smi` prüfen, `.venv/bin/python scripts/fetch_models.py`, Tests laufen lassen. Die Hugging-Face-Bibliothek lädt hier normal; in der alten Umgebung war ein Download-Server gesperrt.
   **Erledigt am 26.11.2026:** torch zuerst aus dem CUDA-13.0-Index installieren (`.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu130`), danach das Projekt; so findet torch 2.14.1+cu130 die H200 mit dem 580er-Treiber. pip hat diffusers 0.43.0 und transformers 5.24.1 gezogen (nicht 0.42.1). Die vier Erkennungsmodelle laden und bestehen die Prüfsummen, alle 177 Tests laufen durch.
2. **Erster echter FLUX-Lauf:** `.venv/bin/python scripts/gpu_smoke.py --out smoke`. Erzeugt ein Stillleben ohne Menschen und prüft, ob derselbe Seed dasselbe Bild gibt. Ladezeit, Zeit pro Bild und Speicherbedarf festhalten. Falls der Adapter nicht läuft: korrigieren (er ist nur gegen einen Ersatz getestet).
3. **Wasserzeichen:** `pip install -e ".[watermark]"`, TrustMark mit echtem Modell prüfen. Kernfrage: Bleibt das Wasserzeichen lesbar, nachdem die Produktpixel zurückkopiert wurden, auch bei großem Produkt? Wenn nicht: der Auftraggeberin die Wahl zwischen kleiner Toleranz im Produktbereich und Verzicht dort vorlegen.
4. **Schwellen des Safety-Gates** an echten erzeugten Bildern einstellen. Bis dahin gilt für jedes echte Bild: provisorisches Gate plus menschliche Prüfung. Keine problematischen Bilder beschaffen oder erzeugen, um die Erkenner zu testen.
5. **Referenzbilder und LoRA im FLUX-Adapter** (diffusers 0.42.1 hat `Flux2KleinPipeline` mit `image=`-Referenzen, `Flux2KleinInpaintPipeline` und LoRA-Laden). Danach die Capabilities des Adapters erweitern; das Register lehnt diese Schritte mit FLUX bisher ab.
6. **Echter LoRA-Trainer** hinter der `Trainer`-Schnittstelle auf FLUX.2 [klein] Base 4B. Den Speicherbedarf messen und festhalten: Für den späteren Hetzner-Server ist wichtig, ob Training und Bilderzeugung mit 20 GB auskommen.
7. Der Rechner wird nach jeder Arbeitssitzung gelöscht: vor dem Ende immer committen und pushen, und heruntergeladene Modelle sind beim nächsten Mal neu zu laden.
8. Erst danach und nur mit ihrem OK: erstes Marken-Kind mit dem echten Modell. **Vorher** muss die BFL-Frage angestoßen sein (Abschnitt 5, Punkt 1).
9. Danach Schritt 6 der Architektur (Ähnlichkeitsprüfung mit DINOv2, Markenfarben-Check), dann Review-Oberfläche, Dossier als PDF, Regressionssuite, Betrieb.

## 5. Offene Punkte bei der Auftraggeberin

1. **BFL-Klärung** (vor dem ersten echten Kind): Gelten für selbst betriebenes klein 4B nur Apache 2.0 und die Usage Policy? Erfasst das Upload-Verbot unter 18 auch vollsynthetische Kinder? Sie wollte die E-Mail noch nicht; bei Punkt 8 erneut anbieten.
2. **Thorn** (vor dem ersten Kundenbild): Anfrage beim Vertrieb für die selbst betriebene Variante. Angebot aus externem Review, nicht geprüft.
3. **C2PA:** anerkanntes Zertifikat und Zeitstempel-Dienst vor der ersten Auslieferung.
4. **Anwalt:** Hände in Referenzfotos (Kinderhand = Foto eines echten Kindes), § 184b StGB und Risikostufen, Anbieter- oder Betreiberrolle nach EU AI Act, Umgang mit blockierten Bildern (löschen oder aufbewahren).
5. Bria als Alternative nur, falls Kunden Nachweise zur Datenherkunft verlangen.

## 6. Bekannte Schwächen

- Der Wortfilter im Briefing ist grob und lehnt lieber zu viel ab.
- Marqo schlägt bei flächigen Grafiken fälschlich an (bis etwa 0,5), bei Fotos nicht.
- Die Audit-Kette ist eine Datei und wird bei jedem Schreiben ganz geprüft; für den Betrieb ist Postgres mit qualifizierten Zeitstempeln geplant.
- Die 15-%-Grenze im Upload-Gate ist ein Vorschlag ohne Messung; ein kleines Kind von hinten im Hintergrund würde angenommen.
- Korrekturen sind bisher nur durch Wahl einer anderen Variante möglich; das gezielte Ändern eines Bildbereichs fehlt noch.
