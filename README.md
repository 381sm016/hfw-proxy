# hfw-proxy

Install PS3 firmware over your home network instead of a USB stick.

Run it on a PC, type the PC's address into the PS3's proxy setting, and
"Update via Internet" installs whatever `PS3UPDAT.PUP` you gave it. Made for
getting HFW onto a console for PS3HEN, but it serves any PUP the console accepts.

It also hosts `.pkg` files for the PS3 browser, so homebrew installs don't
need a stick either.

Tested on a CECH-2504B going from OFW 4.93 to HFW 4.93.1.

## Usage

Needs Python 3. No other dependencies.

1. Put your firmware next to the script, named `PS3UPDAT.PUP`.
2. Run `python hfw_proxy.py` (or `start.bat` on Windows). It prints the
   address and port to use, and the MD5 of your PUP. Check the MD5.
3. On the PS3: Network Settings > Internet Connection Settings > Custom,
   leave everything on default except Proxy Server > Use. Enter the address
   and port.
4. Settings > System Update > Update via Internet.
5. Set the proxy back to Do Not Use when it's done.

Allow the port (8080 by default) through your firewall if the PS3 can't connect.

## Packages

Drop `.pkg` files into the `pkg` folder and open `http://<pc-address>:8080/pkg`
in the PS3 browser. Download, then install from Package Manager.

## How it works

The PS3 finds updates by fetching `ps3-updatelist.txt` over plain HTTP.
The proxy answers that one request itself with a list pointing at your PUP,
and passes everything else through.

The console ignores the update unless the list's `ImageVersion` build number
is higher than what's installed. Raising the version alone isn't enough. HFW
has the same build number as the OFW it's based on, so the proxy reads
version and build from your PUP and announces slightly higher ones. The PS3 will say it's updating to e.g.
4.94. What gets installed is your file.

## Options

```
--ip             address to announce, if auto-detection picks the wrong one (VPNs do this)
--port           default 8080
--version        version to announce
--image-version  build to announce, 8 hex digits
```

## Warnings

The proxy doesn't check what you feed it. A CFW PUP on a console that can't
run CFW, or without a patched flash, can brick it. If you're not sure, use HFW.

No firmware is included. Get it from the official release threads.

## License

MIT
