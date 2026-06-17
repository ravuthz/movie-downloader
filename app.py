import os
import subprocess
import gradio as gr
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

OUTPUT_ROOT = "download"
os.makedirs(OUTPUT_ROOT, exist_ok=True)

QUEUE = []


# -------------------------------------------------------
# derive folder name from URL
# -------------------------------------------------------
def get_folder_name(url: str):
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    return parts[-2] if len(parts) >= 2 else "output"


def get_video_name(url: str):
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    return parts[-2] if len(parts) >= 2 else "video"


# -------------------------------------------------------
# FFmpeg runner
# -------------------------------------------------------
def run_ffmpeg(url, output, headers):
    cmd = [
        "ffmpeg",
        "-y",
        "-user_agent",
        headers["user_agent"],
        "-referer",
        headers["referer"],
        "-headers",
        headers["cookie_header"],
        "-i",
        url,
        "-c",
        "copy",
        output,
        "-loglevel",
        "error",
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    logs = []

    while True:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                break
            continue

        clean_line = line.strip()
        if clean_line:
            print(f"    [FFmpeg] {clean_line}")
            logs.append(clean_line)
            yield "\n".join(logs[-40:])

    process.wait()
    status = "✅ DONE" if process.returncode == 0 else "❌ FAILED"
    print(f"    [FFmpeg] {status}")
    yield status


# -------------------------------------------------------
# extract function (CUSTOMIZE THIS)
# -------------------------------------------------------
def extract_media_url(page):
    # -----------------------------
    # 1. Try player_aaaa (BEST)
    # -----------------------------
    try:
        data = page.evaluate("() => window.player_aaaa || null")
        if data and isinstance(data, dict) and data.get("url"):
            return data["url"]
    except:
        pass

    # -----------------------------
    # 2. Try VideoJS DOM
    # -----------------------------
    try:
        m3u8 = page.evaluate("""
            () => {
                const el = document.querySelector('#shortmovs-videojs-player_html5_api');
                return el ? el.getAttribute('src') : null;
            }
        """)
        if m3u8:
            return m3u8
    except:
        pass


# -------------------------------------------------------
# 1. CRAWL
# -------------------------------------------------------
def crawl(base_url, max_page, headless, progress=gr.Progress()):
    global QUEUE
    QUEUE = []

    max_page = int(max_page)
    logs = []

    print(f"\n🚀 STARTING CRAWL: {base_url} (Max: {max_page}, Headless: {headless})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        # Ensure base_url ends correctly for concatenation
        if not base_url.endswith("/"):
            # If it ends with something like .html, get the directory
            parsed = urlparse(base_url)
            if parsed.path and "." in parsed.path.split("/")[-1]:
                base_url = urljoin(base_url, ".")

        for i in range(1, max_page + 1):
            url = urljoin(base_url, f"{i}.html")

            progress(i / max_page, desc=f"Crawling {i}/{max_page}")
            print(f"  [{i}/{max_page}] Visiting: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1500)

                media = extract_media_url(page)

                if media:
                    QUEUE.append(media)
                    msg = f"[{i}] ✅ FOUND: {media}"
                    logs.append(msg)
                    print(f"      {msg}")
                else:
                    msg = f"[{i}] ⚠️ EMPTY"
                    logs.append(msg)
                    print(f"      {msg}")

                yield "\n".join(logs[-50:]), "\n".join(QUEUE)

            except Exception as e:
                msg = f"[{i}] ❌ ERROR: {e}"
                logs.append(msg)
                print(f"      {msg}")
                yield "\n".join(logs[-50:]), "\n".join(QUEUE)

        browser.close()

    print("🎉 CRAWL DONE\n")
    yield "🎉 CRAWL DONE", "\n".join(QUEUE)


# -------------------------------------------------------
# 2. DOWNLOAD
# -------------------------------------------------------
def download(queue_text, base_url, headless, progress=gr.Progress()):

    urls = [u.strip() for u in queue_text.splitlines() if u.strip()]

    if not urls:
        print("⚠️ Download started with empty queue")
        yield "Empty queue"
        return

    logs = []

    folder = get_folder_name(base_url)
    save_dir = os.path.join(OUTPUT_ROOT, folder)
    os.makedirs(save_dir, exist_ok=True)

    print(
        f"\n📥 STARTING DOWNLOAD: {len(urls)} items -> {save_dir} (Headless: {headless})"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        # Just to get headers/UA
        page.goto("https://www.google.com")
        headers = {
            "user_agent": page.evaluate("navigator.userAgent"),
            "referer": base_url,
            "cookie_header": "",
        }

        total = len(urls)

        for i, url in enumerate(urls, 1):
            progress(i / total, desc=f"Downloading {i}/{total}")

            # name = f"video_{i}"
            name = get_video_name(url)
            output = os.path.join(save_dir, f"{name}.mp4")

            print(f"  [{i}/{total}] {name} ...")
            logs.append(f"[{i}/{total}] Starting: {name}")
            yield "\n".join(logs[-60:])

            for out in run_ffmpeg(url, output, headers):
                logs[-1] = f"[{i}/{total}] {out}"
                yield "\n".join(logs[-60:])

            print(f"      Finished: {output}")

        browser.close()

    print("🎉 DOWNLOAD COMPLETE\n")
    yield "🎉 DOWNLOAD COMPLETE"


# -------------------------------------------------------
# UI
# -------------------------------------------------------
custom_css = """
#max-pages {
    min-width: 100px !important;
    max-width: 100px !important;
    flex: none !important;
}
#headless-toggle {
    margin-top: 0px;
}
"""

import gradio as gr

with gr.Blocks(title="Crawler Pipeline", theme=gr.themes.Base(), css=custom_css) as app:

    gr.Markdown("# 🎥 The https://www.shortmovs.com/ Downloader")

    with gr.Row():
        base_url = gr.Textbox(
            label="Base URL", placeholder="https://example.com/path/", scale=4
        )
        max_page = gr.Number(
            value=10, label="Max Pages", elem_id="max-pages", precision=0
        )

    with gr.Row():
        headless = gr.Checkbox(
            label="Headless", value=True, scale=1, elem_id="headless-toggle"
        )
        crawl_btn = gr.Button("1️⃣ Crawl", variant="primary", scale=5)

    with gr.Row():
        crawl_log = gr.Textbox(label="Crawler Log", lines=12, interactive=False)
        queue_box = gr.Textbox(label="Queue (URLs found)", lines=12)

    download_btn = gr.Button("2️⃣ Download", variant="primary")

    download_log = gr.Textbox(label="Download Log", lines=15, interactive=False)

    crawl_btn.click(
        crawl,
        inputs=[base_url, max_page, headless],
        outputs=[crawl_log, queue_box],
    )

    download_btn.click(
        download,
        inputs=[queue_box, base_url, headless],
        outputs=download_log,
    )


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)
