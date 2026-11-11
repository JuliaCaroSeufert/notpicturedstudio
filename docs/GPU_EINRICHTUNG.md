# GPU einrichten (Scaleway, Paris)

Ziel: ein gemieteter GPU-Rechner in der EU, auf dem Claude Code direkt läuft. Du arbeitest danach wie gewohnt im Chat weiter, nur dass die Session auf diesem Rechner sitzt und das echte Bildmodell starten kann. Die bisherige Cloud-Session kann fremde Rechner nicht erreichen, deshalb dieser Weg.

Dauer: etwa 30 bis 45 Minuten beim ersten Mal. Du brauchst ein Terminal auf deinem Computer (Mac: Programm „Terminal"; Windows: „PowerShell").

**Nicht an der Quelle geprüft:** Die Scaleway-Website ist aus der Entwicklungsumgebung nicht erreichbar. Preise, Typnamen und Menüpunkte unten stammen aus Drittquellen und aus Erfahrung; die Konsole zeigt dir den tatsächlichen Preis an, bevor du etwas bestätigst.

## Was es kostet

- Abgerechnet wird nach Laufzeit. Preisvergleichsseiten nennen für den Typ **L4-1-24G** rund 0,80 bis 0,90 € pro Stunde und für **L40S-1-48G** rund 1,50 bis 1,70 € pro Stunde (Stand November 2026).
- Speicherplatz und öffentliche IP-Adresse kosten zusätzlich einen kleinen Betrag, vermutlich auch bei ausgeschaltetem Rechner.
- Wichtig: Nach der Arbeit den Rechner ausschalten oder löschen (Schritt 8), sonst läuft die Uhr weiter.

## 1. Konto anlegen

1. Auf `console.scaleway.com` registrieren, E-Mail bestätigen, Zahlungsmittel hinterlegen.
2. Scaleway verlangt bei neuen Konten oft eine Identitätsprüfung, bevor GPU-Rechner freigeschaltet sind. Falls beim Anlegen in Schritt 3 die Meldung kommt, dass dein Kontingent nicht reicht: über „Support" ein Ticket öffnen und die Freischaltung von einer GPU-Instanz vom Typ L4 in Paris beantragen.

## 2. Zugangsschlüssel erzeugen

Auf deinem Computer im Terminal:

```bash
ssh-keygen -t ed25519 -C "notpicturedstudio"
```

Dreimal Enter drücken (Standardort, kein Passwort nötig; ein Passwort ist sicherer). Dann den öffentlichen Teil anzeigen:

```bash
cat ~/.ssh/id_ed25519.pub
```

Die ausgegebene Zeile kopieren und in der Scaleway-Konsole unter „SSH Keys" (im Bereich Projekt-Einstellungen bzw. Zugangsdaten) einfügen. Nur diese `.pub`-Zeile weitergeben, niemals die Datei ohne `.pub`.

## 3. Rechner anlegen

In der Konsole unter „Instances" → „Create Instance":

| Einstellung | Wert |
|---|---|
| Region / Zone | Paris (PAR-2, bei L4 auch PAR-1) |
| Typ | **L4-1-24G** (eine GPU mit 24 GB). Reicht für das Bildmodell; falls das Training später zu wenig Speicher hat, wechseln wir auf L40S-1-48G |
| Betriebssystem | „Ubuntu … GPU OS" (mit vorinstallierten NVIDIA-Treibern) |
| Speicher | mindestens 150 GB |
| Name | z. B. `nps-gpu` |

Anlegen und warten, bis der Status „Running" zeigt. Die öffentliche IP-Adresse notieren.

## 4. Verbinden

```bash
ssh root@DEINE-IP-ADRESSE
```

Die Rückfrage beim ersten Mal mit `yes` bestätigen. Ab hier laufen alle Befehle auf dem GPU-Rechner.

Prüfen, ob die GPU da ist (es sollte eine Tabelle mit „L4" erscheinen):

```bash
nvidia-smi
```

## 5. Werkzeuge installieren

```bash
apt-get update && apt-get install -y git gh python3-venv tmux
```

Claude Code installieren:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Falls danach der Befehl `claude` nicht gefunden wird: einmal `exit` eingeben, neu verbinden (Schritt 4) und erneut versuchen. Die offizielle Anleitung steht unter `code.claude.com/docs`.

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

Der Rechner erscheint dann in der Claude-Code-App, und du führst die Unterhaltung von dort. (Nach einem Verbindungsabbruch kommst du mit `ssh root@DEINE-IP-ADRESSE` und dann `tmux attach -t nps` zurück.)

## 8. Nach der Arbeit: ausschalten

1. In der Session darum bitten, alles zu committen und zu pushen. Was nicht auf GitHub liegt, ist nach dem Löschen des Rechners weg.
2. In der Scaleway-Konsole den Rechner ausschalten („Power off") oder löschen. Beim Löschen auch Speicher und IP-Adresse mit entfernen, sonst kosten sie weiter.
3. In der Abrechnungsübersicht kontrollieren, dass nichts mehr läuft.

## Sicherheit

- Der Rechner kennt nach der Einrichtung dein GitHub- und dein Claude-Login. Wenn du ihn länger nicht brauchst: löschen statt nur ausschalten.
- In der Konsole unter „Security Groups" nur den SSH-Zugang (Port 22) von außen erlauben.
- Auf dem Rechner entstehen später die echten Bilder. Er steht in Paris; die Bilder verlassen ihn nur, wenn sie ausgeliefert werden.
