# Lizenzprüfung an den Originaltexten (11.11.2026)

Ergebnis von Aufgabe 1 und 2 aus `HANDOFF.md`, Abschnitt 7. Alle Aussagen stammen aus den Originalseiten, abgerufen am 11.11.2026. Das ist eine technische Lektüre, keine Rechtsberatung; die mit **Anwalt** markierten Punkte brauchen eine juristische Einschätzung.

## 1. Gelesene Quellen

| Quelle | Stand |
|---|---|
| `bfl.ai/legal/usage-policy` | Last Revised 4.8.2026 |
| `bfl.ai/legal/developer-terms-of-service` (Nicht-EU, Black Forest Labs Inc.) | Last Revised 4.8.2026 |
| `bfl.ai/legal/eu-developer-terms-of-service` (EU, BFL GmbH Freiburg) | Last Revised 26.8.2026 |
| `bfl.ai/legal/self-hosted-commercial-license-terms` | Last Revised 4.8.2026 |
| `bfl.ai/legal/non-commercial-license-terms` (FLUX [dev] NC v2.0) | Last Revised 25.11.2025 |
| `black-forest-labs/FLUX.2-klein-4B` (Karte + `LICENSE.md`) | Revision `e7b7dc27f91deacad38e78976d1f2b499d76a294` |
| `black-forest-labs/FLUX.2-klein-base-4B` (Karte + `LICENSE.md`) | Revision `a3b4f4849157f664bdbc776fd7453c2783562f4d` |
| `Qwen/Qwen-Image-2512` | Revision `25468b98e3276ca6700de15c6628e51b7de54a26` |
| `Qwen/Qwen-Image-Edit-2511` | Revision `6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9` |
| `InstantX/Qwen-Image-ControlNet-Union` | Revision `b13036f066d6dee7c20513e263d3d673055e9de8` |
| `InstantX/Qwen-Image-ControlNet-Inpainting` | Revision `5387c47add7b3a9b1d6341b75a251d235408c670` |
| `thedeoxen/refcontrol-FLUX.2-klein-4B-reference-depth-lora` | Revision `0ae1ef7f9acc4e55ec2237360943c3c3032d3583` |
| `black-forest-labs/flux-3-image-klein` | **nicht lesbar** (siehe 3.8) |

Die Revisionen werden später in der Konfiguration fest gepinnt, damit Lizenzstand und Gewichte zusammen dokumentiert sind.

## 2. Bestätigt

