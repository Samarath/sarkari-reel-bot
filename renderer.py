import os
import json
from playwright.sync_api import sync_playwright
from database import FirestoreManager


class ReelCardRenderer:
    def __init__(self, studio_url: str = "http://localhost:5173"):
        self.studio_url = studio_url
        self.output_dir = os.path.join(os.getcwd(), "output", "cards")
        os.makedirs(self.output_dir, exist_ok=True)

    def render_job_card(self, job: dict) -> str:
        """
        Injects a Firestore job dictionary into the React template
        and captures a 1080x1920 PNG screenshot.
        """
        job_id = job.get("job_id", "sample_job")
        output_path = os.path.join(self.output_dir, f"{job_id}.png")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1080, "height": 1920},
                device_scale_factor=1,
            )

            # Inject the job dictionary directly into window.__JOB_DATA__ before React mounts
            serialized_job = json.dumps(job, default=str)
            page.add_init_script(f"window.__JOB_DATA__ = {serialized_job};")

            print(f"Rendering Reel card for: {job.get('agency')} - {job.get('raw_title')[:40]}...")
            page.goto(f"{self.studio_url}/?capture=true", wait_until="networkidle", timeout=45000)

            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)

            # Screenshot the exact #reel-canvas element
            canvas = page.locator("#reel-canvas")
            canvas.screenshot(path=output_path, type="png")

            browser.close()

        print(f"   [STUDIO] Saved 1080x1920 graphic -> {output_path}")
        return output_path


if __name__ == "__main__":
    db = FirestoreManager()
    renderer = ReelCardRenderer()

    top_jobs = db.get_next_batch_to_publish(batch_size=3)
    if not top_jobs:
        print("No QUEUED jobs found in Firestore. Run main.py first!")
    else:
        for job in top_jobs:
            renderer.render_job_card(job)