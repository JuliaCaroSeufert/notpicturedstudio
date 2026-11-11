# Handoff: Stand nach Recherche-Session (11.11.2026)

Dieses Dokument überträgt den Stand der ersten Session in die nächste. Es wurde noch **kein Code** geschrieben. Nächster Schritt ist die Lizenzprüfung an den Originaltexten, danach der Architekturvorschlag – Code erst nach ausdrücklichem OK der Auftraggeberin.

## 1. Auftrag (Originalbrief, sinngemäß vollständig)

System für vollsynthetische Werbebilder mit Kindern und Babys für Marken.

**Vorgehen**
1. Erst recherchieren, nicht bauen: Bildmodelle, Fine-Tuning, Control/Compositing, Provenance, Safety-Klassifikatoren, EU-GPU-Hosting; Versionen und Lizenzen prüfen. Report + Stack-Empfehlung. Code erst nach OK.
2. Modulare Architektur vorschlagen, Generierungs-Modell bleibt austauschbar.
3. Modul für Modul umsetzen, mit Tests und Checkpoint nach jedem Modul. Start mit lauffähigem minimalem End-to-End.

**Module**
- Brief-gesteuerte Szenen- und Posengenerierung (ControlNet o. Ä.); wiederverwendbare Safe-Pose-Bibliothek für Säuglinge.
- Marken-exklusives synthetisches Kindmodell (LoRA/Fine-Tune) + Style-Lock, pro Marke gespeichert und versioniert (Seeds + Modellstand → exakt reproduzierbar).
- Produkt-Treue: echtes Produkt wird nie neu gezeichnet (Masked Inpainting + Depth-/Segmentation-Control).
- Markenidentität (Farben usw.) als Input und muss erhalten bleiben.
- Kinder/Babys bleiben über ein Shooting konsistent und werden für spätere Shootings gespeichert.
- Provenance: C2PA + (falls verfügbar) SynthID-kompatibles Wasserzeichen + sichtbares Label (EU AI Act Art. 50).
- Ähnlichkeits-Screening pro Output (Gesichts-Embedding / DINOv2) gegen reale/öffentliche Personen und Dubletten, geloggt.
- CSAM-Safety-Gate auf jedem Output; sicherheits-feingetunte Basis bevorzugt.
- Audit-Log mit unveränderlichem Zeitstempel pro Asset (Prompt, Modellversion, Checks, Freigabe).
- Automatisches Compliance-Dossier pro Kampagne.
- Workflow: Intake → Generieren → menschliche Review/QC (nach Risiko gestaffelt) → Delivery.

**Harte Regeln**
- Ausschließlich vollsynthetische Kinder. Uploads echter Kinderfotos technisch ablehnen. Keine echten Kinder in Trainingsdaten.
- Vor Modellfestlegung Lizenz/AGB prüfen, ob kommerzielle Erzeugung realistischer Minderjähriger erlaubt ist; auf **jedes** Gating hinweisen, bevor weitergebaut wird.
- Kommerziell saubere, lizenzsichere Basis, bevorzugt self-hostbar, EU-Hosting, DSGVO-nativ.

**Nicht-funktional:** Reproduzierbarkeit; EU-Datenresidenz; austauschbarer Engine-Layer; Tests pro Modul; saubere Secrets-/Konfig-Trennung; dokumentierte Pipeline; lauffähig auf serverless EU-GPU oder lokal.

**Sprache:** Die Auftraggeberin schreibt Deutsch; Antworten auf Deutsch.

## 2. Verlässlichkeit der Fakten

- In der ersten Session waren `bfl.ai` und `huggingface.co` gesperrt. Alle Lizenzaussagen stammen aus Suchtreffern, **nicht** aus den Originaltexten.
- Die Auftraggeberin hat ein externes Review eingeholt, das die Kernfakten bestätigt; dessen Quellen sind teils Spiegel und Drittseiten und wurden von uns nicht geprüft.
- **Erste Aufgabe der neuen Session:** die Originaltexte lesen (Abschnitt 7).

## 3. Modelle (Stand der Recherche)

