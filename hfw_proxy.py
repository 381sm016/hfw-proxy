"""hfw-proxy: install PS3 firmware over the network, no USB stick.

Run this on a PC, point the PS3's proxy setting at it, and "Update via
Internet" installs the PS3UPDAT.PUP sitting next to this script. It also
serves .pkg files from the pkg folder to the PS3 browser.

    python hfw_proxy.py
"""
import argparse
import hashlib
import os
import select
import shutil
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PUP_NAME = "PS3UPDAT.PUP"
PUP_PATH = os.path.join(HERE, PUP_NAME)
PKG_DIR = os.path.join(HERE, "pkg")

# Region codes used in the update list (one line pair per console region).
DEST_CODES = ["83", "84", "85", "86", "87", "88", "89", "8A", "8B", "8C", "8D", "8E"]
CFG = {}


def build_update_list():
    ver = CFG["version"]  # e.g. "4.92" -> "4.9200"
    major, minor = ver.split(".")
    full = f"{int(major)}.{minor.ljust(4, '0')}"
    url = f"http://{CFG['ip']}:{CFG['port']}/{PUP_NAME}"
    lines = ["# hfw-proxy"]
    for d in DEST_CODES:
        lines.append(f"Dest={d};CompatibleSystemSoftwareVersion={full}-;")
        lines.append(
            f"Dest={d};ImageVersion={CFG['image_version']};"
            f"SystemSoftwareVersion={full};CDN={url};CDN_Timeout=30;"
        )
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (self.client_address[0], fmt % args))
        sys.stdout.flush()

    # ---- interception -------------------------------------------------
    def do_GET(self):
        self._handle(send_body=True)

    def do_HEAD(self):
        self._handle(send_body=False)

    def _handle(self, send_body):
        path = self.path.split("?")[0]
        if path.lower().endswith("ps3-updatelist.txt"):
            return self._send_list(send_body)
        if path.upper().endswith("/" + PUP_NAME) and self._is_ours():
            return self._send_pup(send_body)
        local = "/" + path.split("//", 1)[1].partition("/")[2] if "//" in path else path
        if self._is_ours() and (local == "/pkg" or local.startswith("/pkg/")):
            return self._send_pkg(send_body)
        return self._forward(send_body)

    def _is_ours(self):
        if self.path.startswith("/"):
            return True
        return f"//{CFG['ip']}:{CFG['port']}/" in self.path

    def _send_list(self, send_body):
        body = build_update_list()
        print(">>> Update list requested. Sent the custom one.", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if send_body:
            self.wfile.write(body)
        self.close_connection = True

    def _send_pup(self, send_body):
        self._send_file(PUP_PATH, send_body)

    def _send_pkg(self, send_body):
        """Serve the local 'pkg' folder: an index page plus the files in it."""
        name = urllib.parse.unquote(self.path.split("?")[0].split("/pkg", 1)[1]).strip("/")
        if not name:
            files = sorted(f for f in os.listdir(PKG_DIR) if f.lower().endswith(".pkg")) if os.path.isdir(PKG_DIR) else []
            rows = "".join('<p><a href="/pkg/%s">%s</a> (%d MB)</p>' % (
                urllib.parse.quote(f), f, os.path.getsize(os.path.join(PKG_DIR, f)) // 1048576 + 1) for f in files)
            body = ("<html><head><title>PS3 packages</title></head><body style='font-size:28px'>"
                    "<h2>PS3 packages</h2>%s</body></html>" % (rows or "<p>No .pkg files in the pkg folder.</p>")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if send_body:
                self.wfile.write(body)
            return
        path = os.path.join(PKG_DIR, os.path.basename(name))
        self._send_file(path, send_body)

    def _send_file(self, file_path, send_body):
        if not os.path.isfile(file_path):
            self.send_error(404, "File not found on the PC")
            return
        size = os.path.getsize(file_path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        partial = False
        if rng and rng.startswith("bytes="):
            try:
                a, b = rng[6:].split("-", 1)
                if a:
                    start = int(a)
                    if b:
                        end = min(int(b), size - 1)
                else:
                    start = max(0, size - int(b))
                partial = True
            except ValueError:
                start, end, partial = 0, size - 1, False
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = end - start + 1
        print(f">>> Sending {os.path.basename(file_path)} (bytes {start}-{end} of {size}).", flush=True)
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not send_body:
            return
        with open(file_path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionError, OSError):
                    print(">>> Download interrupted by the console.", flush=True)
                    self.close_connection = True
                    return
                left -= len(chunk)
        print(">>> Transfer finished.", flush=True)

    # ---- plain pass-through for everything else -----------------------
    def _forward(self, send_body):
        if not self.path.lower().startswith("http://"):
            self.send_error(400, "This is a proxy. Use it as a proxy server.")
            return
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("proxy-connection", "connection", "keep-alive")}
        req = urllib.request.Request(self.path, headers=headers, method=self.command)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=30) as resp:
                self._relay(resp.status, resp, send_body)
        except urllib.error.HTTPError as e:
            self._relay(e.code, e, send_body)
        except Exception as e:  # network errors
            self.send_error(502, f"Upstream error: {e}")

    def _relay(self, status, resp, send_body):
        self.send_response(status)
        for k, v in resp.headers.items():
            if k.lower() in ("transfer-encoding", "connection", "keep-alive"):
                continue
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if send_body:
            try:
                shutil.copyfileobj(resp, self.wfile)
            except (ConnectionError, OSError):
                pass

    def do_CONNECT(self):
        host, _, port = self.path.partition(":")
        try:
            upstream = socket.create_connection((host, int(port or 443)), timeout=30)
        except Exception as e:
            self.send_error(502, f"Cannot connect: {e}")
            return
        self.send_response(200, "Connection established")
        self.end_headers()
        self.close_connection = True
        socks = [self.connection, upstream]
        try:
            while True:
                readable, _, errored = select.select(socks, [], socks, 60)
                if errored or not readable:
                    break
                for s in readable:
                    data = s.recv(65536)
                    if not data:
                        return
                    (upstream if s is self.connection else self.connection).sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()


class Tee:
    """Write everything to the console and to proxy.log."""
    def __init__(self, stream, path):
        self.stream = stream
        self.file = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, data):
        self.stream.write(data)
        self.file.write(data)

    def flush(self):
        self.stream.flush()
        self.file.flush()


def read_pup(path):
    """Return (version string, image version int) from a PUP file header."""
    with open(path, "rb") as f:
        header = f.read(0x30)
        if header[:5] != b"SCEUF":
            raise ValueError("not a PUP file")
        image_version = struct.unpack(">Q", header[0x10:0x18])[0]
        count = struct.unpack(">Q", header[0x18:0x20])[0]
        version = None
        for _ in range(count):
            entry_id, offset, size, _pad = struct.unpack(">QQQQ", f.read(0x20))
            if entry_id == 0x100:  # version.txt
                pos = f.tell()
                f.seek(offset)
                version = f.read(size).decode("ascii", "replace").strip()
                f.seek(pos)
        return version, image_version


def lan_addresses():
    """Best guess for this PC's LAN address first, then the other candidates."""
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # no packet is sent
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in found and not ip.startswith(("127.", "169.254.")):
                found.append(ip)
    except OSError:
        pass
    return found


def main():
    ap = argparse.ArgumentParser(description="PS3 firmware update proxy")
    ap.add_argument("--ip", help="this PC's LAN address as the PS3 sees it (default: auto)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--version", help="version to announce, e.g. 4.94 (default: one above the PUP)")
    ap.add_argument("--image-version", help="build to announce, 8 hex digits (default: above the PUP)")
    args = ap.parse_args()

    sys.stdout = Tee(sys.stdout, os.path.join(HERE, "proxy.log"))
    print("==== started " + time.strftime("%Y-%m-%d %H:%M:%S") + " ====")

    version, image_version = args.version, args.image_version
    if os.path.isfile(PUP_PATH):
        try:
            pup_version, pup_build = read_pup(PUP_PATH)
        except (ValueError, OSError, struct.error) as e:
            sys.exit(f"{PUP_NAME} could not be read: {e}")
        h = hashlib.md5()
        with open(PUP_PATH, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        print(f"Firmware: {pup_version} (build {pup_build:08x}), MD5 {h.hexdigest()}")
        # The PS3 only takes an update whose version and build are above its own,
        # so announce slightly more than the file really is.
        if not version:
            major, _, minor = (pup_version or "4.93").partition(".")
            version = f"{int(major)}.{int(minor[:2] or 0) + 1:02d}"
        if not image_version:
            image_version = f"{pup_build + 0x100:08x}"
    else:
        print(f"No {PUP_NAME} next to the script. Only the pkg page will work.")
        version = version or "4.94"
        image_version = image_version or "00010c00"

    ips = lan_addresses()
    ip = args.ip or (ips[0] if ips else None)
    if not ip:
        sys.exit("Could not find a LAN address. Pass one with --ip.")
    CFG.update(ip=ip, port=args.port, version=version, image_version=image_version)

    print(f"Announcing {version} (build {image_version})")
    print(f"\nPS3 proxy server: {ip}  port: {args.port}")
    if not args.ip and len(ips) > 1:
        print(f"Other addresses on this PC: {', '.join(ips[1:])}. Use --ip if that one is wrong.")
    print(f"Packages for the PS3 browser: http://{ip}:{args.port}/pkg\n", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
