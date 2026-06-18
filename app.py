import os
import sys
import subprocess
import asyncio
import threading
import queue
import customtkinter as ctk
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

# Handle PyInstaller --windowed mode where stdout/stderr might be None
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# Fix Playwright browser path for bundled EXE
if getattr(sys, 'frozen', False):
    # If running as a bundle, point to the global ms-playwright folder 
    # instead of looking inside the temporary _MEI folder.
    if sys.platform == "win32":
        default_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        if os.path.exists(default_path):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = default_path

OUTPUT_ROOT = "download"
os.makedirs(OUTPUT_ROOT, exist_ok=True)

# -------------------------------------------------------
# Helpers
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
# FFmpeg runner (modified for queue)
# -------------------------------------------------------
def run_ffmpeg(url, output, headers, ui_queue):
    cmd = [
        "ffmpeg", "-y",
        "-referer", headers["referer"],
        "-headers", headers["cookie_header"],
        "-user_agent", headers["user_agent"],
        "-i", url,
        "-c", "copy",
        output,
        "-loglevel", "error",
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    try:
        while True:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue

            clean_line = line.strip()
            if clean_line:
                ui_queue.put({"type": "ffmpeg_log", "msg": clean_line})
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()

    return process.returncode == 0

# -------------------------------------------------------
# Async Logic
# -------------------------------------------------------
async def extract_media_url_async(page):
    # 1. Try common JS object
    try:
        data = await page.evaluate("() => window.player_aaaa || window.player_data || null")
        if data and isinstance(data, dict) and data.get("url"):
            return data["url"]
    except:
        pass

    # 2. Try to find m3u8 in all script tags (regex)
    try:
        content = await page.content()
        import re
        # Look for something like "url": "http...m3u8" or similar patterns
        match = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', content)
        if match:
            return match.group(1).replace("\\/", "/")
    except:
        pass

    # 3. Check iframes (common for video players)
    try:
        frames = page.frames
        for frame in frames:
            # Check frame URL for common player keywords
            if "player" in frame.url or "video" in frame.url or "m3u8" in frame.url:
                # Try to extract from the frame's JS context too
                data = await frame.evaluate("() => window.player_aaaa || window.player_data || null")
                if data and isinstance(data, dict) and data.get("url"):
                    return data["url"]
    except:
        pass

    # 4. Try VideoJS DOM
    try:
        m3u8 = await page.evaluate("""
            () => {
                const el = document.querySelector('#shortmovs-videojs-player_html5_api, video source, video');
                if (!el) return null;
                return el.getAttribute('src') || el.currentSrc || null;
            }
        """)
        if m3u8:
            return m3u8
    except:
        pass
    
    return None

async def crawl(base_url, max_page_input, ui_queue, stop_event):
    current_max = int(max_page_input)
    title = ""
    found_urls = []

    ui_queue.put({"type": "log", "msg": f"🚀 STARTING CRAWL: {base_url}"})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        if not base_url.endswith("/"):
            parsed = urlparse(base_url)
            if parsed.path and "." in parsed.path.split("/")[-1]:
                base_url = urljoin(base_url, ".")

        i = 1
        while i <= current_max:
            if stop_event.is_set():
                break

            url = urljoin(base_url, f"{i}.html")
            ui_queue.put({"type": "log", "msg": f"  [{i}/{current_max}] Visiting: {url}"})

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2500)

                # Detect Title and Max Page
                try:
                    new_title = await page.eval_on_selector(".album-title", "el => el.innerText.trim()")
                    if new_title:
                        title = new_title
                        ui_queue.put({"type": "title", "msg": title})

                    detected_max = await page.eval_on_selector(
                        ".selections-info",
                        "el => { const text = el.innerText || ''; const match = text.match(/(\\d+)\\s*集/); return match ? parseInt(match[1], 10) : 0; }"
                    )
                    if detected_max > 0:
                        current_max = detected_max
                except:
                    pass

                media = await extract_media_url_async(page)
                if media:
                    found_urls.append(media)
                    ui_queue.put({"type": "queue_update", "msg": "\n".join(found_urls)})
                    ui_queue.put({"type": "log", "msg": f"[{i}] ✅ FOUND: {media}"})
                else:
                    ui_queue.put({"type": "log", "msg": f"[{i}] ⚠️ EMPTY"})

            except Exception as e:
                ui_queue.put({"type": "log", "msg": f"[{i}] ❌ ERROR: {e}"})
            
            i += 1

        await browser.close()

    ui_queue.put({"type": "log", "msg": "🎉 CRAWL DONE"})
    return found_urls

async def download(urls, base_url, ui_queue, stop_event):
    if not urls:
        ui_queue.put({"type": "log", "msg": "⚠️ Download started with empty queue"})
        return

    folder = get_folder_name(base_url)
    save_dir = os.path.join(OUTPUT_ROOT, folder)
    os.makedirs(save_dir, exist_ok=True)

    ui_queue.put({"type": "log", "msg": f"📥 STARTING DOWNLOAD: {len(urls)} items -> {save_dir}"})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://www.google.com")
        headers = {
            "user_agent": await page.evaluate("navigator.userAgent"),
            "referer": base_url,
            "cookie_header": "",
        }

        total = len(urls)
        for i, url in enumerate(urls, 1):
            if stop_event.is_set():
                break

            name = get_video_name(url)
            output = os.path.join(save_dir, f"{name}.mp4")

            ui_queue.put({"type": "log", "msg": f"[{i}/{total}] Starting: {name}"})
            
            # Run FFmpeg in a thread to not block the async loop
            success = await asyncio.to_thread(run_ffmpeg, url, output, headers, ui_queue)
            
            if success:
                ui_queue.put({"type": "log", "msg": f"[{i}/{total}] ✅ DONE"})
            else:
                ui_queue.put({"type": "log", "msg": f"[{i}/{total}] ❌ FAILED"})

        await browser.close()

    ui_queue.put({"type": "log", "msg": "🎉 DOWNLOAD COMPLETE"})

