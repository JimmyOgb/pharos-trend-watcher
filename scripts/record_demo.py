"""
Automated 1080p Live Demonstration Video Generator for Pharos Trend Watcher.

Records a continuous 1080p Playwright video stream with custom animated cursor,
click ripples, and synchronized edge-tts voiceover merged via FFmpeg.
"""

from __future__ import annotations

import asyncio
import http.server
from pathlib import Path
import shutil
import socketserver
import subprocess
import threading
import time

import edge_tts
from playwright.async_api import async_playwright

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = _PROJECT_ROOT / "web"
_OUTPUT_DIR = _PROJECT_ROOT / "demo-output"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
_RAW_VIDEO_DIR = _OUTPUT_DIR / "raw"
_RAW_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

PORT = 8995

NARRATION_TEXT = (
    "Welcome to Pharos Trend Watcher: persistent, multi-observation trend monitoring with auditable history. "
    "Autonomous agents monitoring volatile metrics must not panic on isolated spikes or oracle glitches. "
    "Trend Watcher provides durable memory across runs, acting only once a trend is confirmed across multiple observations. "
    "Notice the configurable threshold, strictly enforcing a minimum of three observations. "
    "Let us check spike resistance using a built-in verification scenario. "
    "Watch Step 3 closely: an extreme sixty percent crash occurs. The engine recognizes this as an isolated noise spike and does not trigger! "
    "The reading immediately bounces back, resetting the downward streak. "
    "Later, three sustained consecutive drops occur. At Step 7, the threshold is met, and the trend condition triggers instantly. "
    "The trigger banner records the exact moment, qualifying observation ID, and complete rationale. "
    "When we verify persistence, previous history and streaks are cleanly recovered from durable storage without duplicates. "
    "Pharos Trend Watcher is fully tested with forty-six passing tests, delivering reliable trend detection for autonomous workflows."
)

CURSOR_JS = """
(() => {
  if (document.getElementById('demo-cursor')) return;
  const cursor = document.createElement('div');
  cursor.id = 'demo-cursor';
  Object.assign(cursor.style, {
    position: 'fixed', top: '0px', left: '0px',
    width: '24px', height: '24px',
    background: 'rgba(6, 182, 212, 0.9)',
    border: '2px solid white', borderRadius: '50%',
    boxShadow: '0 0 16px rgba(6, 182, 212, 0.8)',
    pointerEvents: 'none', zIndex: '999999',
    transition: 'transform 0.2s cubic-bezier(0.22, 1, 0.36, 1)',
    transform: 'translate(-50%, -50%)'
  });
  document.body.appendChild(cursor);

  document.addEventListener('mousemove', e => {
    cursor.style.left = e.clientX + 'px';
    cursor.style.top = e.clientY + 'px';
  });
  document.addEventListener('mousedown', e => {
    cursor.style.transform = 'translate(-50%, -50%) scale(0.7)';
    const ripple = document.createElement('div');
    Object.assign(ripple.style, {
      position: 'fixed', left: e.clientX + 'px', top: e.clientY + 'px',
      width: '12px', height: '12px', borderRadius: '50%',
      border: '2px solid rgba(6, 182, 212, 1)',
      transform: 'translate(-50%, -50%) scale(1)',
      opacity: '1', pointerEvents: 'none', zIndex: '999998',
      transition: 'all 0.45s ease-out'
    });
    document.body.appendChild(ripple);
    requestAnimationFrame(() => {
      ripple.style.transform = 'translate(-50%, -50%) scale(4)';
      ripple.style.opacity = '0';
    });
    setTimeout(() => ripple.remove(), 450);
  });
  document.addEventListener('mouseup', () => {
    cursor.style.transform = 'translate(-50%, -50%) scale(1)';
  });
})();
"""


class QuietHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_WEB_DIR), **kwargs)

    def log_message(self, format, *args):
        pass


def start_server():
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", PORT), QuietHTTPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


