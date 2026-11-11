# Architekturvorschlag (Entwurf, 11.11.2026)

**Status: vorläufig.** Die Lizenzprüfung an den Originaltexten (HANDOFF Abschnitt 7.1) konnte noch nicht stattfinden, weil die Session ohne Zugriff auf `bfl.ai` und `huggingface.co` lief. Alles, was von einer konkreten Engine abhängt, steht deshalb unter Vorbehalt und ist mit **[V]** markiert. Der Entwurf ist so gebaut, dass eine Korrektur der Lizenzlage nur einen Engine-Adapter betrifft, nicht die übrigen Module. Es wurde kein Code geschrieben.

## 1. Leitprinzipien

1. **Fail closed.** Jeder Check, der nicht läuft oder kein eindeutiges Ergebnis liefert, blockiert das Asset. Kein Asset erreicht Review oder Delivery ohne vollständige Check-Kette.
2. **Engine ist ein Adapter.** Kein Modul außerhalb von `engine/` kennt FLUX, Qwen oder diffusers.
3. **Alles ist ein Audit-Ereignis.** Zustandswechsel eines Assets existieren nur als Eintrag in der Hash-Kette; der aktuelle Zustand wird daraus abgeleitet.
4. **Keine Menschen als Input.** Uploads mit Personen werden abgelehnt; Kind-Referenzen kommen ausschließlich aus dem eigenen Register signierter synthetischer Outputs.
5. **Reproduzierbarkeit über Manifeste.** Jedes Asset trägt ein Manifest (Engine-ID, Gewichts-Hashes, LoRA-Versionen, Seed, Parameter, Container-Digest, GPU-Typ), aus dem es neu erzeugt werden kann.

## 2. Module

| Modul | Aufgabe | Wichtigste Schnittstelle |
|---|---|---|
| `core` | Datentypen (Brief, Marke, Identität, Asset, Manifest), Konfiguration, Secrets-Trennung | Pydantic-Modelle; Konfig aus Umgebung, Secrets nie im Repo |
| `engine` | Bildgenerierung hinter einheitlicher Schnittstelle | `Engine.capabilities()`, `Engine.generate(request) -> result` |
| `intake` | Brief, Markenprofil, Produktbild + Maske, Upload-Gate (Personen-Detektor → Ablehnung) | `validate_upload(file) -> Accepted \| Rejected(reason)` |
| `poses` | Safe-Pose-Bibliothek: versionierte Control-Bilder aus eigenen 3D-Rigs, jede Pose menschlich freigegeben | `get_pose(id, version) -> ControlImage` (nur freigegebene) |
| `identity` | Register synthetischer Kinder pro Marke; Bootstrap; LoRA-Versionen | `freeze_identity(...)`, `resolve(identity_id, version)` |
| `product` | Produkt-Treue: Generierung um die Maske, Originalpixel zurückkopieren | `composite(scene, product, mask)`, `verify_pixels(...)` |
| `brand` | Markenfarben und Style-Lock prüfen | `check_palette(image, profile) -> Report` |
| `safety` | CSAM-/Safety-Gate auf jedem Output | `SafetyGate.check(image) -> Pass \| Block(reason)` |
| `similarity` | Ähnlichkeit gegen eigenes Register und Dubletten | `screen(image) -> Report` |
| `provenance` | C2PA-Manifest, TrustMark-Wasserzeichen, sichtbares Label | `label(image, manifest) -> LabelledAsset` |
| `audit` | Append-only-Hash-Kette, RFC-3161-Zeitstempel, Object Lock | `append(event) -> entry`, `verify_chain()` |
| `review` | Risikostaffelung, Zustände, Vier-Augen-Regeln, Stichproben | Zustandsmaschine (Abschnitt 4) |
| `dossier` | Compliance-Dossier pro Kampagne aus der Audit-Kette | `build(campaign_id) -> PDF + JSON` |
| `delivery` | Auslieferung nur freigegebener, gekennzeichneter Assets | `deliver(asset_id)` prüft Kette vor Ausgabe |
| `regression` | Festes Seed-/Prompt-Set, läuft bei jedem Engine-/LoRA-Wechsel | `run(suite, engine) -> Report` |
| `orchestrator` | Job-Queue, Worker, Kaltstart-Handling | Jobs asynchron; API liefert Job-ID |
| `api` / `ui` | FastAPI und Next.js (Intake, Review, Delivery) | REST, rollenbasiert |

## 3. Engine-Abstraktion

```python
class Capabilities(BaseModel):
    text_to_image: bool
    multi_reference: bool      # Referenzbilder als Konditionierung
    inpaint: bool              # maskierte Generierung
    control: set[ControlKind]  # depth, pose, canny
    lora: bool

class GenerationRequest(BaseModel):
    prompt: str
    seed: int
    size: tuple[int, int]
    references: list[ImageRef] = []
    mask: ImageRef | None = None
    controls: list[ControlInput] = []
    loras: list[LoraRef] = []      # Gewichts-Hash + Stärke
    params: dict                   # Engine-spezifisch, wird ins Manifest übernommen

class Engine(Protocol):
    id: str                        # z. B. "flux2-klein-4b@<gewichts-hash>"
    def capabilities(self) -> Capabilities: ...
    def generate(self, request: GenerationRequest) -> GenerationResult: ...
```

- Der Orchestrator wählt die Engine über Capabilities: braucht ein Job Pose-Control, das die Standard-Engine nicht hat, geht er an die zweite Engine. Die Wahl wird geloggt.
- Adapter: `MockEngine` (CPU, deterministisch, für Tests und das minimale End-to-End), `Flux2KleinEngine` **[V]**, `QwenImageEngine` **[V]**, Z-Image als Reserve **[V]**.
- Ein Identitäts-LoRA gehört zu genau einer Engine. Ein Engine-Wechsel heißt: Identität aus den eingefrorenen Referenzbildern neu trainieren, Regressionssuite fahren, neue Version im Register.

