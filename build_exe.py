import os
import sys
import subprocess
import shutil

# This script is intended to be run on Windows to create a standalone native executable.
# Prerequisites: 
# 1. Python installed
# 2. pip install pyinstaller playwright customtkinter
# 3. playwright install chromium

def build():
    print("🚀 Starting native build process...")
    
    # 1. Check if pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller not found. Install it with: pip install pyinstaller")
        return

    # 2. Define names
    app_name = "Mov1Downloader"
    entry_point = "app.py"
    
    # 3. Handle CustomTkinter
    import customtkinter
    import playwright_stealth
    ctk_path = os.path.dirname(customtkinter.__file__)
    stealth_path = os.path.dirname(playwright_stealth.__file__)
    
    # 4. PyInstaller Command
    # --onefile: Create a single executable
    # --windowed: No console window
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--windowed", 
        "--name", app_name,
        f"--add-data={ctk_path};customtkinter",
        f"--add-data={stealth_path};playwright_stealth",
        "--collect-all=playwright_stealth",
        "--hidden-import=playwright",
        "--hidden-import=playwright_stealth",
        entry_point
    ]
    
    print(f"📦 Running PyInstaller command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    print(f"✅ Build complete! Find your native EXE in the 'dist' folder.")

if __name__ == "__main__":
    build()
