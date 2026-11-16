# GPU einrichten (OVHcloud, Frankreich)

Ziel: ein gemieteter GPU-Rechner in der EU, auf dem Claude Code direkt läuft. Du arbeitest danach wie gewohnt im Chat weiter, nur dass die Session auf diesem Rechner sitzt und das echte Bildmodell starten kann. Die bisherige Cloud-Session kann fremde Rechner nicht erreichen, deshalb dieser Weg.

Dauer: etwa 30 bis 45 Minuten beim ersten Mal. Du brauchst ein Terminal auf deinem Computer (Mac: Programm „Terminal"; Windows: „PowerShell").

**Nicht an der Quelle geprüft:** Die OVHcloud-Website ist aus der Entwicklungsumgebung nicht erreichbar. Menüpfade stammen aus Suchtreffern zur offiziellen OVHcloud-Anleitung, Preise von Vergleichsseiten. Die Konsole zeigt dir den tatsächlichen Preis an, bevor du etwas bestätigst. Die offizielle Anleitung heißt „GPU Instanzen einrichten" und steht unter `docs.ovhcloud.com/de/guides/public-cloud/compute/deploy-a-gpu-instance`.

## Was es kostet

- Abgerechnet wird nach Laufzeit, wenn du beim Anlegen „stündlich" wählst. Vergleichsseiten nennen für eine **L4** (24 GB) rund 1,00 $ pro Stunde und für eine **L40S** (48 GB) rund 1,80 $ pro Stunde (Stand November 2026).
- Wichtig: Bei OVHcloud kostet vermutlich auch ein nur ausgeschalteter Rechner weiter. Verlässlich endet die Abrechnung erst, wenn du ihn löschst (Schritt 8).
- OVHcloud bewirbt ein Startguthaben für das erste Public-Cloud-Projekt. Ob es für dich gilt, zeigt die Konsole.

## 1. Konto und Projekt anlegen

1. Auf `ovhcloud.com` ein Kundenkonto anlegen und Zahlungsmittel hinterlegen.
2. Im Kundencenter oben auf „Public Cloud" gehen und ein Projekt anlegen, zum Beispiel mit dem Namen `notpicturedstudio`.
3. Falls in Schritt 3 keine GPU-Modelle wählbar sind oder eine Meldung zum Kontingent erscheint: im Projekt unter „Quota and Regions" (bzw. „Kontingente und Regionen") eine Erhöhung beantragen oder ein Support-Ticket öffnen.

## 2. Zugangsschlüssel erzeugen

Auf deinem Computer im Terminal:

```bash
ssh-keygen -t ed25519 -C "notpicturedstudio"
```

Dreimal Enter drücken (Standardort, kein Passwort nötig; ein Passwort ist sicherer). Dann den öffentlichen Teil anzeigen:

```bash
cat ~/.ssh/id_ed25519.pub
```

Die ausgegebene Zeile kopieren. Du fügst sie in Schritt 3 beim Anlegen des Rechners ein (oder vorab im Projekt unter „SSH Keys"). Nur diese `.pub`-Zeile weitergeben, niemals die Datei ohne `.pub`.

## 3. Rechner anlegen

Im Projekt: „Compute" → „Instances" → „Create an instance" (bzw. „Instanz erstellen").