| Modell | Lizenz | Bewertung |
|---|---|---|
| FLUX.2 [klein] 4B + Base 4B | Apache 2.0 | **Standard-Engine.** Safety-feingetunt, Trainingsdaten auf NSFW/CSAM gefiltert (laut Review mit IWF). LoRA-Training auf Base offiziell dokumentiert, Multi-Referenz-Editing nativ. Kein echtes ControlNet; Tiefe/Pose nur über Community-LoRAs (RefControl, Lizenz ungeprüft) bzw. Referenz-Latents. 9B-Varianten sind Non-Commercial. |
| Qwen-Image-2512 + Qwen-Image-Edit-2511 | Apache 2.0 | **Zweite Engine** (Control-Fallback). InstantX ControlNet Union (Depth/Pose/Canny) und InstantX Inpainting-ControlNet, beide Apache, diffusers-Pipelines. 20B; laut Sekundärquellen ca. 64 GB in BF16, 18–24 GB quantisiert. Kein Safety-Fine-Tuning dokumentiert. |
| Z-Image (Turbo/Base) | Apache 2.0 | Reserve. Fun ControlNet Union mit Inpaint-Modus. |
| FLUX 3 Image Klein (15.10.2026) | FLUX Kommunity License | Nur beobachten. Kommerziell frei nur unter 5 Mio. US$ Jahresumsatz inkl. verbundener Unternehmen; Filter-/Review-Pflicht; laut Review verlangt BFL für Betrieb innerhalb eines Produkts eine kommerzielle Lizenz. |
| Qwen-Image-2.1 | Qwen Research License | Ausgeschieden (nicht kommerziell). |
| Bria FIBO 2.0 | CC BY-NC 4.0 | Nur mit Bria-Vertrag kommerziell. Lizenzierte Trainingsdaten (Herstellerangabe) + Freistellung. Option, falls Datenherkunft Priorität bekommt. |
| Adobe Firefly | proprietär | Ausgeschieden als Engine (nicht self-hostbar, Custom Models ohne eigene Freistellung). |

## 4. Gatings und Risiken (alle der Auftraggeberin bereits genannt)

1. **BFL Usage Policy:** verbietet CSAM und Darstellungen Minderjähriger in sexueller, gewalttätiger, obszöner oder sonst schädlicher Art; neutrale Werbedarstellungen sind nicht verboten. Entscheidung: Policy **als bindend behandeln**, auch für eigene LoRAs; ins Dossier aufnehmen. Ob sie Apache-2.0-Gewichte rechtlich binden kann, ist Anwaltssache.
2. **BFL-API nicht nutzen:** Developer Terms verbieten Upload von Bildern von Personen unter 18. Nur Self-Hosting.
3. **CSAM-Klassifikator:** kein frei verfügbarer. Thorn Safer Predict ist laut Review self-hosted erhältlich (Enterprise-Vertrieb) → Angebot einholen. Bis dahin self-gehostetes Ersatz-Gate (Nacktheits-Klassifikator + Altersschätzung, im Zweifel blockieren), im Dossier als Provisorium mit geplanter Thorn-Migration ausweisen. Lizenz der Altersschätzung (z. B. MiVOLO) ungeprüft.
4. **Gesichts-Embeddings:** InsightFace-Modelle (buffalo, antelopev2) nicht kommerziell → Lizenz kaufen oder Alternative suchen (offen). DINOv2 Apache 2.0; DINOv3 eigene Meta-Lizenz, kommerziell erlaubt.
5. **Abgleich gegen reale Personen:** Referenzdatenbank echter Gesichter = biometrische Daten (DSGVO Art. 9). Unkritisch nur Abgleich gegen eigenes Register synthetischer Identitäten; alles weitere braucht Rechtsprüfung.
6. **SynthID:** für fremde self-gehostete Bilder nicht verfügbar → TrustMark (Adobe/CAI, MIT für Code und Modelle).
7. **C2PA:** c2pa-python 0.37.12, Spezifikation 2.4. Anerkanntes Signaturzertifikat muss beschafft werden; Trust-List-Details unverifiziert.
8. **Säuglings-Pose:** SMIL (eigene MPI-Lizenz, kommerziell ungeklärt), InfantNet CC BY-NC-ND → Safe-Pose-Bibliothek aus eigenen 3D-Rigs, kuratiert und menschlich freigegeben, als versionierte Control-Bilder.
9. **Echte Kinderfotos erkennen:** offene KI-Bild-Detektoren ca. 75 %, 35–42 % bei neuesten Generatoren → nicht per Klassifikator lösbar, sondern strukturell (Abschnitt 5).
10. **EU AI Act Art. 50:** gilt seit 2.8.2026, Code of Practice seit Juni 2026 final. Keine Schonfrist für neue Systeme: Kennzeichnung ab Launch. Anbieter- vs. Betreiber-Status offen (Anwalt).
11. **Strafrecht:** auch realistische synthetische Darstellungen können unter § 184b StGB fallen. Windel-/Bad-/Bademode-Kategorien: höchste Risikostufe mit Vier-Augen-Review oder Ausschluss in v1 (Anwalt).
12. **Trainingsdaten-Herkunft:** nur Bria macht belastbare Angaben; schwächt das Dossier bei FLUX/Qwen.

## 5. Vereinbarte Stack- und Designentscheidungen

