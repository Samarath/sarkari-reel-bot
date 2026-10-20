import os
import re
import glob
import time
import random
import subprocess
import requests
import cloudinary
import cloudinary.uploader
import imageio_ffmpeg
from dotenv import load_dotenv
from database import FirestoreManager
from renderer import ReelCardRenderer

load_dotenv()

# Meta Graph API error codes that indicate rate-limiting or publishing blocks
META_RATE_LIMIT_CODES = {4, 9, 17, 32, 613, 368}


class MetaRateLimitError(RuntimeError):
    """Raised when Meta Graph API signals rate-limiting or spam protection."""
    pass


class ReelPublisher:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

        # 1. Cloudinary Credentials
        self.cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
        self.cloud_key = os.getenv("CLOUDINARY_API_KEY")
        self.cloud_secret = os.getenv("CLOUDINARY_API_SECRET")

        if not self.dry_run:
            if not all([self.cloud_name, self.cloud_key, self.cloud_secret]):
                raise ValueError("Missing Cloudinary credentials in .env file.")
            cloudinary.config(
                cloud_name=self.cloud_name,
                api_key=self.cloud_key,
                api_secret=self.cloud_secret,
                secure=True,
            )

        # 2. Meta (Instagram + Facebook) Credentials
        self.ig_account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
        self.fb_page_id = os.getenv("FACEBOOK_PAGE_ID")
        self.access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.fb_page_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") or self.access_token
        self.graph_base_url = "https://graph.facebook.com/v21.0"

        # 3. Local Paths & FFmpeg
        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        self.video_dir = os.path.join(os.getcwd(), "output", "videos")
        self.music_dir = os.path.join(os.getcwd(), "assets", "music")
        os.makedirs(self.video_dir, exist_ok=True)
        os.makedirs(self.music_dir, exist_ok=True)

    def check_instagram_quota(self) -> int:
        """
        Queries Meta's /content_publishing_limit endpoint to check how many
        API publishes remain in the current 24-hour rolling window.
        """
        if self.dry_run or not self.ig_account_id or not self.access_token:
            return 25

        url = f"{self.graph_base_url}/{self.ig_account_id}/content_publishing_limit"
        try:
            resp = requests.get(
                url,
                params={
                    "fields": "config,quota_usage",
                    "access_token": self.access_token,
                },
                timeout=15,
            )
            if not resp.ok:
                return 25

            data = resp.json().get("data", [])
            if not data:
                return 25

            quota_info = data[0]
            used = int(quota_info.get("quota_usage", 0))
            total = int(quota_info.get("config", {}).get("quota_total", 50))
            remaining = max(0, total - used)
            print(f"[META QUOTA] Used {used}/{total} posts in last 24h ({remaining} remaining).")
            return remaining
        except Exception as e:
            print(f"[META QUOTA WARNING] Could not check quota ({e}). Proceeding with safe default.")
            return 25

    def _check_for_rate_limit(self, resp: requests.Response, platform: str) -> None:
        """Raises MetaRateLimitError if the Graph API response indicates throttling."""
        if resp.status_code == 429:
            raise MetaRateLimitError(f"{platform} HTTP 429 Too Many Requests: {resp.text}")

        try:
            err_data = resp.json().get("error", {})
            code = err_data.get("code")
            if code in META_RATE_LIMIT_CODES:
                raise MetaRateLimitError(
                    f"{platform} API Rate Limit / Spam Block (code {code}): {err_data.get('message')}"
                )
        except ValueError:
            pass

    def pick_random_music(self) -> str | None:
        """Picks a random .mp3 file from assets/music/ if available."""
        mp3_files = glob.glob(os.path.join(self.music_dir, "*.mp3"))
        if not mp3_files:
            return None
        chosen_track = random.choice(mp3_files)
        print(f"   [AUDIO] Randomly selected track: {os.path.basename(chosen_track)}")
        return chosen_track

    def build_reel_caption(self, job: dict) -> str:
        """
        Builds a Hinglish + SEO-optimized description with structured job details
        and dynamic ranking hashtags for Instagram and Facebook.
        """
        agency = job.get("agency", "GOVT JOB")
        title = job.get("raw_title", "Official Recruitment Alert")
        post_name = job.get("post_name", "Check Notification")
        vacancies = job.get("vacancies", "Refer Notice")
        qualification = job.get("qualification", "Refer Notice")
        age_limit = job.get("age_limit", "As per rules")
        last_date = job.get("last_date", "Check Notice")
        apply_url = job.get("official_apply_url", "Refer Official Portal")

        # 1. Dynamic Agency Hashtags
        clean_agency = re.sub(r"[^a-zA-Z0-9]", "", agency.title())
        dynamic_tags = [f"#{clean_agency}", f"#{clean_agency}Recruitment"] if clean_agency else []

        # 2. Dynamic Qualification Hashtags
        qual_lower = qualification.lower()
        if "10th" in qual_lower or "matric" in qual_lower:
            dynamic_tags.append("#10thPassJobs")
        if "12th" in qual_lower or "intermediate" in qual_lower:
            dynamic_tags.append("#12thPassJobs")
        if any(q in qual_lower for q in ["degree", "graduate", "b.tech", "b.e", "b.sc", "b.com"]):
            dynamic_tags.append("#GraduateJobs")
        if "iti" in qual_lower or "diploma" in qual_lower:
            dynamic_tags.append("#DiplomaJobs")

        # 3. Dynamic Sector Hashtags
        combined_text = f"{agency} {title}".lower()
        if any(w in combined_text for w in ["army", "navy", "air force", "defence", "crpf", "bsf", "itbp"]):
            dynamic_tags.extend(["#DefenceJobs", "#Bharti2026"])
        elif any(w in combined_text for w in ["bank", "sbi", "ibps", "rbi", "uco", "canara"]):
            dynamic_tags.extend(["#BankJobs", "#BankingExams"])
        elif any(w in combined_text for w in ["railway", "rrb", "ntpc", "metro"]):
            dynamic_tags.extend(["#RailwayJobs", "#RRBRecruitment"])
        elif any(w in combined_text for w in ["upsc", "ssc", "psc"]):
            dynamic_tags.extend(["#UPSC", "#SSCExams"])

        dynamic_tag_str = " ".join(dict.fromkeys(dynamic_tags))

        caption = (
            f"🚨 {title.upper()} ({vacancies} Posts) — Official Notification Out! 🇮🇳\n\n"
            f"Sabhi details niche di gayi hain, form bharne se pehle check karein 👇\n\n"
            f"📌 COMPLETE VACANCY DETAILS:\n"
            f"🏛️ Recruiting Agency: {agency}\n"
            f"💼 Post Name: {post_name}\n"
            f"🎯 Total Vacancies: {vacancies}\n"
            f"🎓 Qualification / Eligibility: {qualification}\n"
            f"🎂 Age Limit: {age_limit}\n"
            f"⏳ Last Date to Apply: {last_date}\n\n"
            f"🔗 OFFICIAL APPLY LINK (No Middlemen):\n"
            f"👉 {apply_url}\n"
            f"(Facebook par link direct click karein • Instagram par copy karke browser mein open karein)\n\n"
            f"📥 Is Reel ko SAVE karlo taaki last date miss na ho, aur apne dosto ke sath SHARE karo!\n"
            f"Follow @sarkaridrop har roz nayi Central & State Govt job updates ke liye 🔔\n\n"
            f"🔎 Search Keywords:\n"
            f"{agency} Recruitment 2026, {title}, Latest Sarkari Naukri 2026, "
            f"Direct Official Job Alert, Sarkari Drop.\n\n"
            f"#SarkariDrop #SarkariNaukri #SarkariNaukri2026 #GovtJobs #GovtJobs2026 "
            f"#GovernmentJobs #SarkariResult #SarkariExam #SarkariJobAlert #JobAlertIndia "
            f"#JobsInIndia #IndiaJobs #LatestJobs #NewVacancy #JobUpdate #Recruitment2027 "
            f"#EmploymentNews #CompetitiveExams #ExamPreparation #ReelsIndia #ViralReels "
            f"{dynamic_tag_str}"
        )
        return caption

    def convert_png_to_mp4(self, image_path: str, job_id: str, duration: int = 6) -> str:
        """
        Converts the 1080x1920 PNG + random MP3 into a 30fps H.264 MP4 video
        compatible with both Instagram Reels and Facebook Reels.
        """
        video_path = os.path.join(self.video_dir, f"{job_id}.mp4")
        audio_track = self.pick_random_music()

        if audio_track:
            fade_start = max(1.0, duration - 1.2)
            cmd = [
                self.ffmpeg_exe, "-y",
                "-loop", "1", "-framerate", "30", "-i", image_path,
                "-i", audio_track,
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-r", "30",
                "-c:a", "aac", "-b:a", "192k",
                "-af", f"afade=t=in:st=0:d=0.4,afade=t=out:st={fade_start}:d=1.2",
                "-pix_fmt", "yuv420p",
                "-vf", "scale=1080:1920",
                "-t", str(duration),
                "-shortest",
                "-movflags", "+faststart",
                video_path,
            ]
        else:
            print("   [AUDIO] No MP3s found in assets/music/ — generating silent audio track.")
            cmd = [
                self.ffmpeg_exe, "-y",
                "-loop", "1", "-framerate", "30", "-i", image_path,
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-r", "30",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p",
                "-vf", "scale=1080:1920",
                "-t", str(duration),
                "-shortest",
                "-movflags", "+faststart",
                video_path,
            ]

        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f"   [FFMPEG] Created {duration}s 30fps Reel MP4 -> {video_path}")
        return video_path

    def upload_to_cloudinary(self, video_path: str, job_id: str) -> tuple[str, str]:
        """Uploads the MP4 to Cloudinary and returns (secure_url, public_id)."""
        public_id = f"sarkari_reels/reel_{job_id}"
        print(f"   [CLOUDINARY] Uploading temporary video ({public_id})...")
        res = cloudinary.uploader.upload(
            video_path,
            resource_type="video",
            public_id=public_id,
            overwrite=True,
        )
        return res["secure_url"], res["public_id"]

    def delete_from_cloudinary(self, public_id: str) -> None:
        """Deletes the temporary video from Cloudinary."""
        try:
            cloudinary.uploader.destroy(public_id, resource_type="video", invalidate=True)
            print(f"   [CLOUDINARY] Deleted temporary asset: {public_id}")
        except Exception as e:
            print(f"   [CLOUDINARY WARNING] Could not delete {public_id}: {e}")

    def publish_to_instagram(self, video_url: str, caption: str) -> str:
        """Uploads container, polls until FINISHED, and publishes Reel to Instagram."""
        if not self.ig_account_id or not self.access_token:
            raise ValueError("Missing INSTAGRAM_ACCOUNT_ID or INSTAGRAM_ACCESS_TOKEN in .env")

        create_url = f"{self.graph_base_url}/{self.ig_account_id}/media"
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": self.access_token,
        }
        resp = requests.post(create_url, data=payload, timeout=30)
        if not resp.ok:
            self._check_for_rate_limit(resp, "INSTAGRAM")
            raise RuntimeError(f"IG Container Create Error: {resp.text}")

        creation_id = resp.json().get("id")
        print(f"   [INSTAGRAM] Container created ({creation_id}). Waiting for processing...")

        status_url = f"{self.graph_base_url}/{creation_id}"
        for attempt in range(1, 22):
            time.sleep(6)
            status_resp = requests.get(
                status_url,
                params={"fields": "status_code,status", "access_token": self.access_token},
                timeout=20,
            )
            if not status_resp.ok:
                self._check_for_rate_limit(status_resp, "INSTAGRAM")
                status_resp.raise_for_status()

            status_data = status_resp.json()
            status_code = status_data.get("status_code")

            print(f"   [INSTAGRAM] Poll #{attempt}: status_code = {status_code}")

            if status_code == "FINISHED":
                break
            elif status_code in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram container processing failed: {status_data}")
        else:
            raise TimeoutError("Instagram took too long to process the Reel container.")

        publish_url = f"{self.graph_base_url}/{self.ig_account_id}/media_publish"
        pub_resp = requests.post(
            publish_url,
            data={"creation_id": creation_id, "access_token": self.access_token},
            timeout=30,
        )
        if not pub_resp.ok:
            self._check_for_rate_limit(pub_resp, "INSTAGRAM")
            raise RuntimeError(f"IG Publish Error: {pub_resp.text}")

        media_id = pub_resp.json().get("id")
        print(f"   [INSTAGRAM] ✅ Reel Published! Live Media ID: {media_id}")
        return media_id

    def publish_to_facebook(self, video_url: str, caption: str) -> str | None:
        """
        Publishes the exact same Cloudinary MP4 + caption as a Facebook Page Reel.
        """
        if not self.fb_page_id or not self.fb_page_token:
            print("   [FACEBOOK] No FACEBOOK_PAGE_ID in .env — skipping Facebook publish.")
            return None

        # Step 1: Initialize upload session
        init_url = f"{self.graph_base_url}/{self.fb_page_id}/video_reels"
        init_resp = requests.post(
            init_url,
            data={"upload_phase": "start", "access_token": self.fb_page_token},
            timeout=30,
        )
        if not init_resp.ok:
            self._check_for_rate_limit(init_resp, "FACEBOOK")
            raise RuntimeError(f"FB Init Error: {init_resp.text}")

        video_id = init_resp.json().get("video_id")
        print(f"   [FACEBOOK] Reel session started ({video_id}). Transferring video from Cloudinary...")

        # Step 2: Pass Cloudinary file_url to Meta's rupload server
        upload_url = f"https://rupload.facebook.com/video-upload/v21.0/{video_id}"
        up_resp = requests.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {self.fb_page_token}",
                "file_url": video_url,
            },
            timeout=60,
        )
        if not up_resp.ok:
            self._check_for_rate_limit(up_resp, "FACEBOOK")
            raise RuntimeError(f"FB Upload Error: {up_resp.text}")

        # Step 3: Finish and publish the Reel with caption
        finish_resp = requests.post(
            init_url,
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": caption,
                "access_token": self.fb_page_token,
            },
            timeout=30,
        )
        if not finish_resp.ok:
            self._check_for_rate_limit(finish_resp, "FACEBOOK")
            raise RuntimeError(f"FB Finish Error: {finish_resp.text}")

        print(f"   [FACEBOOK] ✅ Reel Published to Facebook Page! Video ID: {video_id}")
        return video_id