- **FLUX.2 [klein] 4B und Base 4B sind Apache 2.0.** `LICENSE.md` ist in beiden Repos der unveränderte Apache-Text ohne Zusätze. Kein Gating auf Hugging Face. Die Karte nennt ausdrücklich kommerzielle Nutzung; die 9B-Varianten sind Non-Commercial.
- **Safety-Fine-Tuning und Datenfilterung** stehen so in der Modellkarte: Trainingsdaten auf NSFW und bekanntes CSAM gefiltert (zusammen mit der IWF), mehrere Runden gezieltes Fine-Tuning gegen CSAM/NCII für Text-zu-Bild und Bild-zu-Bild, externe Evaluation vor Freigabe.
- **LoRA-Training auf Base 4B** ist der vorgesehene Weg („Ideal for fine-tuning, LoRA training"). Multi-Referenz-Editing ist nativ. Base: 50 Schritte, Guidance 4.0; destilliert: 4 Schritte, Guidance 1.0.
- **Usage Policy, Minderjährige:** verboten sind CSAM sowie „any content depicting minors in any sexual, violent, obscene, or otherwise harmful manner". Neutrale Werbedarstellungen sind nicht erfasst.
- **Usage Policy, Geltungsanspruch:** Sie beansprucht Geltung für jeden, der „any FLUX AI Models, any adaptations for, or modified versions" nutzt, und ausdrücklich auch für Derivate. Eigene LoRAs wären also erfasst. Die Entscheidung, die Policy als bindend zu behandeln, bleibt richtig.
- **Upload-Verbot unter 18:** Ziffer 6(k) der Developer Terms, in der EU-Fassung wortgleich: kein Upload von „images, videos or personal data … relating to individuals under the age of 18".
- **Qwen-Image-2512 und Qwen-Image-Edit-2511:** Apache 2.0, kein Gating. Keine Safety-Angaben, keine Nutzungsrichtlinie.
- **InstantX ControlNet Union und Inpainting:** als Apache 2.0 getaggt, kein Gating, diffusers-Pipelines vorhanden.

## 3. Abweichungen und neue Gatings

### 3.1 Reichweite der BFL Developer Terms auf selbst gehostete Apache-Gewichte ist unklar (wichtigster Punkt)

Die Modellkarte von klein 4B sagt, für „commercial open-weight model users" gälten Developer Terms, Self-Hosted Commercial License Terms und Usage Policy. Gleichzeitig steht dort: „Nothing contained in this Model Card should be interpreted as … a restriction or modification to the license". Die Self-Hosted Terms selbst decken nur Modelle der Marke „FLUX [dev]" ab, also nicht klein 4B. Die Developer Terms binden laut eigenem Text, wer die „FLUX Services" nutzt oder ein Entwicklerkonto anlegt.

Warum das zählt: Ziffer 6(k) verbietet Uploads „to the FLUX Services **or FLUX AI Models**", und „FLUX AI Models" schließt Derivate ein. Unser Design speist Referenzbilder synthetischer Kinder in das Modell ein (Multi-Referenz, LoRA-Training). Der Wortlaut spricht von „individuals", also realen Personen; synthetische Kinder sind das nicht. Sicher ist diese Lesart aber nicht.

Empfehlung:
- Kein BFL-Entwicklerkonto anlegen, keine BFL-Dienste nutzen, Gewichte nur von Hugging Face beziehen (verschärft die bestehende Regel „BFL-API nicht nutzen").
- Schriftliche Bestätigung bei BFL einholen, dass (a) für selbst gehostetes klein 4B nur Apache 2.0 plus Usage Policy gilt und (b) Ziffer 6(k) vollsynthetische Kinderdarstellungen nicht erfasst. **Anwalt.**

### 3.2 „Biometric processing" ist in der Usage Policy verboten

Die Policy untersagt die Nutzung der Modelle „including Output" für „inferring sensitive information about a person or biometric processing purposes". Die Developer Terms (Ziffer 10) verbieten zusätzlich, mit einem FLUX-Modell ein Gesichtserkennungssystem aufzubauen oder zu erweitern.

Betroffen ist das Ähnlichkeits-Screening per Gesichts-Embedding. Der Abgleich synthetischer Gesichter untereinander (eigenes Register, Dubletten) betrifft keine natürlichen Personen und ist vertretbar. Ein Abgleich gegen reale oder öffentliche Personen wäre biometrische Verarbeitung und stößt jetzt an zwei Grenzen: DSGVO Art. 9 (bekannt) und die BFL-Policy (neu). Er bleibt in der Architektur abgeschaltet, bis er rechtlich geklärt ist. **Anwalt.**

### 3.3 Outputs dürfen nicht zum Training „anderer" Modelle dienen (falls die Developer Terms gelten)

Ziffer 6(c): keine Nutzung von Outputs, um ein konkurrierendes Produkt zu entwickeln, „including using any Task or Output to train, distill or fine tune any other AI models". Apache 2.0 selbst kennt keine solche Einschränkung.

Folge für das Design: Eine Kind-Identität, die mit FLUX erzeugt wurde, sollte nicht ohne Klärung als Trainingsmaterial für ein Qwen-LoRA dienen. Bis zur Klärung wird jede Identität **pro Engine getrennt** aufgebaut; der Engine-Wechsel für eine bestehende Identität ist damit kein reiner Konfigurationsschritt. Das LoRA-Training auf FLUX-eigenen Outputs für FLUX selbst ist davon nach dem Wortlaut nicht betroffen. **Anwalt** (hängt an 3.1).

### 3.4 RefControl-LoRA: für die Produktion nicht geeignet

Als Apache 2.0 getaggt, aber: Einzelautor, keine Lizenzdatei, keine Angaben zu Trainingsdaten außer „primarily trained on humans", nur ein ComfyUI-Workflow. Die Herkunft der Trainingsbilder (reale Personen, möglicherweise Minderjährige) ist nicht prüfbar, und das verträgt sich nicht mit dem Dossier-Anspruch.

Empfehlung: nicht einsetzen. Posen- und Tiefensteuerung läuft über die Qwen-Engine; falls sie auf FLUX gebraucht wird, trainieren wir ein eigenes Control-LoRA auf Renderings der eigenen 3D-Rigs.

### 3.5 InstantX-ControlNets sind für das ursprüngliche Qwen-Image trainiert, nicht für 2512

Beide Karten nennen als Basis `Qwen/Qwen-Image` (August 2025). Ob sie mit 2512 sauber arbeiten, steht nirgends und muss auf einer GPU getestet werden, zusammen mit dem ohnehin geplanten Speichercheck. Fällt der Test schlecht aus, ist die zweite Engine das ursprüngliche Qwen-Image oder Z-Image.

Außerdem: Das Inpainting-ControlNet wurde laut Karte auf „10M high-quality general and human images" unbekannter Herkunft trainiert. Die Union-Karte endet mit „All copyright reserved", was dem Apache-Tag widerspricht; eine Lizenzdatei fehlt in beiden Repos. Geringes Risiko, gehört aber ins Dossier.

### 3.6 Qwen: Lizenz nur als Tag, keinerlei Safety-Dokumentation

In den Hugging-Face-Repos liegt keine Lizenzdatei; die Lizenz ergibt sich aus dem Metadaten-Tag, einem Satz in der Edit-2511-Karte und der Apache-Datei im GitHub-Repo `QwenLM/Qwen-Image`. Das reicht, sollte aber als Kopie im Dossier liegen. Es gibt weder Safety-Fine-Tuning noch Nutzungsregeln. Für Qwen-Outputs ist das eigene Safety-Gate also die einzige Schutzschicht; ich schlage vor, sie in der Review-Staffelung eine Risikostufe höher einzuordnen als FLUX-Outputs.

### 3.7 Kleinere Punkte aus der Usage Policy

- Provenance-Signale (C2PA, Wasserzeichen) dürfen nicht entfernt oder verändert werden. Passt zum Design; die Nachbearbeitung (Produktpixel zurückkopieren, Skalieren, Export) muss so gebaut sein, dass Signatur und Wasserzeichen als letzter Schritt gesetzt werden und danach nichts mehr am Bild geändert wird.
- Keine täuschende Darstellung von Personen ohne angemessene Kennzeichnung. Stützt das sichtbare Label.
- EU-Zusatz: kein Ausnutzen von Schwächen aufgrund des Alters. Betrifft die Kampagneninhalte (Werbung, die sich an Kinder richtet), nicht die Technik. **Anwalt**, falls solche Kampagnen geplant sind.
- Menschliche Prüfung der Outputs liegt ausdrücklich in unserer Verantwortung. Passt zum Review-Workflow.
- Inhaltsfilter sind für klein 4B nur empfohlen, nicht vorgeschrieben. Wir setzen sie trotzdem durchgehend ein.

### 3.8 FLUX 3 Image Klein: nicht prüfbar

Das Repo ist zugangsbeschränkt (Gating „auto", Lizenzname `flux-kommunity-license`); `LICENSE.md` ist ohne angemeldetes Hugging-Face-Konto nicht abrufbar. Die Aussagen im Handoff (Umsatzgrenze 5 Mio. US$, Filterpflicht) bleiben **unbestätigt**. Da das Modell nur beobachtet wird, blockiert das nichts.

### 3.9 Texte können sich ändern

Usage Policy und Terms wurden im August 2026 zuletzt geändert und gelten laut eigenem Text bei Weiternutzung als akzeptiert. Das Dossier sollte pro Kampagne den Stand (Datum und Hash) der geltenden Texte festhalten, und die Texte sollten regelmäßig auf Änderungen geprüft werden.

## 4. Auswirkungen auf den Stack

| Entscheidung aus dem Handoff | Status |
|---|---|
| FLUX.2 [klein] 4B als Standard-Engine | bestätigt |
| Usage Policy als bindend behandeln | bestätigt |
| BFL-API nicht nutzen | bestätigt, erweitert auf „kein BFL-Konto" (3.1) |
| Qwen-Image-2512 als zweite Engine | vorläufig; GPU-Test auf ControlNet-Kompatibilität und Speicher offen (3.5) |
| RefControl-LoRAs für Tiefe/Pose auf FLUX | gestrichen (3.4) |
| Abgleich gegen reale Personen | bleibt abgeschaltet (3.2) |
| Identität per LoRA, Engine austauschbar | Identität wird pro Engine getrennt aufgebaut (3.3) |
