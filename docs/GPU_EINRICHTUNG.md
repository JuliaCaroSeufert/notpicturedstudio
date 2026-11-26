# GPU einrichten (IONOS Cloud, Frankfurt)

Ziel: ein gemieteter GPU-Rechner in Deutschland, auf dem Claude Code direkt läuft. Du arbeitest danach wie gewohnt im Chat weiter, nur dass die Session auf diesem Rechner sitzt und das echte Bildmodell starten kann. Die bisherige Cloud-Session kann fremde Rechner nicht erreichen, deshalb dieser Weg.

Plan: Für den Aufbau des MVP stundenweise bei IONOS. Später, wenn die GPU regelmäßig gebraucht wird, ein fester Monatsserver bei Hetzner.

Du brauchst ein Terminal auf deinem Computer (Mac: Programm „Terminal"; Windows: „PowerShell").

**Nicht an der Quelle geprüft:** Die IONOS-Seiten sind aus der Entwicklungsumgebung nicht erreichbar. Die Angaben unten stammen aus Suchtreffern zur IONOS-Dokumentation und aus allgemeiner Kenntnis der IONOS-Oberfläche. Stellen, an denen ich unsicher bin, sind mit **(unsicher)** markiert. Die offizielle Anleitung steht unter `docs.ionos.com/cloud/compute-services/compute-engine/cloud-gpu-vm`.

## Was es kostet

- Die kleinste GPU-Vorlage heißt **H200-S**: eine NVIDIA H200, 15 Prozessorkerne, 267 GB Arbeitsspeicher, 1024 GB Speicherplatz. Laut IONOS-Preisliste **3,00 € pro Stunde**.
- Die H200 ist für unsere Zwecke überdimensioniert, reicht dafür aber sicher für Bilderzeugung und Training.
- **(unsicher)** Bei IONOS kostet ein nur gestoppter Rechner in der Regel weiter. Verlässlich endet die Abrechnung erst, wenn du ihn löschst (Schritt 8). Zehn Stunden Arbeit kosten dann rund 30 €; ein vergessener Rechner kostet rund 72 € pro Tag.

## 1. Konto anlegen

1. Ein Konto für **IONOS Cloud** anlegen (`cloud.ionos.de`). Das ist ein anderer Bereich als das normale IONOS-Hosting für Websites und Domains; ein vorhandenes Hosting-Konto reicht nicht.
2. **(unsicher)** IONOS prüft neue Cloud-Konten teils per Rückruf oder E-Mail, bevor Ressourcen freigeschaltet sind.
3. Standardmäßig ist genau ein GPU-Rechner der Größe H200-S erlaubt. Das genügt. Falls beim Anlegen trotzdem eine Meldung zum Limit erscheint, den IONOS-Support um Freischaltung von „1 × Cloud GPU VM H200-S in Frankfurt" bitten.

## 2. Zugangsschlüssel erzeugen

Falls du das schon für einen anderen Anbieter gemacht hast, kannst du denselben Schlüssel wiederverwenden und direkt die zweite Zeile ausführen.

```bash
ssh-keygen -t ed25519 -C "notpicturedstudio"
```

Dreimal Enter drücken. Dann den öffentlichen Teil anzeigen:

```bash
cat ~/.ssh/id_ed25519.pub
```

Die ausgegebene Zeile kopieren. In der IONOS-Oberfläche (dem „Data Center Designer", kurz DCD) oben im Menü unter „Manager" → „SSH Keys" (bzw. „SSH-Schlüssel") eintragen und als Standard markieren. Nur diese `.pub`-Zeile weitergeben, niemals die Datei ohne `.pub`.

## 3. Rechner anlegen

Im DCD arbeitest du auf einer Zeichenfläche: Elemente werden hineingezogen, verbunden und am Ende gemeinsam bereitgestellt.

