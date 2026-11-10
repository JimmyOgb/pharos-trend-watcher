"""
Automated 1080p Live Demonstration Video Generator for Pharos Trend Watcher.

Records a continuous 1080p Playwright video stream against the live deployed URL
(https://pharos-trend-watcher.vercel.app) with custom animated cursor,
click ripples, and synchronized edge-tts voiceover merged via FFmpeg.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import subprocess
import time

import edge_tts
from playwright.async_api import async_playwright

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_DIR = _PROJECT_ROOT / "demo-output"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
_RAW_VIDEO_DIR = _OUTPUT_DIR / "raw"
_RAW_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

LIVE_URL = "https://pharos-trend-watcher.vercel.app"

NARRATION_TEXT = (
    "Welcome to Pharos Trend Watcher, live on Vercel. "
    "This persistent trend engine protects autonomous agent workflows from isolated spikes and oracle glitches. "
    "The engine begins in a clean monitoring state with active streak zero of three and no trigger active. "
    "Notice the configurable threshold, strictly requiring a minimum of three qualifying observations. "
    "Let us check spike resistance using a built-in verification scenario. "
    "At Step 3, an extreme sixty percent crash occurs. The engine recognizes this as an isolated spike and does not trigger! "
    "The reading immediately recovers, resetting the downward streak. "
    "Later, three sustained downward drops confirm the trend at Step 7. "
    "The trigger banner records the exact moment, qualifying observation ID, and complete causal rationale. "
    "Now let us test manual ingest. We clear the history and submit fifty, forty, and thirty Gwei. "
    "At the third consecutive drop, the trend triggers instantly. "
    "Next, we verify persistence. When the browser page is reloaded, all observations, streaks, and trigger states survive intact from localStorage without duplication. "
    "Pharos Trend Watcher is verified with forty-six automated tests, with source code available on GitHub."
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

  // Live URL and demo title intro banner
  const introBadge = document.createElement('div');
  introBadge.id = 'demo-intro-badge';
  introBadge.innerHTML = '🔴 LIVE PRODUCTION DEMO &nbsp;·&nbsp; <strong>https://pharos-trend-watcher.vercel.app</strong>';
  Object.assign(introBadge.style, {
    position: 'fixed', bottom: '16px', right: '20px',
    background: 'rgba(15, 23, 42, 0.92)', color: '#38bdf8',
    border: '1px solid rgba(56, 189, 248, 0.4)',
    borderRadius: '8px', padding: '8px 16px',
    fontSize: '13px', fontFamily: 'monospace',
    boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
    zIndex: '999990', pointerEvents: 'none',
    transition: 'opacity 0.6s ease'
  });
  document.body.appendChild(introBadge);

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


async def generate_voiceover(audio_path: Path):
    print("Generating voiceover narration using edge-tts...")
    communicate = edge_tts.Communicate(NARRATION_TEXT, "en-US-ChristopherNeural")
    await communicate.save(str(audio_path))
    print(f"Voiceover saved to {audio_path}")


async def smooth_move(page, x: float, y: float, steps: int = 25, pause_after: float = 0.5):
    await page.mouse.move(x, y, steps=steps)
    if pause_after > 0:
        await asyncio.sleep(pause_after)


async def smooth_click(page, selector: str, pause_after: float = 1.0):
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


async def smooth_type(page, selector: str, text: str, pause_after: float = 1.0):
    await smooth_click(page, selector, pause_after=0.2)
    # Clear input first
    await page.fill(selector, "")
    await page.keyboard.type(text, delay=65)
    await asyncio.sleep(pause_after)


async def record_playwright_video(raw_video_dir: Path):
    print(f"Starting Playwright 1080p recording session against live URL: {LIVE_URL}...")
    for old_file in raw_video_dir.glob("*.webm"):
        try:
            old_file.unlink()
        except Exception:
            pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(raw_video_dir),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Handle dialogs automatically
        page.on("dialog", lambda d: asyncio.create_task(d.accept()))

        # Navigate to live deployed web dashboard
        print(f"Navigating to {LIVE_URL}...")
        await page.goto(LIVE_URL, wait_until="networkidle")
        await page.evaluate(CURSOR_JS)

        # Ensure starting in clean state
        try:
            await page.locator("#btn-reset").click()
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # -------------------------------------------------------------
        # Scene 1: Introduction & Live URL Verification (0:00 - 0:08)
        # -------------------------------------------------------------
        print("Scene 1: Introduction & Live URL verification...")
        await smooth_move(page, 960, 80, steps=20, pause_after=1.5)  # Title bar
        await smooth_move(page, 650, 160, steps=20, pause_after=2.0) # Disclosure banner
        await asyncio.sleep(2.0)

        # -------------------------------------------------------------
        # Scene 2: Baseline & Initial Empty State (0:08 - 0:18)
        # -------------------------------------------------------------
        print("Scene 2: Baseline & Initial Empty State...")
        await smooth_move(page, 200, 260, steps=20, pause_after=1.5) # Active Streak (0/3)
        await smooth_move(page, 320, 260, steps=15, pause_after=1.5) # Trend State (MONITORING)
        await smooth_move(page, 250, 480, steps=20, pause_after=2.5) # Trend Configuration (K=3)

        # -------------------------------------------------------------
        # Scene 3: Single-Spike Resistance Verification (0:18 - 0:38)
        # -------------------------------------------------------------
        print("Scene 3: Check Spike Resistance (Built-in 8-point scenario)...")
        await smooth_click(page, "#btn-run-spike", pause_after=1.0)

        # Watch the 8 observations ingest in real time
        print("Observing real-time scenario playback in table...")
        await asyncio.sleep(2.0)
        await smooth_move(page, 750, 380, steps=20, pause_after=2.0) # Hover near step 3 (spike 40.0)
        await asyncio.sleep(2.5)

        # -------------------------------------------------------------
        # Scene 4: Trigger Auditability & Exact Moment (0:38 - 0:49)
        # -------------------------------------------------------------
        print("Scene 4: Inspecting Trigger Notification Banner & Rationale...")
        await smooth_move(page, 960, 215, steps=25, pause_after=2.5) # Trigger card header
        await smooth_move(page, 600, 250, steps=20, pause_after=2.0) # Trigger details (ID, timestamp)
        await smooth_move(page, 960, 290, steps=20, pause_after=2.5) # Complete audit rationale

        # -------------------------------------------------------------
        # Scene 5: Manual Observation Ingest & Live Triggering (0:49 - 1:04)
        # -------------------------------------------------------------
        print("Scene 5: Clearing state and performing Manual Observation Ingest...")
        await smooth_click(page, "#btn-reset", pause_after=1.5)

        print("Ingesting manual reading 1: 50.0")
        await smooth_type(page, "#manual-value", "50.0", pause_after=0.5)
        await smooth_click(page, "#btn-manual-ingest", pause_after=1.0)

        print("Ingesting manual reading 2: 40.0")
        await smooth_type(page, "#manual-value", "40.0", pause_after=0.5)
        await smooth_click(page, "#btn-manual-ingest", pause_after=1.0)

        print("Ingesting manual reading 3: 30.0 (Threshold Trigger Moment)")
        await smooth_type(page, "#manual-value", "30.0", pause_after=0.5)
        await smooth_click(page, "#btn-manual-ingest", pause_after=2.0)

        # Highlight triggered state
        await smooth_move(page, 960, 215, steps=20, pause_after=2.0)

        # -------------------------------------------------------------
        # Scene 6: Durable Persistence Across Reload (1:04 - 1:16)
        # -------------------------------------------------------------
        print("Scene 6: Testing Durable Persistence across reload...")
        await smooth_click(page, "#btn-simulate-reload", pause_after=2.0)

        print("Performing real hard browser page reload...")
        await page.reload(wait_until="networkidle")
        await page.evaluate(CURSOR_JS)
        await asyncio.sleep(1.0)

        # Highlight preserved history and trigger banner after reload
        await smooth_move(page, 200, 260, steps=20, pause_after=1.5) # Preserved streak (3/3)
        await smooth_move(page, 750, 400, steps=20, pause_after=2.5) # Preserved history rows

        # -------------------------------------------------------------
        # Scene 7: Automated Test Coverage & GitHub Source (1:16 - 1:26)
        # -------------------------------------------------------------
        print("Scene 7: Inspecting Automated Test Suite Coverage card...")
        await page.evaluate("window.scrollTo({top: 520, behavior: 'smooth'})")
        await asyncio.sleep(2.5)
        await smooth_move(page, 1000, 750, steps=25, pause_after=2.5) # 46 passing tests

        print("Scrolling back to header and focusing on View source code...")
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await asyncio.sleep(1.5)
        await smooth_move(page, 1340, 80, steps=25, pause_after=3.0)  # View source code link

        # Clean slate reset at very end
        try:
            await page.locator("#btn-reset").click()
            await asyncio.sleep(0.5)
        except Exception:
            pass

        print("Finalizing video capture...")
        await asyncio.sleep(1.5)
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
    audio_path = _OUTPUT_DIR / "voiceover.mp3"
    final_mp4 = _OUTPUT_DIR / "trend_watcher_demo.mp4"

    await generate_voiceover(audio_path)
    raw_webm = await record_playwright_video(_RAW_VIDEO_DIR)
    merge_video_audio(raw_webm, audio_path, final_mp4)

    if final_mp4.exists():
        size_mb = final_mp4.stat().st_size / (1024 * 1024)
        print(f"SUCCESS: Master video generated! File size: {size_mb:.2f} MB")


if __name__ == "__main__":
    asyncio.run(main())
