import os
import sys
import subprocess
import shutil

# This script is intended to be run on Windows to create a standalone executable.
# Prerequisites: 
# 1. Python installed
# 2. pip install pyinstaller playwright gradio
# 3. playwright install chromium

def build():
    print("🚀 Starting build process...")
    
    # 1. Check if pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller not found. Install it with: pip install pyinstaller")
        return

    # 2. Define names
    app_name = "Mov1Downloader"
    entry_point = "app.py"
    
    # 3. Handle Gradio assets
    import gradio
    gradio_path = os.path.dirname(gradio.__file__)
    
    # 4. Handle Playwright
    # We will assume the user has run 'playwright install chromium'
    # For a truly portable app, we would bundle the browser, but that adds ~200MB.
    # Instead, we'll add a check in app.py to install if missing.

    # 5. PyInstaller Command
    # --onefile: Create a single executable
    # --add-data: Bundle Gradio static files
    # --hidden-import: Ensure dynamic imports are caught
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--windowed", # No console window
        "--name", app_name,
        f"--add-data={gradio_path};gradio",
        "--hidden-import=uvicorn",
        "--hidden-import=playwright",
        entry_point
    ]
    
    print(f"📦 Running PyInstaller command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    print(f"✅ Build complete! Find your EXE in the 'dist' folder.")

if __name__ == "__main__":
    build()