1. Falls oben ein Hinweis „Vollversion freischalten" erscheint: zuerst freischalten. Im Testmodus sind GPU-Rechner vermutlich nicht verfügbar. IONOS gibt dabei 200 € Startguthaben (Stand November 2026), das sind rund 66 Stunden H200.
2. Ein neues virtuelles Rechenzentrum anlegen: Name `notpicturedstudio`, Standort **Deutschland / Frankfurt am Main (de/fra/2)**. Laut IONOS gibt es die GPU-Rechner nur dort (und in Worcester, UK); **de/fra/1 hat keine**. Der Standort lässt sich nachträglich nicht ändern; ein Rechenzentrum am falschen Standort, das noch „Unprovisioniert" ist, kann man kostenlos löschen.
3. Aus der linken Leiste („Palette", ggf. nach unten scrollen) das Element **„Cloud GPU"** auf die Fläche ziehen.
4. Das Element anklicken. Rechts im Bereich „Inspector":
   - Name: `nps-gpu`
   - Template: **H200-S**
   - Beim Speicher als Image **Ubuntu 24.04** wählen und deinen SSH-Schlüssel auswählen.
5. Aus der linken Leiste das Element **„Internet"** auf die Fläche ziehen und per Linie mit dem Rechner verbinden. Dadurch bekommt er eine Netzwerkkarte mit öffentlicher Adresse.
6. Unten rechts auf **„Änderungen bereitstellen"** klicken, die Prüfung ansehen und mit deinem Passwort bestätigen.
7. Warten, bis die Bereitstellung fertig ist. Dann den Rechner anklicken und im Inspector unter „Network" die öffentliche IPv4-Adresse notieren.

Ab der Bereitstellung läuft die Abrechnung. Wenn du das Element „Cloud GPU" in der Palette nicht findest, liegt es meist am Standort oder am Testmodus.

## 4. Verbinden

Bei IONOS-Images ist der Benutzer in der Regel `root`:

```bash
ssh root@DEINE-IP-ADRESSE
```

Die Rückfrage beim ersten Mal mit `yes` bestätigen. Falls die Anmeldung als `root` abgelehnt wird, versuche `ubuntu@DEINE-IP-ADRESSE`. Ab hier laufen alle Befehle auf dem GPU-Rechner.

## 5. Werkzeuge installieren

Zuerst prüfen, ob der Grafiktreiber schon da ist:

```bash
nvidia-smi
```

Erscheint eine Tabelle mit „H200", ist alles gut. Erscheint „command not found", den Treiber installieren und neu starten:

```bash
apt-get update && apt-get install -y ubuntu-drivers-common && ubuntu-drivers install && reboot
```

Nach etwa einer Minute neu verbinden (Schritt 4). Falls `nvidia-smi` danach immer noch einen Fehler zeigt: trotzdem weitermachen und es der Session in Schritt 7 als Erstes sagen.

Dann die Werkzeuge:

```bash
apt-get update && apt-get install -y git gh python3-venv tmux
```

Claude Code installieren:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Falls danach der Befehl `claude` nicht gefunden wird: einmal `exit` eingeben, neu verbinden und erneut versuchen. Die offizielle Anleitung steht unter `code.claude.com/docs`.

(Wenn du als `ubuntu` statt `root` angemeldet bist, vor die `apt-get`-, `ubuntu-drivers`- und `reboot`-Befehle jeweils `sudo` setzen.)

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

## 8. Nach der Arbeit: löschen

1. In der Session darum bitten, alles zu committen und zu pushen. Was nicht auf GitHub liegt, ist nach dem Löschen weg.
2. Im DCD den Rechner auf der Fläche anklicken, löschen und wieder **„Provision changes"** bestätigen. Erst mit der Bereitstellung ist er wirklich weg. Das leere Rechenzentrum kann bestehen bleiben.
3. Im Menü unter „Kosten" bzw. „Billing" kontrollieren, dass nichts mehr läuft.

Beim nächsten Mal wiederholst du die Schritte 3 bis 7; Konto und Schlüssel bleiben bestehen.

## Alltag: Arbeitssitzung beginnen und beenden

Nach der ersten Einrichtung bleibt alles auf dem Rechner, solange du ihn nur ausschaltest und nicht löschst.

**Beginnen**

1. IONOS-Rechenzentrum öffnen, GPU-Rechner anklicken, „Power" → „Start". Warten, bis „Läuft" dasteht, dann noch zwei bis drei Minuten.
2. Unter „Netzwerk" die IPv4-Adresse prüfen. Sie kann sich nach dem Ausschalten ändern.
3. In PowerShell verbinden:

```powershell
ssh root@DEINE-IP-ADRESSE
```

4. Sitzungsfenster öffnen, in den Projektordner wechseln, den neuesten Stand holen:

```bash
tmux new -s nps
```

```bash
cd ~/notpicturedstudio && git pull
```

5. Claude Code starten. Mit `--continue` geht es in der letzten Unterhaltung weiter; ohne startet eine neue.

```bash
claude --continue
```

**Beenden**

1. In Claude Code schreiben: „Bitte alles committen und pushen und kurz notieren, wo wir stehen."
2. Wenn das erledigt ist, Claude Code mit `/exit` beenden und die Verbindung mit `exit` (zweimal: einmal für tmux, einmal für SSH).
3. IONOS: GPU-Rechner anklicken, „Power" → „Stop". Warten, bis der Zustand nicht mehr „Läuft" zeigt.

**Wenn etwas anders ist als sonst**

- Neue IP-Adresse: Beim ersten Verbinden fragt PowerShell wieder „Are you sure…?"; mit `yes` bestätigen.
- Meldung „REMOTE HOST IDENTIFICATION HAS CHANGED": Nicht einfach weitermachen, sondern melden. Das passiert, wenn der Rechner neu angelegt wurde, kann aber auch auf ein Problem hinweisen.
- Verbindung bricht mitten in der Arbeit ab: neu verbinden und `tmux attach -t nps`. Claude Code hat in der Zwischenzeit weitergearbeitet.

## Sicherheit

- Der Rechner kennt nach der Einrichtung dein GitHub- und dein Claude-Login. Durch das Löschen nach der Arbeit sind beide wieder weg.
- Von außen sollte nur der SSH-Zugang (Port 22) erreichbar sein. Die Session auf dem Rechner prüft das als Erstes.
- Auf dem Rechner entstehen später die echten Bilder. Er steht in Frankfurt; die Bilder verlassen ihn nur, wenn sie ausgeliefert werden.
