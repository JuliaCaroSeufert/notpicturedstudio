# Architekturvorschlag (Entwurf zur Freigabe, 11.11.2026)

Aufgabe 3 aus `HANDOFF.md`, Abschnitt 7. Baut auf den Entscheidungen im Handoff und den Korrekturen aus `LIZENZPRUEFUNG.md` auf. **Es wird kein Code geschrieben, bevor dieser Entwurf freigegeben ist.**

## 1. Leitlinien

1. **Im Zweifel blockieren.** Jeder Check, der ausfällt, nicht läuft oder unsicher ist, blockiert das Asset. Ohne vollständige Check-Kette gibt es keine Auslieferung.
2. **Die Engine ist ein Adapter.** Kein Modul außerhalb von `engine/` kennt FLUX oder Qwen.
3. **Alles Relevante steht in der Audit-Kette.** Das Compliance-Dossier wird ausschließlich aus ihr erzeugt, nicht aus einem zweiten Datenbestand.
4. **Echte Kinder kommen strukturell nicht ins System.** Uploads mit Menschen werden abgelehnt; Kind-Referenzen und Trainingsbilder werden nur akzeptiert, wenn sie eine eigene C2PA-Signatur und einen Audit-Eintrag haben.
5. **Reproduzierbar per Manifest.** Jedes Bild trägt ein Manifest, aus dem es sich neu erzeugen lässt.

## 2. Ablauf

```
Intake ──> Planung ──> Generierung ──> Safety-Gate ──> Ähnlichkeit ──> Produkt-Compositing
(Brief,     (Szene,     (Engine-        (blockiert      (Register,      (Originalpixel zurück,
 Assets)     Pose,       Adapter,        hart)           Dubletten)      Pixeltest)
             Risiko)     Job-Queue)
                                                                              │
Delivery <── Kennzeichnung <── Freigabe <── Review/QC (nach Risikostufe) <────┘
(Paket +      (Label, TrustMark,             (ein oder vier Augen,
 Dossier)      C2PA als letzter Schritt)      Stichprobe, Eskalation)
```

Das Safety-Gate läuft direkt nach der Generierung, damit Reviewer nur Bilder sehen, die es bestanden haben. Blockierte Outputs werden niemandem angezeigt; ob das Bild selbst gelöscht und nur Hash und Metadaten aufbewahrt werden, ist eine Anwaltsfrage und wird konfigurierbar.

## 3. Module

Ein Python-Paket `nps` (FastAPI-Backend), ein Next.js-Frontend, Postgres, S3-kompatibler Speicher.

| Modul | Aufgabe | Wichtigste Schnittstelle |
|---|---|---|
| `core` | Datenmodelle, IDs, Hashing, Konfiguration (Secrets nur über Umgebung) | Pydantic-Modelle: `Brief`, `Asset`, `Manifest`, `CheckResult` |
| `audit` | Append-only-Hash-Kette, Zeitstempel (RFC 3161), Zustandswechsel | `append(event) -> entry`, `verify_chain()` |
| `engine` | Bildgenerierung hinter einer Schnittstelle | siehe Abschnitt 4 |
| `jobs` | Warteschlange und Worker (Postgres-basiert), Warmhalten zu Geschäftszeiten | `enqueue(job)`, `claim()`, `complete()` |
| `intake` | Brief-Validierung, Upload-Gate | `accept_upload(file) -> Accepted \| Rejected(reason)` |
| `scene` | Brief → Szenenplan: Prompt, Pose, Risikostufe | `plan(brief) -> ScenePlan` |
| `poses` | Safe-Pose-Bibliothek: versionierte Control-Bilder aus eigenen 3D-Rigs mit Freigabevermerk | `get(pose_id, version) -> ControlSet` |
| `identity` | Register der Marken, Kind-Identitäten, LoRA-Versionen, Style-Lock; Bootstrap-Workflow | `resolve(brand, child, version) -> IdentityBundle` |
| `product` | Produktmaske, Compositing, Pixeltest | `composite(scene, product, mask)`, `verify_pixels() -> CheckResult` |
| `brand` | Markenvorgaben (Farben, Logo-Schutzzonen) als Input und als Check | `check(image, brand) -> CheckResult` |
| `safety` | Safety-Gate hinter einer Schnittstelle; erst Provisorium, später Thorn | `evaluate(image) -> Pass \| Block(reason)` |
| `similarity` | Embeddings gegen das Register synthetischer Identitäten und gegen Dubletten | `screen(image) -> CheckResult` |
| `provenance` | Sichtbares Label, TrustMark, C2PA-Signatur; Verifikation | `seal(image, manifest)`, `verify(file)` |
| `review` | Zustandsautomat, Risikostaffelung, Vier-Augen, Stichproben, Eskalation | `transition(asset, action, reviewer)` |
| `dossier` | Compliance-Dossier pro Kampagne aus der Audit-Kette | `build(campaign_id) -> Dossier` |
| `regression` | Dauerhafte Regressionssuite | `run(engine, identity) -> Report` |
| `api`, `web` | REST-API und Oberfläche für Intake, Review, Delivery | |

