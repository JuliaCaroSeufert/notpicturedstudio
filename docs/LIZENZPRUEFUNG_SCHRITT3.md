# Lizenzprüfung für Schritt 3: Upload-Gate und vorläufiges Safety-Gate (11.11.2026)

Gelesen wurden die Modellkarten und Lizenzdateien auf Hugging Face und GitHub, abgerufen am 11.11.2026. Technische Lektüre, keine Rechtsberatung.

## 1. Ergebnis in Kürze

- Für Gesichts- und Personenerkennung sowie für die Nacktheitserkennung gibt es kommerziell nutzbare Modelle.
- Für die Altersschätzung gibt es **kein** kommerziell nutzbares Modell mit belegter Qualität. Sie wird für v1 aber auch nicht gebraucht (Abschnitt 4).
- Keines der Modelle ist ein Erkenner für Missbrauchsdarstellungen. Das Safety-Gate bleibt ein Provisorium, bis Thorn angebunden ist.

## 2. Geprüfte Modelle

### Nacktheit und sexuelle Inhalte (Safety-Gate)

| Modell | Lizenz | Bewertung |
|---|---|---|
| `Freepik/nsfw_image_detector` (Revision `15b85477e4fd2000db76ae9aae0f89a72f95e2e3`) | MIT; Basis `timm/eva02_base…` ebenfalls MIT | **Empfohlen als Hauptmodell.** Vier Stufen (neutral, low, medium, high), sodass schon ab „low" blockiert werden kann. Laut Karte auf 100 000 Bildern trainiert und auch auf KI-generierten Bildern gemessen. Die Vergleichszahlen stammen vom Hersteller selbst. |
| `Marqo/nsfw-image-detection-384` (Revision `0c26ec22111b83f106d72a55f611ec35962bcb65`) | Apache 2.0 | **Empfohlen als zweite Meinung.** Zwei Klassen, klein und schnell. Trainingsdaten proprietär (220 000 Bilder, darunter reale Fotos und Zeichnungen). |
| `Falconsai/nsfw_image_detection` | Apache 2.0 | Nutzbar, aber laut Freepik-Vergleich schwach bei leichten und mittleren Fällen. Nicht empfohlen. |
| NudeNet v3 | AGPL-3.0, baut auf Ultralytics YOLOv8 (ebenfalls AGPL) | **Ausgeschieden.** AGPL würde verlangen, den eigenen Dienst offenzulegen, oder eine kostenpflichtige Lizenz. |
| `CompVis/stable-diffusion-safety-checker` | keine Lizenzangabe im Repo | Ausgeschieden (ungeklärt). |
| `google/shieldgemma-2-4b-it` | Gemma-Lizenz, Zugang nur nach manueller Freigabe | Nicht geprüft; Bedingungen nicht lesbar ohne Freigabe. Mögliche spätere Ergänzung. |

### Gesichter und Personen (Upload-Gate)

| Modell | Lizenz | Bewertung |
|---|---|---|
| YuNet (`opencv/face_detection_yunet`, OpenCV Zoo) | MIT | **Empfohlen für Gesichter.** Sehr klein, läuft ohne GPU. Erkennt laut Karte Gesichter von etwa 10 bis 300 Pixeln; Bilder müssen deshalb in mehreren Größen geprüft werden. |
| MediaPipe Face Detection | Apache 2.0 | Alternative zu YuNet. |
| RT-DETR v2 (`PekingU/rtdetr_v2_r50vd`, Revision `282494075698cab9faa1096ae26856890030c817`) | Apache 2.0, trainiert auf COCO | **Empfohlen für Personen.** |
| D-FINE, DETR, YOLOX | Apache 2.0 | Alternativen zu RT-DETR. |
| Ultralytics YOLO (v8 und neuer) | AGPL-3.0 | **Ausgeschieden**, auch alle darauf aufbauenden Gesichtsmodelle. |
| InsightFace (RetinaFace, SCRFD) | Modelle nicht kommerziell | Ausgeschieden (bekannt aus dem Handoff). |

### Altersschätzung

| Modell | Lizenz | Bewertung |
|---|---|---|
| MiVOLO v2 (`iitolstykh/mivolo_v2`) | CC BY-NC 4.0 | **Ausgeschieden** (nicht kommerziell). Damit ist der offene Punkt aus dem Handoff geklärt. |
| `nateraw/vit-age-classifier` | keine Lizenzangabe | Ausgeschieden (ungeklärt). |
| `dima806/facial_age_image_detection` | Apache 2.0 | Lizenz in Ordnung, aber Trainingsdaten und Qualität nicht dokumentiert. Nicht als Sicherheitsbaustein geeignet. |

## 3. Einschränkungen, die ins Dossier gehören

- Keines der empfohlenen Repos enthält eine Lizenzdatei für die Gewichte; die Lizenz ergibt sich aus dem Metadaten-Tag der Modellkarte (bei YuNet zusätzlich aus der MIT-Datei im Repo).
- Die Trainingsdaten aller Erkennungsmodelle sind proprietär oder nicht dokumentiert und enthalten reale Fotos. Das betrifft die Erkenner, nicht die erzeugten Bilder.
- Was genau die Stufe „low" bei Freepik umfasst (zum Beispiel Bademode oder Unterwäsche), steht nicht in der Karte und muss mit eigenen Testbildern gemessen werden.
- Die Modelle erkennen Nacktheit und sexuelle Inhalte allgemein. Keines ist auf Kinderschutz trainiert.

## 4. Vorschlag für den Aufbau

**Safety-Gate (jedes erzeugte Bild).** Beide Nacktheitsmodelle prüfen jedes Bild. Blockiert wird, wenn Freepik „low" oder höher meldet **oder** Marqo anschlägt **oder** ein Modell nicht läuft. Eine Altersschätzung ist dafür nicht nötig: Im System zeigt jedes erzeugte Bild ein Kind, also blockiert jedes Nacktheitssignal, unabhängig vom geschätzten Alter. Die Altersschätzung wäre nur nötig, um zwischen Erwachsenen und Kindern zu unterscheiden, und Erwachsene gibt es in v1 nicht.

**Upload-Gate (jede hochgeladene Datei, Videos als Einzelbilder).**

| Befund | Folge |
|---|---|
| Gesicht erkannt | abgelehnt |
| Person erkannt, kein Gesicht (zum Beispiel Rückenansicht, Körper ohne Kopf) | abgelehnt |
| Nur kleiner Personenbereich ohne Gesicht (typisch: Hand am Produkt) | menschliche Prüfung statt automatischer Annahme |
| Nichts erkannt | angenommen |
| Erkenner läuft nicht | abgelehnt |

Hände sind laut Entscheidung der Auftraggeberin erlaubt. Ein Personenerkenner kann eine Hand aber nicht sicher von einem angeschnittenen Körper unterscheiden, deshalb entscheidet in diesem Fall ein Mensch.

**Laufzeit.** Alle vier Modelle laufen ohne GPU. Sie brauchen die Bibliothek torch (groß, aber frei lizenziert) und OpenCV (Apache 2.0).

**Test in dieser Umgebung.** Die Gewichte liegen auf einem Hugging-Face-Downloadserver (`us.aws.cdn.hf.co`), der hier gesperrt ist. Ohne Freigabe dieses Hosts lassen sich die Gates nur gegen Ersatzmodelle testen, nicht mit den echten.