- **Engines:** FLUX.2 [klein] 4B Standard, Qwen-Image-2512 zweiter Adapter hinter derselben Schnittstelle, Z-Image Reserve.
- **Pipeline:** diffusers in Produktion (ComfyUI nur Prototyping).
- **Produkt-Treue:** Szene um die Produktmaske generieren, Originalpixel zurückkopieren, automatischer Pixel-Vergleich innerhalb der Maske als Test.
- **Identität/Stil:** LoRA pro Marke und Kind + Referenzbilder; versioniert mit Gewichts-Hashes, Seeds, Container-Digest. Bit-genaue Reproduktion nur auf gleichem GPU-Typ/Treiber.
- **Upload-Regel:** Uploads dürfen keine Menschen enthalten (Personen-Detektor → Ablehnung). Kind-Referenzen und LoRA-Trainingsdaten nur mit eigener C2PA-Signatur und Audit-Log-Eintrag.
- **Kennzeichnung:** C2PA + TrustMark + sichtbares Label.
- **Audit-Log:** Append-only-Hash-Kette in Postgres, Objekte in S3 mit Object Lock, qualifizierte Zeitstempel (RFC 3161).
- **App:** FastAPI, Next.js, Postgres, S3-kompatibler Speicher.
- **Hosting:** OVHcloud AI Deploy für Inferenz (Scale-to-Zero; max. 10 Replicas, 4 GPUs pro App). Scaleway hat kein GPU-Serverless, nur minutengenaue Instanzen (L40S ca. 1,47 €/h, H100 ca. 2,87 €/h, Sekundärquellen) → für LoRA-Training.

## 6. In die Architektur aufzunehmen (aus dem Review, akzeptiert)

1. **Bootstrap der Kind-Identität:** Kandidaten rein aus Text mit dem Basismodell → Screening → Vier-Augen-Auswahl → Datensatz per Multi-Referenz erweitern → LoRA nur auf signierten eigenen Outputs → Identität im Register einfrieren.
2. **Kaltstart:** Job-Queue statt synchroner Aufrufe; Warmhalten zu Geschäftszeiten. Bei Qwen eher Minuten (Schätzung).
3. **Qwen-Speichercheck** vor Festlegung als zweite Engine (Engpass ist VRAM pro GPU, nicht die GPU-Anzahl; ggf. Quantisierung).
4. **Dauerhafte Regressionssuite** als eigenes Modul: festes Seed-/Prompt-Set, Produkt-Pixeltest, Identitäts-Konsistenz per Embedding, Safety-Pass-Raten – bei jedem Engine- oder LoRA-Wechsel.
5. **Review-Tooling:** Zustand „blockiert", Eskalationspfade und Stichprobenregeln als feste Zustände in der Audit-Kette.

## 7. Aufgaben der neuen Session (in dieser Reihenfolge)

1. Originaltexte lesen und Abschnitt 3/4 bestätigen oder korrigieren:
   - `https://bfl.ai/legal/usage-policy` (Minderjährige; Geltung für Open Weights und Derivate)
   - `https://bfl.ai/legal/developer-terms-of-service` (Definition „FLUX AI Models", Upload-Verbot unter 18)
   - `https://huggingface.co/black-forest-labs/FLUX.2-klein-4B` und `.../FLUX.2-klein-base-4B` (Lizenz, Gating, Safety-Abschnitt)
   - `https://huggingface.co/Qwen/Qwen-Image-2512`, `.../Qwen-Image-Edit-2511` (Lizenzdatei)
   - `https://huggingface.co/InstantX/Qwen-Image-ControlNet-Union`, `.../Qwen-Image-ControlNet-Inpainting`
   - `https://huggingface.co/thedeoxen/refcontrol-FLUX.2-klein-4B-reference-depth-lora` (Lizenz)
   - `https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md` (nur zur Einordnung)
2. Abweichungen der Auftraggeberin melden (jedes Gating ausdrücklich).
3. Architekturvorschlag vorlegen (Module, Schnittstellen, Engine-Abstraktion, Punkte aus Abschnitt 6, Reihenfolge der Umsetzung mit minimalem End-to-End zuerst).
4. Auf OK warten, dann Modul für Modul mit Tests und Checkpoint.

## 8. Offene Fragen an die Auftraggeberin

- Sind Windel-, Bade- oder ähnliche Produktkategorien in v1 dabei?
- Liegt der Jahresumsatz unter 5 Mio. US$? (nur für FLUX 3 Image Klein relevant)
- Bria-Vertragsweg wegen Datenherkunft/Freistellung gewünscht, oder bleibt es bei FLUX.2 klein 4B + Qwen? (Review und bisherige Rückmeldung sprechen für Letzteres, ausdrückliches OK steht aus.)
- Thorn-Angebot und InsightFace-Lizenz: wer holt sie ein?

## 9. Umgebung

- Cloud-Umgebung **„notpicturedstudio"** ist angelegt und erlaubt `huggingface.co`, `bfl.ai`, `docs.bfl.ml`, `help.bfl.ai`. Die neue Session muss in dieser Umgebung gestartet werden.
- Für spätere Modell-Downloads werden voraussichtlich weitere Hugging-Face-Download-Hosts nötig; erst bei konkretem Bedarf ergänzen.
- Die Cloud-Container haben keine GPU: Pipeline-Code hier nur mit Mocks/CPU-Tests, echte Läufe auf EU-GPU.
- Entwicklungsbranch: `claude/optimistic-meitner-cjeq9a`.
