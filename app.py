import requests
import os
import sys
import subprocess
import asyncio
import json
import gradio as gr
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
# from urllib.parse import urljoin

# Handle PyInstaller --windowed mode where stdout/stderr might be None
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

OUTPUT_ROOT = "download"
os.makedirs(OUTPUT_ROOT, exist_ok=True)

QUEUE = []
RESULTS_FILE = "results.json"


# -------------------------------------------------------
# results.json tracking
# -------------------------------------------------------
def load_results(filepath):
    """Load the results.json file, return a list of records."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_results(filepath, records):
    """Save records list to results.json."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def is_downloaded(filepath, url):
    """Check if a base URL has already been downloaded."""
    records = load_results(filepath)
    return any(r.get("url") == url for r in records)


def add_result(filepath, name, url, folder):
    """Add a download record to results.json."""
    records = load_results(filepath)
    records.append({"name": name, "url": url, "folder": folder})
    save_results(filepath, records)


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
    filename = parts[-2] if len(parts) >= 2 else "video"
    return filename.split("_")[-1] if "_" in filename else filename


# -------------------------------------------------------
# CRAWL RECURSIVE (Logic from crawler.py)
# -------------------------------------------------------
async def fetch_player_data(url: str):
    try:
        process = await asyncio.create_subprocess_exec(
            "curl", "-s", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        html = stdout.decode("utf-8", errors="ignore")

        soup = BeautifulSoup(html, "html.parser")
        
        cover = ""
        title = ""
        pages = ""

        anchor = soup.select_one(".album-title a")
        if anchor:
            title = anchor.get_text(strip=True)

        image = soup.select_one(".album-poster img")
        if image:
            cover = image.get("src")

        section = soup.select_one(".selections-info")
        if section:
            pages = section.get_text(strip=True)
            pages = pages.split('集')[0]

        # Extract player data
        start = html.find("var player_aaaa=")
        if start == -1:
            return None, title, cover, pages

        start = html.find("{", start)
        i = start
        depth = 0
        end = -1
        while i < len(html):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1

        if end == -1:
            return None, title, cover, pages

        json_str = html[start:end]
        return json.loads(json_str), title, cover, pages
    except Exception as e:
        print(f"    [Curl] Error: {e}")
        return None, ""


async def crawl_recursive(base_url, output_dir=OUTPUT_ROOT, progress=gr.Progress()):
    global QUEUE
    QUEUE = []
    logs = []

    parsed = urlparse(base_url)
    site_base = f"{parsed.scheme}://{parsed.netloc}"

    current_url = base_url
    visited = set()
    title = ""

    print(f"\n🚀 STARTING RECURSIVE CRAWL: {base_url}")

    folder = get_folder_name(base_url)
    save_dir = os.path.join(output_dir, folder)
    os.makedirs(save_dir, exist_ok=True)

    while current_url and current_url not in visited:
        visited.add(current_url)
        i = len(visited)
        progress(0, desc=f"Crawling {i}...")

        print(f"  [{i}] Fetching: {current_url}")
        data, new_title, cover, pages = await fetch_player_data(current_url)

        if i == 1 and cover:
            title = new_title
            image_url = site_base + cover
            with open(os.path.join(save_dir, f"thumb.jpg")  , "wb") as f:
                f.write(requests.get(image_url).content)

        if data:
            if data.get("url"):
                media_url = data["url"]

            # NOTE: same as new_title
            # if data.get("vod_data"):
            #     title = data["vod_data"]["vod_name"]

            QUEUE.append(media_url)
            msg = f"[{i}] ✅ FOUND: {media_url}"
            logs.append(msg)
            print(f"      {msg}")
        else:
            msg = f"[{i}] ⚠️ EMPTY or FAILED"
            logs.append(msg)
            print(f"      {msg}")

        yield "\n".join(logs[-50:]), "\n".join(QUEUE), title, i

        if data and data.get("link_next"):
            current_url = site_base + data["link_next"]
        else:
            current_url = None

    print("🎉 RECURSIVE CRAWL DONE\n")
    yield "🎉 CRAWL DONE", "\n".join(QUEUE), title, len(visited)

# -------------------------------------------------------
# FFmpeg runner
# -------------------------------------------------------
def run_ffmpeg(url, output, headers):
    cmd = [
        # fmt: off
        "ffmpeg", "-y",
        "-referer", headers["referer"],
        "-headers", headers["cookie_header"],
        "-user_agent", headers["user_agent"],
        "-i", url,
        "-c", "copy",
        output,
        "-loglevel", "error",
        # fmt: on
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    logs = []

    try:
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
    finally:
        if process.poll() is None:
            print(f"    [FFmpeg] Terminating process for {output}...")
            process.terminate()
            process.wait()

    status = "✅ DONE" if process.returncode == 0 else "❌ FAILED"
    print(f"    [FFmpeg] {status}")
    yield status

# -------------------------------------------------------
# 1. CRAWL (ASYNC)
# -------------------------------------------------------
async def crawl(base_url, max_page_input, headless, progress=gr.Progress()):
    global QUEUE
    QUEUE = []

    current_max = int(max_page_input)
    title = ""
    logs = []

    print(f"\n🚀 STARTING CRAWL: {base_url} (Max: {current_max}, Headless: {headless})")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        # Ensure base_url ends correctly for concatenation
        if not base_url.endswith("/"):
            # If it ends with something like .html, get the directory
            parsed = urlparse(base_url)
            if parsed.path and "." in parsed.path.split("/")[-1]:
                base_url = urljoin(base_url, ".")

        i = 1
        while i <= current_max:
            url = urljoin(base_url, f"{i}.html")

            progress(i / current_max, desc=f"Crawling {i}/{current_max}")
            print(f"  [{i}/{current_max}] Visiting: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1500)

                # Detect Title and Max Page
                try:
                    new_title = await page.eval_on_selector(
                        ".album-title",
                        "el => el.innerText.trim()"
                    )
                    if new_title:
                        title = new_title

                    detected_max = await page.eval_on_selector(
                        ".selections-info",
                        """
                        el => {
                            const text = el.innerText || "";
                            const match = text.match(/(\\d+)\\s*集/);
                            return match ? parseInt(match[1], 10) : 0;
                        }
                        """
                    )
                    if detected_max > 0:
                        current_max = detected_max
                except:
                    pass

                # extract_media_url needs to be async too
                media = await extract_media_url_async(page)

                if media:
                    QUEUE.append(media)
                    msg = f"[{i}] ✅ FOUND: {media}"
                    logs.append(msg)
                    print(f"      {msg}")
                else:
                    msg = f"[{i}] ⚠️ EMPTY"
                    logs.append(msg)
                    print(f"      {msg}")

                # Single yield per page to minimize flickering
                yield "\n".join(logs[-50:]), "\n".join(QUEUE), title, current_max

            except Exception as e:
                msg = f"[{i}] ❌ ERROR: {e}"
                logs.append(msg)
                print(f"      {msg}")
                yield "\n".join(logs[-50:]), "\n".join(QUEUE), title, current_max
            
            i += 1

        await browser.close()

    print("🎉 CRAWL DONE\n")
    yield "🎉 CRAWL DONE", "\n".join(QUEUE), title, current_max


# -------------------------------------------------------
# extract function (ASYNC)
# -------------------------------------------------------
async def extract_media_url_async(page):
    try:
        data = await page.evaluate("() => window.player_aaaa || null")
        if data and isinstance(data, dict) and data.get("url"):
            return data["url"]
    except:
        pass

    try:
        m3u8 = await page.evaluate("""
            () => {
                const el = document.querySelector('#shortmovs-videojs-player_html5_api');
                return el ? el.getAttribute('src') : null;
            }
        """)
        if m3u8:
            return m3u8
    except:
        pass
    return None


# -------------------------------------------------------
# 2. DOWNLOAD (ASYNC)
# -------------------------------------------------------
async def download(queue_text, base_url, headless, output_dir=OUTPUT_ROOT, title="", results_file=None, progress=gr.Progress()):

    urls = [u.strip() for u in queue_text.splitlines() if u.strip()]

    if not urls:
        print("⚠️ Download started with empty queue")
        yield "Empty queue"
        return

    logs = []

    folder = get_folder_name(base_url)
    save_dir = os.path.join(output_dir, folder)
    os.makedirs(save_dir, exist_ok=True)

    print(
        f"\n📥 STARTING DOWNLOAD: {len(urls)} items -> {save_dir} (Headless: {headless})"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        # Just to get headers/UA
        await page.goto("https://www.google.com")
        headers = {
            "user_agent": await page.evaluate("navigator.userAgent"),
            "referer": base_url,
            "cookie_header": "",
        }

        total = len(urls)

        for i, url in enumerate(urls, 1):
            progress(i / total, desc=f"Downloading {i}/{total}")

            name = get_video_name(url)
            output = os.path.join(save_dir, f"{name}.mp4")

            print(f"  [{i}/{total}] {name} ...")
            logs.append(f"[{i}/{total}] Starting: {name}")
            yield "\n".join(logs[-60:])

            # run_ffmpeg is a sync generator, so we use a sync loop
            for out in run_ffmpeg(url, output, headers):
                logs[-1] = f"[{i}/{total}] {out}"
                yield "\n".join(logs[-60:])

            print(f"      Finished: {output}")

        await browser.close()

    # Record to results.json after all episodes downloaded
    if results_file:
        record_name = title if title else folder
        add_result(results_file, record_name, base_url, folder)
        print(f"📝 Recorded to {results_file}: {record_name}")

    print("🎉 DOWNLOAD COMPLETE\n")
    yield "🎉 DOWNLOAD COMPLETE"


# -------------------------------------------------------
# 3. COMBINED (ASYNC)
# -------------------------------------------------------
async def combined_handler(queue_text, base_urls_text, movie_title_val, output_dir_val, progress=gr.Progress()):
    output_dir = output_dir_val.strip() if output_dir_val and output_dir_val.strip() else OUTPUT_ROOT
    os.makedirs(output_dir, exist_ok=True)

    results_file = os.path.join(output_dir, RESULTS_FILE)

    # Split base URLs by newline — support multiple URLs
    base_urls = [u.strip() for u in base_urls_text.splitlines() if u.strip()]
    if not base_urls:
        yield "No URLs provided.", queue_text, movie_title_val, gr.update(visible=True), gr.update(visible=False)
        return

    headless = True
    current_queue = queue_text
    current_title = movie_title_val
    total_urls = len(base_urls)

    try:
        # Initial state: Show Cancel, Hide Download
        yield "Starting...", current_queue, current_title, gr.update(visible=False), gr.update(visible=True)

        for url_idx, base_url in enumerate(base_urls, 1):
            prefix = f"[{url_idx}/{total_urls}]" if total_urls > 1 else ""

            # Check if already downloaded
            if is_downloaded(results_file, base_url):
                msg = f"{prefix} ⏭️ SKIPPED (already downloaded): {base_url}"
                print(msg)
                yield msg, current_queue, current_title, gr.update(visible=False), gr.update(visible=True)
                continue

            print(f"\n{prefix} 🔗 Processing: {base_url}")
            yield f"{prefix} 🔗 Processing: {base_url}", current_queue, current_title, gr.update(visible=False), gr.update(visible=True)

            # Crawl
            async for logs, queue, title, m_page in crawl_recursive(base_url, output_dir, progress):
                current_queue = queue
                current_title = title
                yield f"{prefix} {logs}", current_queue, current_title, gr.update(visible=False), gr.update(visible=True)

            urls = [u.strip() for u in current_queue.splitlines() if u.strip()]
            if not urls:
                yield f"{prefix} No media URLs found for: {base_url}", current_queue, current_title, gr.update(visible=False), gr.update(visible=True)
                continue

            # Download
            async for logs in download(current_queue, base_url, headless, output_dir, current_title, results_file, progress):
                yield f"{prefix} {logs}", current_queue, current_title, gr.update(visible=False), gr.update(visible=True)

            # Reset queue for next URL
            current_queue = ""
            current_title = ""

        # Final state: Show Download, Hide Cancel
        yield "🎉 ALL DONE", current_queue, current_title, gr.update(visible=True), gr.update(visible=False)

    except Exception as e:
        print(f"Error in combined_handler: {e}")
        yield f"Error: {e}", current_queue, current_title, gr.update(visible=True), gr.update(visible=False)
    finally:
        # This will run even if cancelled
        print("Process ended or cancelled.")



# -------------------------------------------------------
# UI
# -------------------------------------------------------
custom_css = """
#download-btn, #cancel-btn {
    margin-top: 0px;
    height: 90px;
}
"""

with gr.Blocks(title="Video Downloader", theme=gr.themes.Base(), css=custom_css) as app:

    gr.Markdown("# 🎥 The https://www.shortmovs.com/ Downloader")

    with gr.Row():
        base_url = gr.Textbox(
            label="Base URLs (one per line)", 
            placeholder="https://example.com/path/1/\nhttps://example.com/path/2/",
            lines=3,
            max_lines=5,
            scale=4,
        )
        download_btn = gr.Button("Download", variant="primary", scale=1, elem_id="download-btn")
        cancel_btn = gr.Button("Cancel", variant="stop", scale=1, elem_id="cancel-btn", visible=False)

    with gr.Row():
        movie_title = gr.Textbox(label="Detected Movie Title", interactive=False)
        output_dir = gr.Textbox(
            label="Output Directory",
            value=OUTPUT_ROOT,
            placeholder="download",
        )

    queue_box = gr.Textbox(label="Queue (URLs found)", lines=5, max_lines=5)

    all_logs = gr.Textbox(label="Logs", lines=10, max_lines=10, interactive=False)

    download_event = download_btn.click(
        combined_handler,
        inputs=[queue_box, base_url, movie_title, output_dir],
        outputs=[all_logs, queue_box, movie_title, download_btn, cancel_btn],
        show_progress="minimal"
    )

    cancel_btn.click(
        fn=lambda: (gr.update(visible=True), gr.update(visible=False), "🛑 Cancelled by user.", "", ""),
        inputs=None,
        outputs=[download_btn, cancel_btn, all_logs, queue_box, movie_title],
        cancels=[download_event]
    )


if __name__ == "__main__":
    app.launch(server_name="127.0.0.1", inbrowser=True)
