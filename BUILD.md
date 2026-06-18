# 🚀 How to release Mov1 Downloader as a Windows EXE

Since this application depends on **Gradio**, **Playwright**, and **FFmpeg**, follow these steps on a **Windows machine** to create your standalone `.exe`.

## 1. Prerequisites
Install the required tools on your Windows machine:
- [Python 3.11+](https://www.python.org/downloads/)
- [FFmpeg](https://ffmpeg.org/download.html) (Ensure `ffmpeg` is in your Windows PATH)

## 2. Setup Environment
Open PowerShell or Command Prompt in the project folder and run:
```bash
# Install dependencies
pip install -r requirements.txt

# Install PyInstaller
pip install pyinstaller

# Install Playwright browsers (required for the app to work)
playwright install chromium
```

## 3. Build the Executable
Run the provided build script:
```bash
python build_exe.py
```

## 4. Output
- Your standalone executable will be located in the `dist/` folder: `dist/Mov1Downloader.exe`.

## 🛠 Troubleshooting
- **Playwright missing**: If the EXE fails to find Chromium, you may need to bundle it by setting the `PLAYWRIGHT_BROWSERS_PATH` environment variable before building, or simply run `playwright install chromium` on the machine where you run the EXE for the first time.
- **FFmpeg not found**: Ensure `ffmpeg` is installed on the user's system. For a fully portable version, you can place `ffmpeg.exe` in the same folder as `Mov1Downloader.exe`.

## 📦 Creating a Setup Installer
To create a "Setup Wizard" (`setup.exe`), we recommend using [Inno Setup](https://jrsoftware.org/isinfo.php). You can point it to the `dist/Mov1Downloader.exe` file created in step 3.