def publish_all_pending_jobs(
    max_per_run: int = 15,
    min_cooldown_sec: int = 180,
    max_cooldown_sec: int = 240,
    dry_run: bool = False,
):
    """
    Fetches all pending ('QUEUED') jobs from Firestore and publishes them one by one
    with randomized human-like cooldowns and Meta Graph API quota/rate-limit protection.
    """
    db = FirestoreManager()
    renderer = ReelCardRenderer()
    publisher = ReelPublisher(dry_run=dry_run)

    # 1. Check how many posts Meta allows in the current 24h rolling window
    remaining_quota = publisher.check_instagram_quota()
    if remaining_quota <= 0 and not dry_run:
        print("[STOP] Meta 24-hour publishing quota is exhausted. Will resume automatically later.")
        return

    # 2. Fetch all pending ('QUEUED') jobs sorted by priority_score
    all_queued_jobs = db.get_next_batch_to_publish(batch_size=1000)
    if not all_queued_jobs:
        print("No 'QUEUED' jobs waiting in Firestore. All caught up!")
        return

    # Cap the run by both remaining 24h Meta quota and max_per_run safety ceiling
    safe_limit = min(len(all_queued_jobs), remaining_quota, max_per_run) if not dry_run else len(all_queued_jobs)
    jobs_to_process = all_queued_jobs[:safe_limit]

    print(
        f"Found {len(all_queued_jobs)} total QUEUED job(s) in Firestore. "
        f"Publishing {len(jobs_to_process)} in this session (cooldown: {min_cooldown_sec}-{max_cooldown_sec}s).\n"
    )

    published_count = 0

    for index, job in enumerate(jobs_to_process, start=1):
        job_id = job["job_id"]
        png_path = None
        mp4_path = None
        cloudinary_public_id = None

        print(f"=== [{index}/{len(jobs_to_process)}] Processing: {job.get('raw_title')} ===")

        try:
            # 1. Render 1080x1920 PNG from React Studio
            png_path = renderer.render_job_card(job)

            # 2. Convert PNG + Random MP3 to 6-second 30fps MP4
            mp4_path = publisher.convert_png_to_mp4(png_path, job_id)

            # 3. Build Hinglish + SEO Reel Caption
            caption = publisher.build_reel_caption(job)

            if dry_run:
                print("\n--- DRY RUN CAPTION PREVIEW ---")
                print(caption)
                print("-------------------------------")
                print(f"   [DRY RUN] Video saved at: {mp4_path}\n")
                continue

            # 4. Upload MP4 to Cloudinary
            video_url, cloudinary_public_id = publisher.upload_to_cloudinary(mp4_path, job_id)

            # 5. Publish to Instagram Reels
            ig_media_id = publisher.publish_to_instagram(video_url, caption)

            # 6. Publish to Facebook Page Reels ( pauses briefly so we don't hit both endpoints in the same millisecond)
            time.sleep(5)
            try:
                publisher.publish_to_facebook(video_url, caption)
            except MetaRateLimitError:
                raise
            except Exception as fb_err:
                print(f"   [FACEBOOK WARNING] Facebook publish failed: {fb_err}")

            # 7. STRICT ORDER: Mark PUBLISHED in Firestore only after Instagram succeeds
            if ig_media_id:
                db.mark_status(job_id, "PUBLISHED")
                published_count += 1

            # 8. Jittered cooldown before the next job to protect account health
            if index < len(jobs_to_process):
                wait_seconds = random.randint(min_cooldown_sec, max_cooldown_sec)
                print(
                    f"   [COOLDOWN] Sleeping {wait_seconds}s ({wait_seconds / 60:.1f} min) "
                    f"before Reel #{index + 1} to respect Meta rate limits...\n"
                )
                time.sleep(wait_seconds)

        except MetaRateLimitError as rate_err:
            print(f"\n[CIRCUIT BREAKER] {rate_err}")
            print(
                "[CIRCUIT BREAKER] Stopping batch immediately to protect your Meta account. "
                "Remaining jobs stay 'QUEUED' in Firestore for the next run."
            )
            break

        except Exception as e:
            print(f"   [ERROR] Failed to publish job {job_id}: {e}")
            print("   [INFO] Job status remains 'QUEUED' in Firestore for retry.\n")

        finally:
            # 9. Always delete the temporary video from Cloudinary & clean up local files
            if cloudinary_public_id:
                publisher.delete_from_cloudinary(cloudinary_public_id)

            for local_file in (png_path, mp4_path):
                if local_file and os.path.exists(local_file) and not dry_run:
                    os.remove(local_file)

    print(f"\nBatch Complete! Successfully published {published_count}/{len(jobs_to_process)} Reels.")


if __name__ == "__main__":
    # Fetches all QUEUED jobs and publishes them sequentially with 3-4 min jittered spacing
    publish_all_pending_jobs(
        max_per_run=15,        # Safety cap per session (Meta allows max 50 per 24h)
        min_cooldown_sec=180,  # Minimum 3 minutes between Reels
        max_cooldown_sec=240,  # Maximum 4 minutes between Reels
        dry_run=False,
    )