"""Record the README's demo animation by driving the real UI in a headless browser.

    pip install playwright pillow && playwright install chromium
    python scripts/record_demo_gif.py https://tradeos-s33z.onrender.com docs/img/demo.gif
    python scripts/record_demo_gif.py http://localhost:8000 docs/img/demo.gif --chromium /path/to/chrome

What it does, in order, exactly as a judge would: opens the inbox (and, if it is empty, clicks "Fill the inbox"),
watches the progress page fill, opens the inbox, opens the honest AI-agent request, approves it as the merchant
(a PayPal Sandbox refund on the hosted demo), and ends on the inbox with the "refunds an AI agent approved" counter.
One frame per moment, assembled into a looping GIF. Nothing is staged: every frame is the page as served.

The page's own environment badges stay in every frame (PayPal Sandbox, or MOCK when recorded locally), so the
animation always says where it was recorded.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

WIDTH, HEIGHT = 1280, 820
OUT_WIDTH = 960


def record(base: str, out: Path, chromium: str | None = None) -> int:
    from playwright.sync_api import sync_playwright

    frames: list[tuple[Path, int]] = []  # (png, milliseconds)
    tmp = Path(tempfile.mkdtemp(prefix="tradeos-gif-"))

    def shot(page, ms: int, top_of=None) -> None:
        """One frame. A frame further down the page keeps the page's own header (with its PayPal Sandbox / MOCK badge)
        on top, so no frame can be mistaken for another environment: header pixels + content pixels, both real."""
        path = tmp / f"{len(frames):02d}.png"
        if top_of is None:
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(path))
        else:
            from PIL import Image
            header_h = round(page.locator("header.topbar").bounding_box()["height"]
                             + page.locator(".demo-ribbon").bounding_box()["height"])
            page.evaluate("window.scrollTo(0, 0)")
            full = tmp / "full.png"
            page.screenshot(path=str(full), full_page=True)
            top = page.locator(top_of).first.evaluate("e => e.getBoundingClientRect().top + window.scrollY")
            img = Image.open(full)
            start = max(header_h, int(top) - 70)
            body = img.crop((0, start, WIDTH, min(img.height, start + HEIGHT - header_h)))
            frame = Image.new("RGB", (WIDTH, header_h + body.height), "white")
            frame.paste(img.crop((0, 0, WIDTH, header_h)), (0, 0))
            frame.paste(body, (0, header_h))
            frame.save(path)
        frames.append((path, ms))

    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": chromium} if chromium else {}))
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.goto(f"{base}/inbox")
        if page.locator('form[action="/demo/fill-inbox"] button').count():
            shot(page, 2200)
            page.click('form[action="/demo/fill-inbox"] button')
            page.wait_for_url("**/agent-runs/**")
            seen = -1
            deadline = time.time() + 180
            while time.time() < deadline:
                if page.locator('[data-status="done"], [data-status="failed"]').count():
                    break
                steps = page.locator("#run-steps li").count()
                if steps != seen and steps in (2, 5):
                    shot(page, 1300)
                    seen = steps
                page.wait_for_timeout(400)
            shot(page, 3200, top_of="#run-final")
            page.click("#run-case")
        else:
            page.goto(f"{base}/inbox")
        page.locator(".ag-row").first.wait_for(timeout=20000)
        page.wait_for_timeout(400)
        shot(page, 3000)

        # The honest agent request: "Needs you" and from an AI agent.
        page.click("[data-inbox-filter=agents]")
        page.wait_for_timeout(400)
        page.locator(".ag-row", has_text="Needs you").locator("[col-id=buyer]").first.click()
        page.wait_for_load_state()
        shot(page, 3200, top_of=".agent-card")
        approve = page.locator('form[action$="/approve"] button')
        if approve.count():
            approve.first.click()
            page.wait_for_load_state()
            shot(page, 3200, top_of=".result-card")
        page.goto(f"{base}/inbox")
        page.locator(".ag-row").first.wait_for(timeout=20000)
        page.click("[data-inbox-filter=all]")
        page.wait_for_timeout(500)
        shot(page, 3800)
        browser.close()

    from PIL import Image
    images = []
    for path, _ in frames:
        raw = Image.open(path).convert("RGB")
        img = Image.new("RGB", (WIDTH, HEIGHT), (245, 247, 251))  # every frame the same size, page background colour
        img.paste(raw.crop((0, 0, WIDTH, min(raw.height, HEIGHT))), (0, 0))
        img = img.resize((OUT_WIDTH, round(img.height * OUT_WIDTH / img.width)), Image.LANCZOS)
        images.append(img.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, save_all=True, append_images=images[1:], duration=[ms for _, ms in frames], loop=0,
                   optimize=True, disposal=1)
    print(f"{out}: {len(images)} frames, {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    chromium = None
    if "--chromium" in argv:
        i = argv.index("--chromium")
        chromium = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) != 2 or not argv[0].startswith(("http://", "https://")) or {"-h", "--help"} & set(sys.argv):
        raise SystemExit(__doc__)
    sys.exit(record(argv[0].rstrip("/"), Path(argv[1]), chromium))