Erläuterungen zu einzelnen Modulen:

- **Upload-Gate (`intake`):** Erlaubt sind Produktfotos und Markenassets. Ein Personen-Detektor lehnt jedes Bild mit Menschen ab. Bilder von Kindern gelangen nur als eigene, signierte Outputs ins System; ein Upload-Weg dafür existiert nicht.
- **Identität (`identity`):** Bootstrap wie im Handoff: Kandidaten rein aus Text → Screening → Vier-Augen-Auswahl → Datensatz per Multi-Referenz erweitern → LoRA nur auf signierten eigenen Outputs → im Register einfrieren. Neu: Eine Identität gehört zu genau einer Engine (`LIZENZPRUEFUNG.md` 3.3). Gespeichert werden Gewichts-Hashes, Trainingsdatensatz-Hashes, Seeds und Trainingskonfiguration.
- **Produkt-Treue (`product`):** Die Szene wird um die Produktmaske herum generiert, danach werden die Originalpixel zurückkopiert. Der Pixeltest verlangt innerhalb der Maske exakte Gleichheit; ein schmaler Übergangsrand wird getrennt bewertet.
- **Safety (`safety`):** Provisorium aus Nacktheits-Klassifikator und Altersschätzung mit strenger Schwelle, im Dossier als Provisorium ausgewiesen. Der Thorn-Adapter wird später hinter derselben Schnittstelle ergänzt. Die Lizenz der Altersschätzung wird vor dem Bau dieses Moduls geprüft.
- **Ähnlichkeit (`similarity`):** Abgleich nur gegen eigene synthetische Identitäten und frühere Outputs. Der Abgleich gegen reale Personen ist als Erweiterungspunkt vorgesehen, aber abgeschaltet (`LIZENZPRUEFUNG.md` 3.2). Start mit DINOv2; ein Gesichts-Embedding kommt erst dazu, wenn eine kommerziell nutzbare Lizenz vorliegt.
- **Kennzeichnung (`provenance`):** Reihenfolge fest: sichtbares Label → TrustMark → C2PA-Signatur. Danach wird die Datei nicht mehr verändert; jede Auslieferungsgröße wird einzeln versiegelt.
- **Review (`review`):** Zustände `geplant`, `generiert`, `blockiert`, `in_review`, `eskaliert`, `abgelehnt`, `freigegeben`, `versiegelt`, `ausgeliefert`. Jeder Wechsel ist ein Audit-Eintrag. Risikostufen bestimmen, ob ein Reviewer genügt, Vier-Augen nötig ist oder die Kategorie ausgeschlossen bleibt. Qwen-Outputs liegen eine Stufe höher als FLUX-Outputs.

## 4. Engine-Abstraktion

```python
class Engine(Protocol):
    def describe(self) -> EngineInfo: ...           # Name, Gewichts-Hashes, HF-Revision, Lizenzstand
    def capabilities(self) -> set[Capability]: ...  # TEXT2IMG, MULTI_REFERENCE, INPAINT,
                                                    # CONTROL_DEPTH, CONTROL_POSE, LORA
    def generate(self, request: GenerationRequest) -> GenerationResult: ...
```

