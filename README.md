# LinSTOP

LinSTOP ist ein eigenständiger Linux-Nachbau der öffentlich dokumentierten WinSTOP-Bedienideen. Es verwendet keine WinSTOP-Binäranalyse, keinen Lizenzcode und keine originalen Programmbestandteile.

## Aus WinSTOP dokumentiert

Aus den lokalen Hilfedateien lassen sich diese Kernflächen ableiten:

- Packet-Radio-Terminal mit mehreren Kanälen.
- Treiber/Ports für TNC, AGW/FlexNet-ähnliche Backends und Loopback.
- Connect-/Disconnect-Workflow mit automatisch gesendeter Verbindungsstartzeile.
- QSO-Fenster, Monitorfenster, Infofenster, MHeard-Liste und Portstatus.
- Vorschreibfenster mit ESC-Befehlen, wobei unbekannte ESC-Befehle an den TNC gehen.
- Textvariablen für Prompt, Connect-Texte und Makros.
- User-Datenbank mit Rufzeichen, Name, Ort, Locator, Home-BBS, Zähler und Remote-Rechten.
- Remote-Kommandos mit `//` und Berechtigungsstufen.
- Sound-/Beacon-/Alarm-Funktionen sowie spätere Dateiübertragung.

## Linux-Zielarchitektur

Der erste echte Transport ist bewusst Linux-nativ: AX.25-Kernel plus `ax25-tools`, konkret `ax25_call` für interaktive Verbindungen. Zusätzlich gibt es einen direkten AXIP/AX25UDP-Transport nach TNT-/FlexNet-Art für Setups ohne Kernel-MKISS, z. B. `10093@44.148.230.93:93`. Dieser UDP-Modus sendet AX.25-Frames mit RFC-1226-FCS.

Der Code trennt drei Schichten:

- `LinStopSession`: Kanäle, Connect-Status, MHeard, QSO-Logik.
- `render_template`: WinSTOP-artige Textvariablen für Prompt, Connect-Texte und Makros.
- `Transport`: austauschbare Backends, aktuell `LoopbackTransport` und `Ax25CommandTransport`.

## Erster lauffähiger Umfang

- Mehrkanal-Sessionmodell.
- Verbindungsstartzeile im dokumentierten Format `{LinSTOP-<version>-<umlaut><flags>}`.
- Textvariablen wie `%SCC`, `%UN`, `%UCC`, `%ZZ`, `%ZD`, `%NK`, `%NA`, `%Hxx` und `%%`.
- JSON-basierte Userdatenbank.
- CLI für Connect, Textausgabe, Makrotest, MHeard und interaktiven Betrieb.
- Native AX.25-Anbindung über `ax25_call`.
- Direkte AX25UDP-Anbindung über UDP-Rohframes mit FCS, ohne `kissattach`/`ax25d`.
- Minimaler Connected Mode mit SABM/UA, I-Frames und RR-ACKs.
- Windowsartige Tkinter-Desktopoberfläche mit Menüleiste, Toolbar, Kanalbuttons, QSO-, Monitor-, Info- und Userfenstern. QSO und Monitor liegen wie bei klassischen Terminals horizontal untereinander.
- QSO-/Monitoranzeige mit fester Monospace-80-Spalten-Anmutung; AX.25 selbst definiert keine Terminal-Zeilenlänge, TNT nutzt aber `input_linelen 80`.
- AX.25-Rohframe-Formatter für Monitorzeilen inklusive Adressen, Digipeaterpfad, Control-Feld, PID und Payload.
- Live-Monitor via `listen -a -h -r -p <port>` aus `ax25-apps` direkt im Monitorfenster.

## Start

```bash
cd linstop
PYTHONPATH=src /usr/bin/python -m linstop --help
PYTHONPATH=src /usr/bin/python -m linstop config-init
PYTHONPATH=src /usr/bin/python -m linstop config-show
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc template "Hallo %UN de %SCC um %ZZ" --user dbw400
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc connect dbw400 --send "Hallo %UN, hier ist %SCC"
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc gui
PYTHONPATH=src /usr/bin/python -m linstop decode-frame "9c 94 6e a0 40 40 e0 9c 6e 98 8a 9a 40 61 03 f0 54 68 65"
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc probe-ax25udp IGATE
```

Mit Linux-AX.25:

```bash
# Voraussetzung: ax25-tools installiert, Port in /etc/ax25/axports konfiguriert
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc-3 --transport ax25 --port P3 connect dbw400
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc-3 --transport ax25 --port P3 shell
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc-3 --transport ax25 --port P3 gui
```

Direkt per AX25UDP wie dein TNT-Setup:

```bash
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc --transport ax25udp connect IGATE
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc --transport ax25udp gui
PYTHONPATH=src /usr/bin/python -m linstop --station do2bbc probe-ax25udp IGATE --mode ui --text "LinSTOP test de DO2BBC"
```

Validierter Test gegen `44.148.230.93:93`: `DO2BBC` connected zu `IGATE`, IGATE antwortet mit `UA`, sendet den Prompt, nimmt `info` als I-Frame an und liefert den deutschen Infotext zurück.

## Konfiguration

Die Standardkonfiguration liegt unter `~/.config/linstop/config.json`. Sie enthält ein Stationsprofil und eine Portliste. Für Funkamateure sind Felder wie Rufzeichen, Name, QTH, QRA/Locator, DOK/Club, Lizenzklasse, Home-BBS, Node-Call, Convers-Call und weitere User-Calls vorgesehen.

Im Einstellungsdialog wird die deutsche Klasse beim Bearbeiten des Rufzeichens konservativ vorgeschlagen. Die AfuV verweist in § 10 auf den von der Bundesnetzagentur veröffentlichten Rufzeichenplan; die App bildet daraus die praktischen Reihen ab: `DN1` bis `DN8` -> `Ausbildung`, `DN9` -> `N`, `DA6` und `DO` -> `E`, sonstige deutsche `D`-Afu-Reihen -> `A`. CB-artige Calls wie drei Buchstaben plus drei Zahlen (`DBW400`) oder Division/Club/Nummer (`13BB016`) werden als `CB-Funk` markiert. Sonderfälle können manuell gepflegt werden.

Der Default-Port heißt `igate-axudp` und zeigt auf `44.148.230.93:93` mit lokalem UDP-Port `10093`. In der GUI ist der Dialog unter `Tools/Einstellungen...` erreichbar.

TNT-artige Zielschreibweise wird in der GUI akzeptiert: `P3:DBW400 DB0ABC` verbindet zu `DBW400` auf Port `P3` via `DB0ABC`.

## Nächste sinnvolle Ausbaustufen

- Vollbild-TUI mit Kanalzeile, QSO-, Monitor-, Info- und MHeard-Panels.
- `listen`/netlink-basierter Monitor für AX.25-Frames und MHeard.
- Importer für die alte xBase-Userdatenbank, falls wir DBF-Feldnamen sauber auslesen können.
- Remote-Kommandos mit expliziter Allowlist pro Rufzeichen.
- YAPP/7plus-Dateitransfer als getrennte Module.
