#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CartoFLU - Serveur local (APRS-IS + WebSocket + cartes hors ligne)
Bibliotheque standard Python uniquement - AUCUNE dependance pip.

Lancement : python cartoflu_serveur.py --callsign F4FLU
"""

import argparse
import base64
import functools
import hashlib
import http.server
import json
import math
import os
import queue
import re
import socket
import struct
import threading
import time

# ── Configuration / etat partage ──────────────────────────────────────────────

APRS_SERVERS = [
    ("euro.aprs2.net", 14580),
    ("rotate.aprs2.net", 14580),
    ("euro.aprs2.net", 10152),
    ("rotate.aprs2.net", 10152),
]

STATE = {"filter": "r/47.2/6.0/200", "connected": False, "source": "both"}
filter_queue = queue.Queue()


def aprsis_on():
    return STATE["source"] in ("aprsis", "both")


def kiss_on():
    return STATE["source"] in ("kiss", "both")
pos_history = {}          # indicatif -> (lat, lon, timestamp)

# ── Parser APRS (port fidele de main.go) ───────────────────────────────────────

rePosUncomp = re.compile(r'^(\d{2}[\d ]{2}\.[\d ]{2}[NS])(.)(\d{3}[\d ]{2}\.[\d ]{2}[EW])(.)(.*)')
reAlt = re.compile(r'/A=(\d+)')
reCourse = re.compile(r'^(\d{3})/(\d{3})')


def parse_lat(s):
    if len(s) < 7:
        return None
    hemi = s[-1]
    body = s[:-1].replace(" ", "0")      # ambiguite APRS -> 0
    try:
        dd = float(body[:2]); mm = float(body[2:])
    except ValueError:
        return None
    deg = dd + mm / 60.0
    if hemi == "S":
        deg = -deg
    return round(deg * 1e6) / 1e6


def parse_lon(s):
    if len(s) < 8:
        return None
    hemi = s[-1]
    body = s[:-1].replace(" ", "0")
    try:
        ddd = float(body[:3]); mm = float(body[3:])
    except ValueError:
        return None
    deg = ddd + mm / 60.0
    if hemi == "W":
        deg = -deg
    return round(deg * 1e6) / 1e6


def dec_comp_lat(s):
    y = 0.0
    for c in s:
        y = y * 91 + (ord(c) - 33)
    return round((90.0 - y / 380926.0) * 1e6) / 1e6


def dec_comp_lon(s):
    x = 0.0
    for c in s:
        x = x * 91 + (ord(c) - 33)
    return round((-180.0 + x / 190463.0) * 1e6) / 1e6


def parse_extras(comment):
    course = speed = altitude = comm = ""
    m = reAlt.search(comment)
    if m:
        altitude = "%.0f" % (float(m.group(1)) * 0.3048)
    mc = reCourse.match(comment)
    if mc:
        course = mc.group(1)
        speed = "%.0f" % (float(mc.group(2)) * 1.852)
        if len(comment) > 7:
            comm = comment[7:].strip()
    else:
        comm = reAlt.sub("", comment).strip()
    return course, speed, altitude, comm


def parse_position(payload):
    if len(payload) < 2:
        return None
    dtype = payload[0]
    if dtype in "!=":
        body = payload[1:]
    elif dtype in "@/":
        body = payload[8:] if len(payload) > 8 else ""
    elif dtype == ";":
        body = payload[18:] if len(payload) > 18 else ""
    elif dtype in "`'":
        return None
    else:
        body = payload[1:]
    if len(body) < 10:
        return None

    # Format non compresse
    m = rePosUncomp.match(body)
    if m:
        la = parse_lat(m.group(1))
        lo = parse_lon(m.group(3))
        if la is None or lo is None:
            return None
        course, speed, altitude, comment = parse_extras(m.group(5))
        return la, lo, m.group(2) + m.group(4), course, speed, altitude, comment

    # Format compresse
    if len(body) >= 10:
        symT = body[0]; lc = body[1:5]; oc = body[5:9]; symC = body[9]; rest = body[10:]
        if all(33 <= ord(c) <= 126 for c in (lc + oc)):
            la = dec_comp_lat(lc); lo = dec_comp_lon(oc)
            if -90 <= la <= 90 and -180 <= lo <= 180:
                course, speed, altitude, comment = parse_extras(rest)
                return la, lo, symT + symC, course, speed, altitude, comment
    return None


# ── Mic-E (trames trackers/portatifs) ───────────────────────────────────────────
# La latitude + 3 bits sont codes dans l'adresse destination (6 car.) ;
# longitude, vitesse, cap et symbole dans le champ info.
_MICE_OK = set("0123456789ABCDEFGHIJKLPQRSTUVWXYZ")


def decode_mice(dest, info):
    if len(dest) < 6 or len(info) < 9:
        return None
    d = dest[:6]
    if any(ch not in _MICE_OK for ch in d):
        return None

    lat_digits = []
    ns_bit = lo_bit = we_bit = 0          # 0 = Sud / +0 / Est ; 1 = Nord / +100 / Ouest
    for i, ch in enumerate(d):
        o = ord(ch)
        if 48 <= o <= 57:                 # 0-9
            dig = ch; bit = 0
        elif 65 <= o <= 74:               # A-J (message custom)
            dig = chr(o - 17); bit = 1
        elif 80 <= o <= 89:               # P-Y (message standard)
            dig = chr(o - 32); bit = 1
        elif ch == "K":                   # espace, custom
            dig = "0"; bit = 1
        elif ch == "L":                   # espace, standard, bit 0
            dig = "0"; bit = 0
        elif ch == "Z":                   # espace, standard, bit 1
            dig = "0"; bit = 1
        else:
            return None
        lat_digits.append(dig)
        if i == 3:
            ns_bit = bit
        elif i == 4:
            lo_bit = bit
        elif i == 5:
            we_bit = bit

    latstr = "".join(lat_digits)          # DDMMmm
    try:
        lat = int(latstr[0:2]) + float(latstr[2:4] + "." + latstr[4:6]) / 60.0
    except ValueError:
        return None
    if ns_bit == 0:                       # 0 -> Sud
        lat = -lat

    # Longitude : info[1..3] (info[0] = type Mic-E ` ou ')
    lon_deg = (ord(info[1]) - 28)
    if lo_bit == 1:
        lon_deg += 100
    if 180 <= lon_deg <= 189:
        lon_deg -= 80
    elif 190 <= lon_deg <= 199:
        lon_deg -= 190
    lon_min = ord(info[2]) - 28
    if lon_min >= 60:
        lon_min -= 60
    lon_hund = ord(info[3]) - 28
    lon = lon_deg + (lon_min + lon_hund / 100.0) / 60.0
    if we_bit == 1:                       # 1 -> Ouest
        lon = -lon

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    # Vitesse (noeuds) + cap : info[4..6]
    sp = ord(info[4]) - 28
    dc = ord(info[5]) - 28
    se = ord(info[6]) - 28
    speed_kn = sp * 10 + dc // 10
    course = (dc % 10) * 100 + se
    if speed_kn >= 800:
        speed_kn -= 800
    if course >= 400:
        course -= 400
    speed = "%.0f" % (speed_kn * 1.852)   # -> km/h (comme parse_extras)

    # Symbole : info[7]=code, info[8]=table -> on stocke "table+code" (idem autres formats)
    sym = info[8] + info[7]

    # Commentaire + altitude Mic-E optionnelle ("xxx}" en base-91, metres - 10000)
    comment = info[9:]
    altitude = ""
    if len(comment) >= 4 and comment[3] == "}":
        try:
            a = 0
            for ch in comment[:3]:
                a = a * 91 + (ord(ch) - 33)
            altitude = "%d" % (a - 10000)
        except Exception:
            pass
        comment = comment[4:]

    lat = round(lat * 1e6) / 1e6
    lon = round(lon * 1e6) / 1e6
    return lat, lon, sym, str(course), speed, altitude, comment.strip()


# ── KISS / AX.25 (decodeur RF : Direwolf ou tout TNC KISS) ──────────────────────
KISS_FEND = 0xC0
KISS_FESC = 0xDB
KISS_TFEND = 0xDC
KISS_TFESC = 0xDD


def kiss_unescape(frame):
    out = bytearray(); i = 0; n = len(frame)
    while i < n:
        b = frame[i]
        if b == KISS_FESC and i + 1 < n:
            nb = frame[i + 1]
            if nb == KISS_TFEND:
                out.append(KISS_FEND); i += 2; continue
            if nb == KISS_TFESC:
                out.append(KISS_FESC); i += 2; continue
        out.append(b); i += 1
    return bytes(out)


def decode_ax25(frame):
    """Trame AX.25 brute -> (src, dest, [digis], info) pour les trames UI."""
    if len(frame) < 16:
        return None
    addrs = []; i = 0
    while i + 7 <= len(frame):
        a = frame[i:i + 7]
        call = "".join(chr(b >> 1) for b in a[:6]).strip()
        ssid = (a[6] >> 1) & 0x0F
        addrs.append(call if ssid == 0 else "%s-%d" % (call, ssid))
        i += 7
        if a[6] & 0x01:                   # bit d'extension HDLC -> derniere adresse
            break
    if len(addrs) < 2 or i + 2 > len(frame):
        return None
    if frame[i] != 0x03 or frame[i + 1] != 0xF0:   # UI + pas de couche 3
        return None
    info = frame[i + 2:].decode("latin1", errors="replace")
    return addrs[1], addrs[0], addrs[2:], info      # src, dest, digis, info


def ax25_to_tnc2(src, dest, digis, info):
    hdr = "%s>%s" % (src, dest)
    if digis:
        hdr += "," + ",".join(digis)
    return hdr + ":" + info


def parse_packet(line):
    line = line.strip()
    if line == "" or line.startswith("#"):
        return None
    ci = line.find(":")
    if ci < 0:
        return None
    header = line[:ci]
    payload = line[ci + 1:]
    gi = header.find(">")
    if gi < 0:
        return None
    cs = header[:gi].strip().upper()
    # Destination (tocall) : en Mic-E elle porte la latitude
    dest = header[gi + 1:].split(",")[0].split("-")[0].strip().upper()
    if payload[:1] in ("`", "'"):
        res = decode_mice(dest, payload)
    else:
        res = parse_position(payload)
    if res is None:
        return None
    lat, lon, sym, course, speed, alt, comm = res
    now = str(int(time.time()))
    return {
        "name": cs, "lat": "%f" % lat, "lng": "%f" % lon,
        "symbol": sym, "course": course, "speed": speed, "altitude": alt,
        "comment": comm, "lasttime": now, "postime": now, "time": now,
    }


# ── Validation position ─────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_valid_position(cs, lat, lon):
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return False, "coords hors plage (%.4f,%.4f)" % (lat, lon)
    parts = STATE["filter"].split("/")
    if len(parts) == 4:
        try:
            zlat = float(parts[1]); zlon = float(parts[2]); zrad = float(parts[3])
            dist = haversine_km(lat, lon, zlat, zlon)
            if dist > zrad * 2.5:
                return False, "hors zone (%.0fkm > %.0fkm)" % (dist, zrad * 2.5)
        except ValueError:
            pass
    prev = pos_history.get(cs)
    now = time.time()
    if prev:
        elapsed_h = (now - prev[2]) / 3600.0
        if elapsed_h > 0:
            dist = haversine_km(lat, lon, prev[0], prev[1])
            spd = dist / elapsed_h
            if spd > 1000 and dist > 50:
                return False, "vitesse impossible (%.0f km/h sur %.0f km)" % (spd, dist)
    pos_history[cs] = (lat, lon, now)
    return True, "ok"


# ── WebSocket (RFC 6455, stdlib pure) ──────────────────────────────────────────

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
clients = set()
clients_lock = threading.Lock()


def ws_accept_key(key):
    return base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("socket fermee")
        data += chunk
    return data


def ws_recv_frame(sock):
    hdr = recv_exact(sock, 2)
    opcode = hdr[0] & 0x0F
    masked = (hdr[1] & 0x80) != 0
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if masked else b"\x00\x00\x00\x00"
    payload = recv_exact(sock, length)
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def ws_send_frame(sock, payload):
    n = len(payload)
    if n <= 125:
        header = bytes([0x81, n])
    elif n <= 65535:
        header = bytes([0x81, 126]) + struct.pack(">H", n)
    else:
        header = bytes([0x81, 127]) + struct.pack(">Q", n)
    sock.sendall(header + payload)


class WSClient:
    def __init__(self, sock):
        self.sock = sock
        self.lock = threading.Lock()
        self.alive = True

    def send_text(self, text):
        with self.lock:
            try:
                ws_send_frame(self.sock, text.encode("utf-8"))
            except Exception:
                self.alive = False

    def ping(self):
        with self.lock:
            try:
                self.sock.sendall(b"\x89\x00")
            except Exception:
                self.alive = False


def broadcast(msg):
    data = json.dumps(msg)
    with clients_lock:
        for c in list(clients):
            c.send_text(data)
            if not c.alive:
                clients.discard(c)


def ws_handle(conn):
    client = None
    try:
        conn.settimeout(10)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(1024)
            if not chunk:
                conn.close(); return
            data += chunk
        conn.settimeout(None)
        key = ""
        for line in data.decode("latin1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        if not key:
            conn.close(); return
        resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                "Sec-WebSocket-Accept: " + ws_accept_key(key) + "\r\n\r\n")
        conn.sendall(resp.encode())

        client = WSClient(conn)
        with clients_lock:
            clients.add(client)
        client.send_text(json.dumps({
            "type": "status",
            "msg": "Relais CartoFLU pret - filtre : " + STATE["filter"],
            "connected": STATE["connected"],
        }))
        client.send_text(json.dumps({"type": "source", "source": STATE["source"]}))

        while client.alive:
            opcode, payload = ws_recv_frame(conn)
            if opcode == 0x8:        # close
                break
            if opcode == 0x1:        # texte
                try:
                    m = json.loads(payload.decode("utf-8"))
                    if m.get("type") == "setfilter" and m.get("filter"):
                        filter_queue.put(m["filter"].strip())
                    elif m.get("type") == "setsource" and m.get("source") in ("aprsis", "kiss", "both"):
                        STATE["source"] = m["source"]
                        libelle = {"aprsis": "Internet (APRS-IS)",
                                   "kiss": "RF (KISS)",
                                   "both": "Internet + RF"}[STATE["source"]]
                        print("[WS] Source -> %s" % STATE["source"])
                        broadcast({"type": "source", "source": STATE["source"]})
                        broadcast({"type": "status", "msg": "Source : " + libelle,
                                   "connected": STATE["connected"]})
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if client is not None:
            with clients_lock:
                clients.discard(client)
        try:
            conn.close()
        except Exception:
            pass


def ws_server(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(16)
    print("[WS] Serveur WebSocket sur ws://localhost:%d" % port)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=ws_handle, args=(conn,), daemon=True).start()


def ping_loop():
    while True:
        time.sleep(25)
        with clients_lock:
            for c in list(clients):
                c.ping()


# ── Serveur HTTP fichiers (tuiles + appli) ─────────────────────────────────────

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args):
        pass  # silencieux


def http_server(port, root):
    handler = functools.partial(CORSHandler, directory=root)
    httpd = http.server.ThreadingHTTPServer(("", port), handler)
    print("[HTTP] Fichiers sur http://localhost:%d/  (dossier : %s)" % (port, os.path.abspath(root)))
    httpd.serve_forever()


# ── Lecteur APRS-IS TCP ─────────────────────────────────────────────────────────

def aprs_reader(args):
    servers = APRS_SERVERS
    if args.aprshost != "euro.aprs2.net":
        servers = [(args.aprshost, args.aprsport)]

    while True:
        if not aprsis_on():
            time.sleep(1)
            continue
        conn = None; connected_to = None; reader = None
        for host, port in servers:
            try:
                print("[APRS] Tentative : %s:%d..." % (host, port))
                c = socket.create_connection((host, port), timeout=8)
            except Exception as e:
                print("[APRS] X %s:%d - %s" % (host, port, e))
                continue
            c.sendall(("user %s pass %s vers CartoFLU 1.2\r\n" % (args.callsign, args.passcode)).encode())
            c.settimeout(12)
            r = c.makefile("r", encoding="latin1", newline="\n")
            got = False
            try:
                for line in r:
                    line = line.rstrip("\r\n")
                    print("[APRS] %s" % line)
                    if "logresp" in line.lower():
                        got = True; break
            except socket.timeout:
                pass
            if not got:
                print("[APRS] X %s:%d - pas de logresp" % (host, port))
                c.close(); continue
            conn = c; connected_to = "%s:%d" % (host, port); reader = r
            break

        if conn is None:
            print("[APRS] Tous les serveurs ont echoue - retry dans %ds..." % args.reconnect)
            broadcast({"type": "status", "msg": "Aucun serveur APRS-IS accessible - reconnexion...", "connected": False})
            time.sleep(args.reconnect); continue

        conn.sendall(("#filter %s\r\n" % STATE["filter"]).encode())
        STATE["connected"] = True
        print("[APRS] OK Connecte a %s - filtre : %s" % (connected_to, STATE["filter"]))
        broadcast({"type": "status", "msg": "APRS-IS connecte - %s - filtre %s" % (connected_to, STATE["filter"]), "connected": True})
        conn.settimeout(90)

        try:
            for line in reader:
                if not aprsis_on():
                    break
                line = line.rstrip("\r\n")
                # Appliquer les changements de filtre en attente
                try:
                    while True:
                        newf = filter_queue.get_nowait()
                        STATE["filter"] = newf
                        conn.sendall(("#filter %s\r\n" % newf).encode())
                        print("[APRS] Filtre mis a jour : %s" % newf)
                        broadcast({"type": "status", "msg": "Filtre mis a jour : %s" % newf, "connected": True})
                except queue.Empty:
                    pass

                if not line:
                    continue
                if line.startswith("#"):
                    print("[APRS] %s" % line)
                    broadcast({"type": "server", "msg": line})
                    continue

                print("[APRS] TRAME : %.100s" % line)
                entry = parse_packet(line)
                if entry is None:
                    print("[APRS] ~ Non parse")
                    continue
                lat = float(entry["lat"]); lon = float(entry["lng"])
                valid, reason = is_valid_position(entry["name"], lat, lon)
                if not valid:
                    print("[APRS] X %s rejete - %s" % (entry["name"], reason))
                    continue
                print("[APRS] OK %s  %s,%s" % (entry["name"], entry["lat"], entry["lng"]))
                if aprsis_on():
                    broadcast({"type": "position", "entry": entry})
        except (socket.timeout, OSError):
            pass

        STATE["connected"] = False
        try:
            conn.close()
        except Exception:
            pass
        if not aprsis_on():
            print("[APRS] Source Internet desactivee - mise en veille")
            broadcast({"type": "status", "msg": "APRS-IS en veille (source desactivee)", "connected": False})
            continue
        print("[APRS] Connexion perdue - reconnexion dans %ds..." % args.reconnect)
        broadcast({"type": "status", "msg": "APRS-IS deconnecte - reconnexion dans %ds..." % args.reconnect, "connected": False})
        time.sleep(args.reconnect)


# ── Lecteur KISS / Direwolf (RF) ────────────────────────────────────────────────

def kiss_reader(args):
    seen = {}                              # (src, info) -> t : anti-doublon direct/digipete
    while True:
        if not kiss_on():
            time.sleep(1)
            continue
        try:
            print("[KISS] Connexion a %s:%d..." % (args.kisshost, args.kissport))
            c = socket.create_connection((args.kisshost, args.kissport), timeout=8)
        except Exception as e:
            print("[KISS] X %s:%d - %s (retry %ds)" % (args.kisshost, args.kissport, e, args.reconnect))
            broadcast({"type": "status",
                       "msg": "KISS/Direwolf injoignable (%s:%d) - reconnexion..." % (args.kisshost, args.kissport),
                       "connected": STATE["connected"]})
            time.sleep(args.reconnect); continue

        print("[KISS] OK connecte a %s:%d" % (args.kisshost, args.kissport))
        STATE["connected"] = True
        broadcast({"type": "status",
                   "msg": "KISS/Direwolf connecte (%s:%d)" % (args.kisshost, args.kissport),
                   "connected": True})
        c.settimeout(20)
        buf = bytearray()
        try:
            while True:
                if not kiss_on():
                    break
                try:
                    chunk = c.recv(4096)
                except socket.timeout:
                    continue               # canal radio silencieux : on patiente
                if not chunk:
                    break
                buf.extend(chunk)
                while True:
                    try:
                        idx = buf.index(KISS_FEND)
                    except ValueError:
                        break
                    frame = bytes(buf[:idx]); del buf[:idx + 1]
                    if not frame or (frame[0] & 0x0F) != 0x00:   # garder trames de donnees (type 0)
                        continue
                    dec = decode_ax25(kiss_unescape(frame[1:]))
                    if not dec:
                        continue
                    src, dest, digis, info = dec
                    now = time.time()
                    key = (src, info)
                    if key in seen and now - seen[key] < 30:
                        continue           # doublon (recu en direct + via digipeteur)
                    seen[key] = now
                    if len(seen) > 500:
                        seen = {k: v for k, v in seen.items() if now - v < 60}

                    line = ax25_to_tnc2(src, dest, digis, info)
                    broadcast({"type": "server", "msg": "RF " + line[:110]})
                    entry = parse_packet(line)
                    if entry is None:
                        print("[KISS] ~ non parse : %.90s" % line); continue
                    lat = float(entry["lat"]); lon = float(entry["lng"])
                    valid, reason = is_valid_position(entry["name"], lat, lon)
                    if not valid:
                        print("[KISS] X %s rejete - %s" % (entry["name"], reason)); continue
                    print("[KISS] OK %s  %s,%s" % (entry["name"], entry["lat"], entry["lng"]))
                    entry["via"] = "rf"          # marqueur source RF (badge cote navigateur)
                    if kiss_on():
                        broadcast({"type": "position", "entry": entry})
        except (socket.timeout, OSError):
            pass
        try:
            c.close()
        except Exception:
            pass
        if not kiss_on():
            print("[KISS] Source RF desactivee - mise en veille")
            continue
        print("[KISS] Connexion perdue - reconnexion dans %ds..." % args.reconnect)
        time.sleep(args.reconnect)


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="CartoFLU - serveur local APRS-IS + cartes")
    ap.add_argument("--callsign", default="N0CALL", help="Indicatif APRS-IS")
    ap.add_argument("--pass", dest="passcode", default="-1", help="Passcode (-1 = lecture seule)")
    ap.add_argument("--filter", default="r/47.2/6.0/200", help="Filtre APRS-IS")
    ap.add_argument("--aprshost", default="euro.aprs2.net")
    ap.add_argument("--aprsport", type=int, default=14580)
    ap.add_argument("--wsport", type=int, default=2237, help="Port WebSocket")
    ap.add_argument("--httpport", default="8080", help="Port HTTP (0 pour desactiver)")
    ap.add_argument("--webroot", default=".", help="Dossier servi (appli + tuiles/)")
    ap.add_argument("--reconnect", type=int, default=15, help="Delai reconnexion (s)")
    ap.add_argument("--source", default="both", choices=["aprsis", "kiss", "both"],
                    help="Source des trames : aprsis | kiss | both (defaut both)")
    ap.add_argument("--kisshost", default="127.0.0.1", help="Hote KISS/Direwolf (defaut 127.0.0.1)")
    ap.add_argument("--kissport", type=int, default=8001, help="Port KISS TCP (defaut 8001)")
    args = ap.parse_args()

    STATE["filter"] = args.filter
    STATE["source"] = args.source

    bar = "=" * 58
    print(bar)
    print("  CartoFLU - Serveur local (APRS-IS + cartes hors ligne)")
    print(bar)
    print("  WebSocket APRS : ws://localhost:%d" % args.wsport)
    if args.httpport not in ("0", ""):
        print("  Serveur HTTP   : http://localhost:%s/" % args.httpport)
    print("  Indicatif      : %s  (pass %s = lecture seule)" % (args.callsign, args.passcode))
    print("  Filtre         : %s" % args.filter)
    print("  Source initiale: %s  (commutable depuis CartoFLU)" % args.source)
    print("  KISS/Direwolf  : %s:%d" % (args.kisshost, args.kissport))
    print(bar)
    print("  Dans CartoFLU -> onglet APRS -> mode 'Relais local'")
    print("  Ctrl+C pour quitter")
    print()

    threading.Thread(target=ping_loop, daemon=True).start()
    threading.Thread(target=ws_server, args=(args.wsport,), daemon=True).start()
    if args.httpport not in ("0", ""):
        threading.Thread(target=http_server, args=(int(args.httpport), args.webroot), daemon=True).start()

    # Les deux lecteurs tournent en permanence ; STATE["source"] decide de ce qui
    # est reellement emis. La source est commutable a chaud depuis CartoFLU
    # ({type:'setsource'}) ; un lecteur non selectionne se met en veille (silencieux).
    threading.Thread(target=aprs_reader, args=(args,), daemon=True).start()
    threading.Thread(target=kiss_reader, args=(args,), daemon=True).start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nArret.")


if __name__ == "__main__":
    main()