- `GenerationRequest`: Prompt, Seed, Größe, Referenzbilder, Control-Bilder, Maske, LoRAs (als Register-ID mit Hash), engine-neutrale Parameter.
- `GenerationResult`: Bild und `Manifest` (Engine, Gewichts-Hashes, Revision, Scheduler, Bibliotheksversionen, Container-Digest, GPU-Typ, alle Eingaben als Hash).
- Die Planung fragt `capabilities()` ab und wählt die Engine: Standard ist FLUX.2 [klein] 4B; Jobs, die Posen- oder Tiefensteuerung brauchen, gehen an die Control-Engine.
- Adapter: `MockEngine` (deterministisch, CPU, für Tests und das erste End-to-End), `Flux2KleinEngine`, `QwenImageEngine`. Die echten Adapter laden diffusers erst beim Start, sodass alle anderen Tests ohne GPU laufen.
- Bit-genaue Reproduktion gilt nur für gleichen GPU-Typ, Treiber und Container; das Manifest hält genau diese Werte fest, und die Regressionssuite prüft sie.

## 5. Punkte aus Handoff-Abschnitt 6

| Punkt | Umsetzung |
|---|---|
| Bootstrap der Kind-Identität | Workflow in `identity`, jeder Schritt als Audit-Eintrag |
| Kaltstart | `jobs`: Queue statt synchroner Aufrufe, Warmhalten per Zeitplan |
| Qwen-Speichercheck | GPU-Test vor dem Bau des Qwen-Adapters, zusammen mit dem ControlNet-Test auf 2512 |
| Regressionssuite | eigenes Modul `regression`, wächst ab Schritt 0 mit; Pflichtlauf bei jedem Engine- oder LoRA-Wechsel |
| Review-Tooling | Zustände, Eskalation und Stichprobenregeln fest in `review` und in der Audit-Kette |

## 6. Reihenfolge der Umsetzung

Nach jedem Schritt: Tests grün, kurzer Bericht, Freigabe abwarten.

| Schritt | Inhalt | Läuft ohne GPU |
|---|---|---|
| 0 | **Minimales End-to-End:** `core`, `audit`, `MockEngine`, Produkt-Compositing mit Pixeltest, Safety-Gate als Attrappe, die standardmäßig blockiert, sichtbares Label, Dossier als JSON. Ein Befehl führt einen Brief bis zum versiegelten Bild mit Audit-Kette. | ja |
| 1 | `Flux2KleinEngine` mit Manifest und Reproduktionstest; Startskript für EU-GPU | Tests ja, echter Lauf nein |
| 2 | `provenance`: C2PA (zunächst Testzertifikat), TrustMark, Verifikation | ja |
| 3 | `intake` mit Upload-Gate und `safety`-Provisorium | weitgehend |
| 4 | `identity`: Register, Bootstrap-Workflow, LoRA-Trainingsjob | Tests ja, Training nein |
| 5 | `poses` und Control-Engine (GPU-Tests aus Abschnitt 5 zuerst) | Tests ja |
| 6 | `similarity`, `brand` | ja |
| 7 | `review`, `api`, `web` | ja |
| 8 | `dossier` (PDF), `regression` vollständig, `jobs` und Deployment auf OVHcloud | teilweise |

## 7. Was vor oder während der Umsetzung entschieden werden muss

Blockiert den Start nicht (Schritte 0 bis 2 sind davon unabhängig), muss aber vor dem jeweils genannten Schritt geklärt sein:

1. Schriftliche Klärung mit BFL bzw. Anwalt zur Reichweite der Developer Terms (`LIZENZPRUEFUNG.md` 3.1 und 3.3) – vor Schritt 4.
2. ~~Windel-, Bade- und ähnliche Kategorien in v1~~ – entschieden am 11.11.2026: in v1 ausgeschlossen, umgesetzt in der Brief-Prüfung (Schritt 0).
3. Thorn-Angebot und Lizenz für Gesichts-Embeddings: wer holt sie ein – vor Schritt 3 bzw. 6.
4. C2PA-Signaturzertifikat beschaffen – vor dem ersten echten Kundenbild.
5. Bria-Vertragsweg oder Bestätigung von FLUX.2 [klein] 4B plus Control-Engine – vor Schritt 1.