| Einstellung | Wert |
|---|---|
| Modell | Reiter „GPU" bzw. „Cloud GPU": **L4-90** (eine L4 mit 24 GB). Reicht für das Bildmodell; falls das Training später zu wenig Speicher hat, wechseln wir auf **L40S-90** |
| Region | Gravelines (GRA), Frankreich. Laut OVHcloud sind die meisten GPUs in GRA7, GRA9 und GRA11 verfügbar; nimm die GRA-Region, in der L4 angeboten wird |
| Image | Ubuntu 24.04 |
| SSH-Schlüssel | die Zeile aus Schritt 2 einfügen |
| Netzwerk | öffentlicher Modus („Public mode") |
| Abrechnung | **stündlich** |
| Name | z. B. `nps-gpu` |

Anlegen und warten, bis der Status „Aktiv" zeigt. Die öffentliche IPv4-Adresse notieren.

## 4. Verbinden

Bei Ubuntu-Images von OVHcloud heißt der Benutzer `ubuntu`:

```bash
ssh ubuntu@DEINE-IP-ADRESSE
```

Die Rückfrage beim ersten Mal mit `yes` bestätigen. Ab hier laufen alle Befehle auf dem GPU-Rechner.

## 5. Werkzeuge und Grafiktreiber installieren

Anders als bei manchen Anbietern ist der NVIDIA-Treiber bei OVHcloud nicht vorinstalliert.

```bash
sudo apt-get update && sudo apt-get install -y git gh python3-venv tmux ubuntu-drivers-common
```

```bash
sudo ubuntu-drivers install
```

```bash
sudo reboot
```

Die Verbindung bricht dabei ab. Nach etwa einer Minute neu verbinden (Schritt 4) und prüfen, ob die GPU da ist; es sollte eine Tabelle mit „L4" erscheinen:

```bash
nvidia-smi
```

Falls `nvidia-smi` einen Fehler zeigt: trotzdem weitermachen und es der Session in Schritt 7 als Erstes sagen; sie kann den Treiber selbst einrichten.

Claude Code installieren:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Falls danach der Befehl `claude` nicht gefunden wird: einmal `exit` eingeben, neu verbinden und erneut versuchen. Die offizielle Anleitung steht unter `code.claude.com/docs`.

## 6. Projekt holen

Bei GitHub anmelden (der Befehl zeigt einen Code und eine Adresse, die du im Browser auf deinem Computer öffnest):

```bash
gh auth login
```

Auswahl: „GitHub.com", „HTTPS", „Login with a web browser".

```bash
gh repo clone JuliaCaroSeufert/notpicturedstudio
```

```bash
cd notpicturedstudio && git checkout claude/hopeful-clarke-eyxge1
```

## 7. Claude Code starten

Damit die Session weiterläuft, wenn deine Verbindung abbricht, zuerst:

```bash
tmux new -s nps
```

Dann im Projektordner:

```bash
claude
```

Beim ersten Start meldest du dich über einen Link im Browser mit deinem Claude-Konto an. Danach als erste Nachricht:

> Lies docs/HANDOFF.md und mach bei „Aufgaben für die GPU-Session" weiter. Antworte auf Deutsch und duze mich.

Wenn du lieber wie bisher in der App statt im Terminal schreiben willst, starte stattdessen:

```bash
claude remote-control
```

Der Rechner erscheint dann in der Claude-Code-App, und du führst die Unterhaltung von dort. (Nach einem Verbindungsabbruch kommst du mit `ssh ubuntu@DEINE-IP-ADRESSE` und dann `tmux attach -t nps` zurück.)

## 8. Nach der Arbeit: löschen

1. In der Session darum bitten, alles zu committen und zu pushen. Was nicht auf GitHub liegt, ist nach dem Löschen des Rechners weg.
2. Im Kundencenter unter „Instances" den Rechner **löschen**. Nur ausschalten reicht bei OVHcloud vermutlich nicht, um die Kosten zu stoppen.
3. Unter „Billing" bzw. „Abrechnung" im Projekt kontrollieren, dass nichts mehr läuft.

Beim nächsten Mal legst du einen neuen Rechner an und wiederholst die Schritte 3 bis 7; Konto, Projekt und Schlüssel bleiben bestehen. Das dauert dann etwa 15 Minuten.

## Sicherheit

- Der Rechner kennt nach der Einrichtung dein GitHub- und dein Claude-Login. Durch das Löschen nach der Arbeit sind beide wieder weg.
- Von außen sollte nur der SSH-Zugang (Port 22) erreichbar sein. Die Session auf dem Rechner kann das als Erstes prüfen und einstellen.
- Auf dem Rechner entstehen später die echten Bilder. Er steht in Frankreich; die Bilder verlassen ihn nur, wenn sie ausgeliefert werden.
