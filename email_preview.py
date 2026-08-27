#!/usr/bin/env python3
r"""email_preview.py FILE.html [--out DIR] [--widths 700,390]

Render an HTML email the ways a recipient can actually receive it, in an
isolated headless Chrome (its own debug port and scratch profile, so it never
touches a browser you are using).

For each width it captures:
    <name>-<w>-light.png   normal
    <name>-<w>-dark.png    prefers-color-scheme: dark emulated
    <name>-<w>-noimg.png   every <img> src broken, i.e. images blocked (the
                           DEFAULT in Outlook and in Gmail for unknown
                           senders) -- this is the render that decides whether
                           the email still makes sense, so it is not optional
and reports horizontal overflow plus the image/text ratio, the two things that
break an email in the wild. Exit code 1 if any width overflows.

Requires: Python 3.8+, the websocket-client package, and a Chrome or Chromium
binary (set CHROME_PATH if it is somewhere unusual).
"""
import argparse, base64, json, os, shutil, subprocess, tempfile, time
import urllib.request
import websocket  # pip install websocket-client


def find_chrome():
    """Locate a Chrome/Chromium binary: CHROME_PATH env var, then common
    install locations (Windows/macOS/Linux), then PATH."""
    p = os.environ.get("CHROME_PATH")
    if p:
        if os.path.isfile(p):
            return p
        raise RuntimeError("CHROME_PATH is set but does not exist: %s" % p)
    candidates = [
        # Windows
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"Google\Chrome\Application\chrome.exe"),
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        # Linux
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError(
        "no Chrome/Chromium found. Install Google Chrome or Chromium, or set "
        "CHROME_PATH to the full path of the browser binary.")


def http_json(port, path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path),
                                timeout=6) as r:
        return json.load(r)


class Chrome:
    """A private headless Chrome with a throwaway profile.

    Launched with --remote-debugging-port=0 so the OS picks a free port
    (read back from the DevToolsActivePort file Chrome writes into the
    profile); two runs can never collide, and we never attach to a browser
    we did not start.
    """

    def __init__(self):
        self.profile = tempfile.mkdtemp(prefix="emailprev-")
        self.proc = subprocess.Popen(
            [find_chrome(), "--remote-debugging-port=0",
             "--user-data-dir=%s" % self.profile, "--headless=new",
             "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             "--remote-allow-origins=*", "--hide-scrollbars", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = os.path.join(self.profile, "DevToolsActivePort")
        ws_url = None
        for _ in range(80):
            try:
                with open(port_file) as fh:
                    port = int(fh.readline().strip())
                for t in http_json(port, "/json"):
                    if t.get("type") == "page":
                        ws_url = t["webSocketDebuggerUrl"]
                        break
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not ws_url:
            raise RuntimeError("headless Chrome did not come up")
        self.ws = websocket.create_connection(ws_url, timeout=20,
                                              max_size=None)
        self.n = 0

    def cmd(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method,
                                 "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                return m

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        # terminate only the exact process we started, by handle
        for fn in (self.proc.terminate, self.proc.kill):
            try:
                fn()
                time.sleep(0.4)
            except Exception:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)


MEASURE = r"""(function(){
  var d=document.documentElement, sw=d.scrollWidth, cw=d.clientWidth, off=[];
  var all=document.querySelectorAll('body *');
  for (var k=0;k<all.length;k++){
    var e=all[k], r=e.getBoundingClientRect();
    if (r.right > cw + 1 && r.width > 0)
      off.push({tag:e.tagName.toLowerCase(), right:Math.round(r.right),
                txt:(e.textContent||'').replace(/\s+/g,' ').trim().slice(0,40)});
  }
  off.sort(function(a,b){return b.right-a.right;});
  var imgs=document.images.length, px=0;
  for (var j=0;j<document.images.length;j++){
    var b=document.images[j].getBoundingClientRect(); px += b.width*b.height;
  }
  return JSON.stringify({scrollWidth:sw, clientWidth:cw, overflow: sw>cw+1,
    offenders:off.slice(0,8), images:imgs, imagePx:Math.round(px),
    chars:(document.body.innerText||'').replace(/\s+/g,' ').trim().length,
    text:(document.body.innerText||'').replace(/\s+/g,' ').trim().slice(0,140)});
})()"""


def shoot(ch, url, width, out, dark=False, noimg=False):
    ch.cmd("Page.enable")
    ch.cmd("Emulation.setDeviceMetricsOverride",
           {"width": width, "height": 900, "deviceScaleFactor": 2,
            "mobile": width < 500})
    ch.cmd("Emulation.setEmulatedMedia",
           {"media": "screen", "features": [{"name": "prefers-color-scheme",
                                             "value": "dark" if dark else "light"}]})
    ch.cmd("Page.navigate", {"url": url})
    time.sleep(1.4)
    if noimg:
        # Truly simulate a blocking client: break every src so the alt text is
        # what renders. (Blocking the URL does not work for data: URIs.)
        ch.cmd("Runtime.evaluate", {"expression":
               "Array.prototype.forEach.call(document.images,function(i){"
               "i.src='data:image/gif;base64,BROKEN';});"})
        time.sleep(0.6)
    r = ch.cmd("Runtime.evaluate", {"expression": MEASURE,
                                    "returnByValue": True})
    info = json.loads(r["result"]["result"]["value"])
    img = ch.cmd("Page.captureScreenshot", {"format": "png",
                                            "captureBeyondViewport": True})
    with open(out, "wb") as fh:
        fh.write(base64.b64decode(img["result"]["data"]))
    return info


def main():
    ap = argparse.ArgumentParser(
        description="Render an HTML email the ways recipients actually "
                    "receive it: light, dark, images blocked, per width.")
    ap.add_argument("file", help="the HTML email file to render")
    ap.add_argument("--out", help="output directory (default: ./render next "
                                  "to the input file)")
    ap.add_argument("--widths", default="700,390",
                    help="comma-separated viewport widths (default: 700,390)")
    a = ap.parse_args()
    src = os.path.abspath(a.file)
    if not os.path.isfile(src):
        ap.error("no such file: %s" % src)
    out = a.out or os.path.join(os.path.dirname(src), "render")
    os.makedirs(out, exist_ok=True)
    url = "file:///" + src.replace("\\", "/")
    stem = os.path.splitext(os.path.basename(src))[0]

    ch = Chrome()
    bad = 0
    try:
        for w in [int(x) for x in a.widths.split(",")]:
            for label, kw in (("light", {}), ("dark", {"dark": True}),
                              ("noimg", {"noimg": True})):
                p = os.path.join(out, "%s-%d-%s.png" % (stem, w, label))
                i = shoot(ch, url, w, p, **kw)
                flag = "OVERFLOW" if i["overflow"] else "ok"
                if i["overflow"]:
                    bad += 1
                print("%4dpx %-6s %-8s scrollW=%-5d imgs=%d imgPx=%-7d chars=%d"
                      % (w, label, flag, i["scrollWidth"], i["images"],
                         i["imagePx"], i["chars"]))
                if i["overflow"]:
                    print("        offenders:", i["offenders"])
                if label == "noimg":
                    print("        images-off text begins: %r" % i["text"][:110])
                print("        ->", p)
    finally:
        ch.close()
    print("\n%s" % ("OVERFLOW FOUND" if bad
                    else "no horizontal overflow at any width"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
