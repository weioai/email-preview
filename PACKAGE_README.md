# Weio email preview

Weio is operated by AI agents under human ownership; this package was prepared by those agents.

Render a local HTML email in Chromium at several widths, with light mode, dark mode and image-blocking variations. Per render, the script prints horizontal overflow, the image count, the image area and the visible text length, and saves screenshots. Exit code 1 if any width overflows.

Status: alpha, version 0.1.0a2, packaged from the existing [MIT-licensed source](https://github.com/weioai/email-preview). It is not published on PyPI; the `Private :: Do Not Upload` classifier prevents an accidental upload.

## Install and run from this source directory

Requires Python 3.10 or later, websocket-client and a supported Chrome or Chromium executable. Source installation may fetch Python dependencies.

```sh
python -m pip install .
weio-email-preview newsletter.html --out ./render --widths 700,390
```

Use only trusted or sanitized HTML. The renderer launches a separate headless browser profile. HTML may load remote resources; this is not a network-isolation sandbox or a malware scanner. Dark-mode and image-blocking variations are Chromium simulations, not exact Gmail, Outlook or Apple Mail rendering. No email is sent by this command.

The upstream MIT license is retained. Company: [weio.ai](https://weio.ai).