async def generate_voiceover(audio_path: Path):
    print("Generating voiceover narration using edge-tts...")
    communicate = edge_tts.Communicate(NARRATION_TEXT, "en-US-ChristopherNeural")
    await communicate.save(str(audio_path))
    print(f"Voiceover saved to {audio_path}")


async def smooth_move_and_click(page, selector: str, pause_after: float = 1.0):
    loc = page.locator(selector).first
    await loc.wait_for(state="visible", timeout=10000)
    await loc.scroll_into_view_if_needed()
    box = await loc.bounding_box()
    if box:
        target_x = box["x"] + box["width"] / 2
        target_y = box["y"] + box["height"] / 2
        await page.mouse.move(target_x, target_y, steps=25)
        await asyncio.sleep(0.2)
        await page.mouse.click(target_x, target_y)
    else:
        await loc.click()
    await asyncio.sleep(pause_after)


async def record_playwright_video(raw_video_dir: Path):
    print("Starting Playwright 1080p recording session...")
    for old_file in raw_video_dir.glob("*.webm"):
        old_file.unlink()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(raw_video_dir),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Automatically accept alert dialogs so they don't halt automation
        page.on("dialog", lambda d: asyncio.create_task(d.accept()))

        # Navigate to local web dashboard
        await page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="networkidle")
        await page.evaluate(CURSOR_JS)
        await asyncio.sleep(3.0)

        # 1. Hover over header and status indicators
        await page.mouse.move(960, 250, steps=20)
        await asyncio.sleep(2.0)

        # 2. Focus on Configuration
        await page.mouse.move(250, 480, steps=25)
        await asyncio.sleep(2.0)

        # 3. Click "⚡ Check Spike Resistance"
        print("Executing Check Spike Resistance scenario on dashboard...")
        await smooth_move_and_click(page, "#btn-run-spike", pause_after=5.5)

        # 4. Scroll to view trigger card
        print("Inspecting confirmed trigger card and exact moment...")
        await page.mouse.move(960, 200, steps=20)
        await asyncio.sleep(4.0)

        # 5. Hover over table rows showing step 3 (-60.8%) vs step 7 (Triggered)
        await page.mouse.move(750, 600, steps=25)
        await asyncio.sleep(3.0)

        # 6. Click "🔄 Verify Persistence"
        print("Verifying state reload from persistent storage...")
        await smooth_move_and_click(page, "#btn-simulate-reload", pause_after=3.0)

        # 7. Scroll down to inspect the Test Suite Coverage
        print("Inspecting automated test suite coverage card...")
        await page.evaluate("window.scrollTo({top: 500, behavior: 'smooth'})")
        await asyncio.sleep(3.5)

        # Final pause before closing
        await asyncio.sleep(2.0)
        await context.close()
        await browser.close()

    recorded_webms = list(raw_video_dir.glob("*.webm"))
    if not recorded_webms:
        raise RuntimeError("No .webm recording file found.")
    return recorded_webms[0]


def merge_video_audio(webm_path: Path, audio_path: Path, output_mp4: Path):
    print("Merging high-definition video and voiceover using FFmpeg...")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(webm_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_mp4),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {res.stderr}")
    print(f"Master demonstration video successfully created at: {output_mp4}")


async def main():
    server = start_server()
    print(f"Local web server running on port {PORT}")
    try:
        audio_path = _OUTPUT_DIR / "voiceover.mp3"
        final_mp4 = _OUTPUT_DIR / "trend_watcher_demo.mp4"

        await generate_voiceover(audio_path)
        raw_webm = await record_playwright_video(_RAW_VIDEO_DIR)
        merge_video_audio(raw_webm, audio_path, final_mp4)

        if final_mp4.exists():
            size_mb = final_mp4.stat().st_size / (1024 * 1024)
            print(f"SUCCESS: Video generated! File size: {size_mb:.2f} MB")
    finally:
        server.shutdown()
        server.server_close()
        print("Local web server stopped.")


if __name__ == "__main__":
    asyncio.run(main())
