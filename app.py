import re
import time
import subprocess
import gradio as gr
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

HEADERS = {"User-Agent": "Mozilla/5.0"}


# ======================================================
# CLEAN URL
# ======================================================
def clean_url(url: str):
    if not url:
        return None

    url = re.sub(r"https:\s*/\s*/", "https://", url)
    url = url.replace("\\/", "/")
    url = url.replace("https:/", "https://")
    return url


# ======================================================
# EXTRACT FROM DOM (YOUR REQUIREMENT)
# ======================================================
def extract_from_dom(page, url):
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(3000)

    src = page.evaluate("""
        () => {
            const el = document.querySelector('#shortmovs-videojs-player_html5_api');
            return el ? el.getAttribute('src') : null;
        }
    """)

    return clean_url(src)


# ======================================================
# STATIC PAGE CRAWLER (1.html -> 2.html ...)
# ======================================================
def build_next(url):
    match = re.search(r"(\d+)\.html", url)
    if not match:
        return None
    n = int(match.group(1))
    return re.sub(r"\d+\.html", f"{n+1}.html", url)


def scan_dom_pages(start_url: str, max_pages: int):
    results = []
    visited = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        queue = [start_url]

        while queue and len(visited) < max_pages:
            url = queue.pop(0)

            if url in visited:
                continue

            visited.add(url)

            try:
                src = extract_from_dom(page, url)

                if src and "m3u8" in src:
                    results.append(src)

                # auto next page
                nxt = build_next(url)
                if nxt and nxt not in visited:
                    queue.append(nxt)

            except Exception as e:
                print("Error:", url, e)

        browser.close()

    return sorted(set(results))


# ======================================================
# WRAPPER
# ======================================================
def extract(url, pages):
    if not url:
        return ""

    try:
        pages = int(pages)
    except:
        pages = 10

    return "\n".join(scan_dom_pages(url, pages))


# ======================================================
# BATCH DOWNLOAD
# ======================================================
def batch_download(text, prefix):
    if not text.strip():
        return "No URLs found"

    urls = [x.strip() for x in text.split("\n") if x.strip()]
    total = len(urls)

    logs = []

    for i, url in enumerate(urls, 1):
        output = f"{prefix}_{i}.mp4"

        cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy", output]

        try:
            subprocess.run(
                cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            logs.append(f"[{i}/{total}] SUCCESS → {output}")
        except:
            logs.append(f"[{i}/{total}] FAILED → {url}")

        time.sleep(0.2)

    return "\n".join(logs)


# ======================================================
# GRADIO UI
# ======================================================
with gr.Blocks(title="Shortmovs DOM Extractor") as app:

    gr.Markdown("## 🎥 DOM Video Extractor + Batch Downloader")

    url_input = gr.Textbox(label="Start URL (e.g. 60.html)")

    pages_input = gr.Number(label="Max Pages", value=10, precision=0)

    btn_extract = gr.Button("Extract Video URLs")

    output = gr.Textbox(label="Extracted m3u8 URLs", lines=12)

    prefix = gr.Textbox(label="Output Prefix", value="video")

    btn_download = gr.Button("Download All (FFmpeg)")

    download_log = gr.Textbox(label="Progress Log", lines=12)

    # actions
    btn_extract.click(fn=extract, inputs=[url_input, pages_input], outputs=output)

    btn_download.click(fn=batch_download, inputs=[output, prefix], outputs=download_log)


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)
