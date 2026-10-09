import http.server
import socketserver
import threading
import time
import subprocess
import os

PORT = 8894
DIRECTORY = "public"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
server_thread.start()
print("Server running on port", PORT)

time.sleep(1)

chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
screenshot_out = os.path.abspath("public/screenshot.png")

cmd = [
    chrome_path,
    "--headless=new",
    "--disable-gpu",
    "--window-size=412,915",
    "--virtual-time-budget=8000",
    f"--screenshot={screenshot_out}",
    f"http://127.0.0.1:{PORT}/index.html"
]

print("Capturing screenshot...")
p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="ignore", timeout=20)
print("Chrome exit code:", p.returncode)

artifact_dir = r"C:\Users\rache\.gemini\antigravity\brain\e7fb1065-007d-4ed0-8f1d-f9c5a778e34a"
artifact_screenshot = os.path.join(artifact_dir, "screenshot.png")
if os.path.exists(screenshot_out):
    print("Screenshot captured! Size:", os.path.getsize(screenshot_out))
    with open(screenshot_out, "rb") as f_src, open(artifact_screenshot, "wb") as f_dst:
        f_dst.write(f_src.read())
    print("Copied to artifact dir:", artifact_screenshot)

httpd.shutdown()