## 4. Ablauf und Zustände eines Assets

```
Intake ─► Job ─► Generierung ─► Produkt-Composite ─► Pixeltest
       ─► Safety-Gate ─► Ähnlichkeits-Screening ─► Markencheck
       ─► Kennzeichnung (C2PA + TrustMark + Label) ─► Review ─► Delivery
```

Zustände (jeder Wechsel ein Audit-Eintrag): `angefordert` → `generiert` → `geprüft` → `gekennzeichnet` → `in_review` → `freigegeben` → `ausgeliefert`. Nebenpfade: `blockiert` (Safety oder Screening), `abgelehnt` (Review), `eskaliert` (Review → zweite Person oder Recht).

Review-Stufen:

| Stufe | Beispiel | Regel |
|---|---|---|
| niedrig | Produkt ohne Kind, Hintergründe | Stichprobe |
| mittel | bekleidetes Kind, freigegebene Pose und Identität | jedes Asset, eine Person |
| hoch | Säuglinge, neue Identität, neue Pose | jedes Asset, Vier-Augen |
| ausgeschlossen (v1-Vorschlag) | Windel, Bad, Bademode | technisch gesperrt, bis Rechtsprüfung vorliegt |

## 5. Punkte aus HANDOFF Abschnitt 6

1. **Bootstrap der Kind-Identität** (`identity`): Kandidaten aus Text → Safety-Gate + Screening → Vier-Augen-Auswahl → Datensatz per Multi-Referenz erweitern → LoRA nur auf C2PA-signierten eigenen Outputs (Trainer prüft Signatur jeder Datei und bricht sonst ab) → Einfrieren im Register.
2. **Kaltstart** (`orchestrator`): Postgres-basierte Queue, Worker auf OVHcloud AI Deploy, Warmhalten zu konfigurierten Geschäftszeiten, Status per Polling.
3. **Qwen-Speichercheck**: eigener Messlauf vor der Festlegung (VRAM in BF16 und quantisiert, Kaltstartzeit), Ergebnis im Repo dokumentiert **[V]**.
4. **Regressionssuite** (`regression`): Produkt-Pixeltest, Identitäts-Konsistenz per Embedding, Safety-Pass-Raten, Farbtreue; Schwellen versioniert; Pflichtlauf vor jeder Freischaltung einer Engine- oder LoRA-Version.
5. **Review-Tooling** (`review`): `blockiert`, `eskaliert` und Stichprobenregeln als feste Zustände in der Audit-Kette (Abschnitt 4).

## 6. Reihenfolge der Umsetzung

Jedes Modul endet mit Tests und einem Checkpoint zur Abnahme. Im Cloud-Container laufen nur CPU-Tests mit `MockEngine`; echte Läufe auf EU-GPU.

| Schritt | Inhalt | Abnahme |
|---|---|---|
| M0 | **Minimales End-to-End** mit `MockEngine`: Brief → Bild → Produkt-Composite → Platzhalter-Gate (blockiert standardmäßig, nur im Test geöffnet) → Audit-Eintrag → sichtbares Label → Datei | ein Befehl erzeugt ein Asset mit vollständiger Kette |
| M1 | `audit`: Hash-Kette, Verifikation, Zeitstempel-Schnittstelle; Konfig/Secrets | Manipulation an einem Eintrag wird erkannt |
| M2 | `safety` (provisorisches Gate) + Upload-Gate | Testbilder mit Personen werden abgelehnt; Gate-Ausfall blockiert |
| M3 | `engine`: erster echter Adapter, Manifest, Reproduktionstest **[V]** | gleicher Seed → gleiches Bild auf gleicher GPU |
| M4 | `product` + `brand` | Pixel in der Maske identisch zum Original |
| M5 | `provenance` | C2PA validiert, Wasserzeichen wird nach JPEG-Kompression gelesen |
| M6 | `identity`: Register, Bootstrap, LoRA-Training | Identität über ein Shooting konsistent (Embedding-Schwelle) |
| M7 | `poses` + Control über zweite Engine, Speichercheck **[V]** | freigegebene Pose wird eingehalten |
| M8 | `similarity` | Dubletten und Register-Treffer werden geloggt |
| M9 | `review` + `api`/`ui` + `orchestrator` | Zustandsmaschine lässt keine Abkürzung zu |
| M10 | `dossier` + `delivery` | Dossier vollständig aus der Kette erzeugt |
| M11 | `regression` als dauerhafte Suite (wächst ab M3 mit) | Lauf bei Engine-Wechsel blockiert bei Schwellenbruch |

Das Safety-Gate (M2) liegt bewusst **vor** dem ersten echten Engine-Lauf (M3): Es wird kein Bild eines Kindes erzeugt, bevor Gate und Audit-Log existieren.

## 7. Offene Entscheidungen (zusätzlich zu HANDOFF Abschnitt 8)

1. **Umgang mit blockierten Outputs:** Vorschlag: Pixel sofort löschen, nur Hash, Manifest und Blockgrund im Audit-Log behalten. Ob und wie lange ein blockiertes Bild gespeichert werden darf oder gemeldet werden muss, ist eine Anwaltsfrage.
2. **Gesichts-Embedding:** Bis die InsightFace-Lizenz oder eine Alternative geklärt ist, startet `similarity` nur mit DINOv2; Identitäts-Konsistenz ist damit schwächer abgesichert.
3. **Sperrkategorien in v1** (Windel, Bad, Bademode): der Entwurf geht von Ausschluss aus.
4. **Zweite Engine:** Festlegung auf Qwen erst nach Speichercheck und Lizenzprüfung.
