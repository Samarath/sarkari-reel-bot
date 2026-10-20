import os
import json
import requests
from datetime import datetime, timezone
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from models import ScrapedJobNotice


class FirestoreManager:
    def __init__(self, key_path: str = "serviceAccountKey.json"):
        if not os.path.exists(key_path):
            raise FileNotFoundError(
                f"Missing '{key_path}'. Make sure serviceAccountKey.json is in your project folder."
            )

        with open(key_path, "r", encoding="utf-8") as f:
            key_data = json.load(f)
            self.project_id = key_data["project_id"]

        scopes = ["https://www.googleapis.com/auth/datastore"]
        self.creds = service_account.Credentials.from_service_account_file(key_path, scopes=scopes)
        self.base_url = (
            f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
            f"/databases/(default)/documents"
        )

    def _headers(self) -> dict:
        if not self.creds.valid:
            self.creds.refresh(Request())
        return {
            "Authorization": f"Bearer {self.creds.token}",
            "Content-Type": "application/json",
        }

    def _to_firestore_fields(self, data: dict) -> dict:
        fields = {}
        for k, v in data.items():
            if v is None:
                fields[k] = {"nullValue": None}
            elif isinstance(v, bool):
                fields[k] = {"booleanValue": v}
            elif isinstance(v, int):
                fields[k] = {"integerValue": str(v)}
            elif isinstance(v, datetime):
                fields[k] = {"timestampValue": v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            else:
                fields[k] = {"stringValue": str(v)}
        return {"fields": fields}

    def _from_firestore_doc(self, doc: dict) -> dict:
        result = {}
        for k, v in doc.get("fields", {}).items():
            if "stringValue" in v:
                result[k] = v["stringValue"]
            elif "integerValue" in v:
                result[k] = int(v["integerValue"])
            elif "booleanValue" in v:
                result[k] = v["booleanValue"]
            elif "timestampValue" in v:
                result[k] = v["timestampValue"]
            else:
                result[k] = None
        return result

    def job_exists(self, job_id: str) -> bool:
        """Fast pre-check: Returns True if this job URL hash is already in Firestore."""
        url = f"{self.base_url}/job_notifications/{job_id}"
        resp = requests.get(url, headers=self._headers(), timeout=15)
        return resp.status_code == 200

    def is_duplicate_content(self, job: ScrapedJobNotice) -> bool:
        """
        Secondary deduplication check: Returns True if another document in Firestore
        already has the same (agency + vacancies) or (agency + post_name) so duplicate
        links across 'Job Notifications' and 'State Job Notifications' are never queued twice.
        """
        url = f"{self.base_url}:runQuery"
        query_payload = {
            "structuredQuery": {
                "from": [{"collectionId": "job_notifications"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "agency"},
                        "op": "EQUAL",
                        "value": {"stringValue": job.agency},
                    }
                },
            }
        }
        resp = requests.post(url, headers=self._headers(), json=query_payload, timeout=15)
        if not resp.ok:
            return False

        for item in resp.json():
            if "document" not in item:
                continue
            existing = self._from_firestore_doc(item["document"])
            if existing.get("job_id") == job.job_id:
                continue

            # Match 1: Same agency + same numeric vacancy count (e.g., DGQA + 32)
            if (
                str(job.vacancies) not in ("Multiple", "Refer Notice", "0")
                and str(existing.get("vacancies")) == str(job.vacancies)
            ):
                return True

            # Match 2: Same agency + exact same post_name
            if existing.get("post_name", "").strip().lower() == job.post_name.strip().lower():
                return True

        return False

    def save_job_to_queue(self, job: ScrapedJobNotice) -> None:
        """
        Saves a scraped job into Firestore.
        If the document already exists with status='PUBLISHED', preserves its PUBLISHED status.
        """
        url = f"{self.base_url}/job_notifications/{job.job_id}"
        existing_resp = requests.get(url, headers=self._headers(), timeout=15)
        if existing_resp.status_code == 200:
            existing_doc = self._from_firestore_doc(existing_resp.json())
            if existing_doc.get("status") == "PUBLISHED":
                job.status = "PUBLISHED"
                print(f"   [DB] Preserved PUBLISHED status for: {job.agency} - {job.post_name[:35]}")

        payload = self._to_firestore_fields(job.model_dump())
        resp = requests.patch(url, headers=self._headers(), json=payload, timeout=15)
        resp.raise_for_status()
        if job.status == "QUEUED":
            print(f"   [DB] Queued: {job.agency} - {job.post_name[:35]} (Score: {job.priority_score})")

    def get_next_batch_to_publish(self, batch_size: int = 3) -> list[dict]:
        """Fetches 'QUEUED' jobs and returns the top N ordered by priority_score."""
        url = f"{self.base_url}:runQuery"
        query_payload = {
            "structuredQuery": {
                "from": [{"collectionId": "job_notifications"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "status"},
                        "op": "EQUAL",
                        "value": {"stringValue": "QUEUED"},
                    }
                },
            }
        }
        resp = requests.post(url, headers=self._headers(), json=query_payload, timeout=15)
        resp.raise_for_status()

        queued_jobs = [
            self._from_firestore_doc(item["document"])
            for item in resp.json()
            if "document" in item
        ]

        queued_jobs.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        return queued_jobs[:batch_size]

    def mark_status(self, job_id: str, status: str) -> None:
        """Updates job status to 'PUBLISHED' or 'FAILED'."""
        url = (
            f"{self.base_url}/job_notifications/{job_id}"
            f"?updateMask.fieldPaths=status&updateMask.fieldPaths=published_at"
        )
        update_data = {
            "status": status,
            "published_at": datetime.now(timezone.utc) if status == "PUBLISHED" else None,
        }
        payload = self._to_firestore_fields(update_data)
        resp = requests.patch(url, headers=self._headers(), json=payload, timeout=15)
        resp.raise_for_status()
        print(f"   [DB] Updated {job_id} -> {status}")