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

        logs.append(line.strip())
        yield "\n".join(logs[-40:])

    process.wait()

    yield "✅ DONE" if process.returncode == 0 else "❌ FAILED"


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
def crawl(base_url, max_page, progress=gr.Progress()):
    global QUEUE
    QUEUE = []

    max_page = int(max_page)
    logs = []

    folder = get_folder_name(base_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        base_url = urljoin(base_url, ".")

        page.goto(base_url + f"1.html")
        page.wait_for_timeout(2000)

        for i in range(1, max_page + 1):
            # if base_url.endswith("1.html"):
            #     url = base_url.replace("1.html", f"{i}.html")
            # else:
            #     url = base_url.rstrip("/") + f"/{i}.html"

            url = base_url + f"{i}.html"

            progress(i / max_page, desc=f"Crawling {i}/{max_page}")

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)

                media = extract_media_url(page)

                if media:
                    QUEUE.append(media)
                    logs.append(f"[{i}] FOUND")
                else:
                    logs.append(f"[{i}] EMPTY")

                yield "\n".join(logs[-50:]), "\n".join(QUEUE)

            except Exception as e:
                logs.append(f"[{i}] ERROR {e}")
                yield "\n".join(logs[-50:]), "\n".join(QUEUE)

        browser.close()

    yield "🎉 CRAWL DONE", "\n".join(QUEUE)


# -------------------------------------------------------
# 2. DOWNLOAD
# -------------------------------------------------------
def download(queue_text, base_url, progress=gr.Progress()):

    urls = [u.strip() for u in queue_text.splitlines() if u.strip()]

    if not urls:
        yield "Empty queue"
        return

    logs = []

    folder = get_folder_name(base_url)
    save_dir = os.path.join(OUTPUT_ROOT, folder)
    os.makedirs(save_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://example.com")
        page.wait_for_timeout(1000)

        headers = {
            "user_agent": page.evaluate("navigator.userAgent"),
            "referer": base_url,
            "cookie_header": "",
        }

        total = len(urls)

        for i, url in enumerate(urls, 1):

            progress(i / total, desc=f"Downloading {i}/{total}")

            name = f"video_{i}"
            output = os.path.join(save_dir, f"{name}.mp4")

            logs.append(f"[{i}/{total}] {name}")
            yield "\n".join(logs[-60:])

            for out in run_ffmpeg(url, output, headers):
                logs[-1] = out
                yield "\n".join(logs[-60:])

        browser.close()

    yield "🎉 DOWNLOAD COMPLETE"


# -------------------------------------------------------
# UI
# -------------------------------------------------------
with gr.Blocks(title="Crawler Pipeline") as app:

    gr.Markdown("# 🎥 Crawl → Queue → Download Pipeline")

    base_url = gr.Textbox(label="Base URL")
    max_page = gr.Number(value=10, label="Max Pages")

    crawl_btn = gr.Button("1️⃣ Crawl")

    crawl_log = gr.Textbox(label="Crawler Log", lines=12)
    queue_box = gr.Textbox(label="Queue", lines=10)

    download_btn = gr.Button("2️⃣ Download")

    download_log = gr.Textbox(label="Download Log", lines=15)

    crawl_btn.click(
        crawl,
        inputs=[base_url, max_page],
        outputs=[crawl_log, queue_box],
    )

    download_btn.click(
        download,
        inputs=[queue_box, base_url],
        outputs=download_log,
    )


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)