# -------------------------------------------------------
# GUI Application
# -------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Mov1 Downloader")
        self.geometry("900x700")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.ui_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.async_loop = None
        self.worker_thread = None

        self.setup_ui()
        self.poll_queue()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self.grid_rowconfigure(5, weight=1)

        # Row 0: URL and Download/Cancel
        self.url_frame = ctk.CTkFrame(self)
        self.url_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="nsew")
        self.url_frame.grid_columnconfigure(0, weight=4)
        self.url_frame.grid_columnconfigure(1, weight=1)

        self.url_entry = ctk.CTkEntry(self.url_frame, placeholder_text="Enter Base URL (e.g., https://example.com/path/)")
        self.url_entry.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="ew")

        self.download_btn = ctk.CTkButton(self.url_frame, text="Download", command=self.on_download_click, fg_color="#1f538d")
        self.download_btn.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="ew")

        self.cancel_btn = ctk.CTkButton(self.url_frame, text="Cancel", command=self.on_cancel_click, fg_color="#a11d1d", hover_color="#7a1616")
        self.cancel_btn.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="ew")
        self.cancel_btn.grid_remove()

        # Row 1: Movie Title
        self.title_entry = ctk.CTkEntry(self, placeholder_text="Detected Movie Title", state="disabled")
        self.title_entry.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        # Row 2: Queue Label
        self.queue_label = ctk.CTkLabel(self, text="Queue (URLs found):", font=ctk.CTkFont(weight="bold"))
        self.queue_label.grid(row=3, column=0, padx=20, pady=(10, 0), sticky="w")

        # Row 3: Queue Box
        self.queue_box = ctk.CTkTextbox(self, height=150)
        self.queue_box.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="nsew")

        # Row 4: Logs Label
        self.logs_label = ctk.CTkLabel(self, text="Logs:", font=ctk.CTkFont(weight="bold"))
        self.logs_label.grid(row=5, column=0, padx=20, pady=(10, 0), sticky="w")

        # Row 5: Logs Box
        self.logs_box = ctk.CTkTextbox(self, height=250)
        self.logs_box.grid(row=6, column=0, padx=20, pady=(0, 20), sticky="nsew")

    def log(self, msg):
        self.logs_box.insert("end", msg + "\n")
        self.logs_box.see("end")

    def update_queue(self, msg):
        self.queue_box.delete("1.0", "end")
        self.queue_box.insert("1.0", msg)

    def set_title(self, title):
        self.title_entry.configure(state="normal")
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, title)
        self.title_entry.configure(state="disabled")

    def on_download_click(self):
        url = self.url_entry.get().strip()
        if not url:
            self.log("❌ Error: Please enter a URL.")
            return

        self.stop_event.clear()
        self.download_btn.grid_remove()
        self.cancel_btn.grid()
        
        # Start async worker in a thread
        self.worker_thread = threading.Thread(target=self.run_async_tasks, args=(url,))
        self.worker_thread.daemon = True
        self.worker_thread.start()

    def on_cancel_click(self):
        self.stop_event.set()
        self.log("🛑 Cancelling...")
        self.reset_ui()

    def reset_ui(self):
        self.cancel_btn.grid_remove()
        self.download_btn.grid()
        self.title_entry.configure(state="normal")
        self.title_entry.delete(0, "end")
        self.title_entry.configure(state="disabled")
        self.queue_box.delete("1.0", "end")
        # self.logs_box.delete("1.0", "end") # Keep logs for history

    def run_async_tasks(self, url):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            queue_content = self.queue_box.get("1.0", "end").strip()
            urls = [u.strip() for u in queue_content.splitlines() if u.strip()]

            if not urls:
                # Crawl
                urls = loop.run_until_complete(crawl(url, 10, self.ui_queue, self.stop_event))
            
            if urls and not self.stop_event.is_set():
                # Download
                loop.run_until_complete(download(urls, url, self.ui_queue, self.stop_event))
        
        except Exception as e:
            self.ui_queue.put({"type": "log", "msg": f"FATAL ERROR: {e}"})
        finally:
            loop.close()
            self.ui_queue.put({"type": "done"})

    def poll_queue(self):
        while True:
            try:
                msg = self.ui_queue.get_nowait()
                if msg["type"] == "log":
                    self.log(msg["msg"])
                elif msg["type"] == "ffmpeg_log":
                    # Update last line or just append
                    self.log(f"    [FFmpeg] {msg['msg']}")
                elif msg["type"] == "title":
                    self.set_title(msg["msg"])
                elif msg["type"] == "queue_update":
                    self.update_queue(msg["msg"])
                elif msg["type"] == "done":
                    self.reset_ui()
                    self.log("🏁 Process finished.")
            except queue.Empty:
                break
        
        self.after(100, self.poll_queue)

if __name__ == "__main__":
    app = App()
    app.mainloop()
