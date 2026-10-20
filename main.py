import os
import re
import json
import time
import hashlib
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from models import ScrapedJobNotice
from database import FirestoreManager

load_dotenv()


class JobScraper:
    def __init__(self, db: FirestoreManager):
        self.db = db
        self.base_url = "https://www.freejobalert.com"
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_tpm_limit = int(os.getenv("GROQ_TPM_LIMIT", "8000"))
        self.cache_path = os.getenv("LLM_CACHE_PATH", "llm_cache.json")
        self._cache = self._load_cache()
        self._groq_window: list[tuple[float, int]] = []

        self.age_range_regex = re.compile(
            r"(\d{1,2}(?:\.\d)?\s*(?:years?\s*\d*\s*months?)?\s*(?:to|-|–)\s*\d{1,2}(?:\.\d)?\s*(?:years?\s*\d*\s*months?)?)",
            re.IGNORECASE,
        )
        self.age_max_regex = re.compile(
            r"(?:up\s*to|maximum|max\.?|not\s*exceeding|age\s*limit\s*is)\s*(\d{2}\s*years?)",
            re.IGNORECASE,
        )
        self.date_regex = re.compile(
            r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[a-z]*[,.\s]+\d{4})\b",
            re.IGNORECASE,
        )
        self.gov_domain_regex = re.compile(
            r"\b((?:https?://)?(?:www\.)?[a-zA-Z0-9-]+\.(?:gov\.in|nic\.in|org\.in|ac\.in|res\.in|edu\.in|co\.in|bank\.in|indianrailways\.gov\.in)(?:/[^\s,.)\"\'<>]*)?)\b",
            re.IGNORECASE,
        )

        self.table_header_blacklist = (
            "vacancies", "vacancy", "no. of posts", "no of posts", "total posts",
            "minimum age", "maximum age", "upper age limit", "age limit", "age",
            "pay level", "pay scale", "pay matrix", "basic pay", "salary", "stipend",
            "medical standard", "educational qualification", "minimum qualification",
            "qualification", "eligibility", "post code", "sl. no", "s. no", "sr. no",
            "category", "grade", "stream", "discipline", "department", "ur", "obc", "sc", "st"
        )

        self.blocked_url_keywords = (
            "freejobalert", "whatsapp", "wa.me", "t.me", "telegram",
            "play.google", "apps.apple", "youtube.com", "youtu.be",
            "facebook.com", "fb.com", "twitter.com", "x.com",
            "instagram.com", "linkedin.com", "pinterest.com",
            "addtoany.com", "sharethis.com", "google.com",
            "bit.ly", "tinyurl.com", "linktr.ee", "javascript:", "mailto:"
        )

    def generate_job_id(self, url: str) -> str:
        clean_url = url.split("#")[0].split("?")[0].rstrip("/").strip().lower()
        return hashlib.md5(clean_url.encode("utf-8")).hexdigest()

    def _is_valid_official_url(self, href: str) -> bool:
        if not href:
            return False
        href_clean = href.strip().lower()
        if not href_clean.startswith("http"):
            return False
        if any(bad in href_clean for bad in self.blocked_url_keywords):
            return False
        parsed = urlparse(href_clean)
        return bool(parsed.netloc and "." in parsed.netloc)

    def _is_fake_table_header_value(self, val: str) -> bool:
        clean_v = val.lower().strip()
        if not clean_v or len(clean_v) < 2:
            return True
        return any(
            clean_v == bad or clean_v.startswith(bad)
            for bad in self.table_header_blacklist
        )

    def _calculate_dynamic_score(self, vacancies: int, is_today: bool = True) -> int:
        freshness_score = 100 if is_today else 40
        if vacancies >= 1000:
            scale_score = 30
        elif vacancies >= 100:
            scale_score = 20
        else:
            scale_score = 10
        return freshness_score + scale_score

    # ------------------------------------------------------------------
    # LLM helpers (cache + pacing + retry)
    # ------------------------------------------------------------------
    def _load_cache(self) -> dict:
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"   [CACHE] could not save: {e}")

    @staticmethod
    def _cache_key(h1_title: str, text: str) -> str:
        return hashlib.md5((h1_title + "||" + text).encode("utf-8")).hexdigest()

    def _compact_for_llm(self, raw: dict) -> str:
        lines = []
        for r in raw["table_rows"]:
            if r["colCount"] == 2 and r["key"]:
                lines.append(f"{r['key']}: {r['firstVal'][:200]}")
            if len(lines) >= 40:
                break
        table_text = "\n".join(lines)
        article = raw["full_article_text"][:3000]
        return f"TABLE FIELDS:\n{table_text}\n\nARTICLE TEXT:\n{article}"[:5000]

    def _groq_wait_for_budget(self, est_tokens: int) -> None:
        budget = int(self.groq_tpm_limit * 0.85)
        while True:
            now = time.time()
            self._groq_window = [(t, n) for (t, n) in self._groq_window if now - t < 60]
            used = sum(n for _, n in self._groq_window)
            if used + est_tokens <= budget or not self._groq_window:
                return
            wait = 60.0 - (now - self._groq_window[0][0]) + 0.5
            print(f"   [GROQ] pacing: waiting {wait:.0f}s for token budget...")
            time.sleep(max(wait, 1.0))

    def _post_with_retry(self, url: str, label: str, max_attempts: int = 3, **kwargs):
        last_err = None
        for attempt in range(1, max_attempts + 1):
            resp = requests.post(url, timeout=45, **kwargs)
            if resp.ok:
                return resp
            last_err = f"{resp.status_code} {resp.text[:200]}"
            if resp.status_code == 429:
                m = re.search(r"try again in ([\d.]+)\s*(ms|s)", resp.text)
                wait = (float(m.group(1)) / (1000.0 if m.group(2) == "ms" else 1.0)) if m else 10.0
                wait = min(wait + 1.0, 30.0)
            elif resp.status_code >= 500:
                wait = float(3 * attempt)
            else:
                break
            if attempt < max_attempts:
                print(f"   [{label}] {resp.status_code}, retry {attempt}/{max_attempts - 1} in {wait:.0f}s")
                time.sleep(wait)
        raise RuntimeError(last_err)

    def _call_groq(self, system_instructions: str, user_prompt: str) -> dict | None:
        if not self.groq_api_key:
            return None
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        max_out = 1024
        est = int((len(system_instructions) + len(user_prompt)) / 3.2) + max_out
        self._groq_wait_for_budget(est)
        try:
            resp = self._post_with_retry(
                "https://api.groq.com/openai/v1/chat/completions",
                f"GROQ:{model}",
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_instructions},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.0,
                    "reasoning_effort": "low",
                    "max_completion_tokens": max_out,
                    "response_format": {"type": "json_object"},
                },
            )
            self._groq_window.append((time.time(), est))
            return self._parse_llm_json(resp.json()["choices"][0]["message"]["content"])
        except Exception as e:
            self._groq_window.append((time.time(), est))
            print(f"   [GROQ FAILED:{model}] {e}")
            return None

    def _call_gemini(self, system_instructions: str, user_prompt: str) -> dict | None:
        if not self.gemini_api_key:
            return None
        models = [
            m.strip() for m in os.getenv(
                "GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash"
            ).split(",") if m.strip()
        ]
        payload = {
            "contents": [{"parts": [{"text": f"{system_instructions}\n\n{user_prompt}"}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        for model in models:
            try:
                resp = self._post_with_retry(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    f"GEMINI:{model}",
                    headers={"x-goog-api-key": self.gemini_api_key},
                    json=payload,
                )
                parts = resp.json()["candidates"][0]["content"]["parts"]
                raw_json = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                time.sleep(2.0)
                return self._parse_llm_json(raw_json)
            except Exception as e:
                print(f"   [GEMINI FAILED:{model}] {e}")
        return None

    @staticmethod
    def _parse_llm_json(text: str) -> dict:
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        return json.loads(text)

    def _extract_with_llm(self, h1_title: str, clean_article_text: str, valid_links: list[dict]) -> dict | None:
        system_instructions = (
            "You are a precise data extractor for Indian government job notifications. "
            "Respond ONLY with a valid JSON object matching this exact schema:\n"
            "{\n"
            '  "agency": "Short uppercase recruiting organization name (e.g. INDIAN ARMY, BHEL, RRB, UCO BANK, DGQA)",\n'
            '  "post_name": "Actual job role title (e.g. Technician, Apprentice, NTPC Graduate & UG Posts, TES-57 Officer). NEVER return column headers like Vacancies, Minimum Age, or Pay Level.",\n'
            '  "vacancies_int": 0,\n'
            '  "qualification": "Concise eligibility requirement under 65 chars (e.g. 12th Pass / Graduate / ITI)",\n'
            '  "age_limit": "Age criteria (e.g. 18 - 27 Years or Up to 30 Years)",\n'
            '  "last_date": "Exact closing/last date to apply (e.g. 12 November 2026 or 21 Days from Emp. News). Do NOT use the opening/start date.",\n'
            '  "official_apply_url": "Direct official government URL from the provided links or text"\n'
            "}"
        )
        user_prompt = (
            f"HEADLINE: {h1_title}\n\n"
            f"VERIFIED EXTERNAL LINKS:\n{json.dumps(valid_links[:6])}\n\n"
            f"{clean_article_text}"
        )

        key = self._cache_key(h1_title, user_prompt)
        if key in self._cache:
            print("   [LLM] cache hit")
            return self._cache[key]

        providers = {"gemini": self._call_gemini, "groq": self._call_groq}
        order = [p.strip().lower() for p in os.getenv("LLM_ORDER", "groq,gemini").split(",")]
        for name in order:
            fn = providers.get(name)
            if not fn:
                continue
            result = fn(system_instructions, user_prompt)
            if result:
                self._cache[key] = result
                self._save_cache()
                return result
        return None

    def _parse_headline_fallbacks(self, h1_title: str) -> tuple[str, str, int]:
        clean = h1_title.replace("–", "-").replace("—", "-")
        no_10_plus_2 = re.sub(r"10\+2", "", clean)

        vacancy_count = 0
        explicit_vac = re.search(
            r"\b(\d[\d,]*)\s+(?:Posts?|Vacanc(?:y|ies)|Seats?)\b", no_10_plus_2, re.IGNORECASE
        )
        if explicit_vac:
            vacancy_count = int(explicit_vac.group(1).replace(",", ""))
        else:
            for num_str in re.findall(r"\b(\d[\d,]*)\b", no_10_plus_2):
                val = int(num_str.replace(",", ""))
                if val not in (6, 10, 12, 57, 2024, 2025, 2026, 2027, 2028) and val > vacancy_count:
                    vacancy_count = val

        post_name = ""
        apply_match = re.search(
            r"Apply\s+(?:Online|Offline)\s+(?:for\s+)?(?:\d[\d,]*\s+)?(.+?)(?:\s+Posts?|\s+Vacanc(?:y|ies))?$",
            clean, re.IGNORECASE
        )
        if apply_match:
            post_name = apply_match.group(1).strip(" -–/")
        else:
            stripped = re.sub(
                r"\s*(?:Online\s+Form|Offline\s+Form|Walk-in\s+Form|Walk-in|Recruitment(?:\s+Rally)?|Notification|Rally)?\s*\d{4}.*$",
                "", clean, flags=re.IGNORECASE
            ).strip()
            num_split = re.split(r"\b\d[\d,]*\b", stripped, maxsplit=1)
            if len(num_split) == 2 and num_split[1].strip():
                post_name = num_split[1].strip(" -–,")
            else:
                words = stripped.split()
                post_name = " ".join(words[1:]) if len(words) > 1 else stripped

        if not post_name or post_name.lower() == "various posts":
            post_name = "Multiple Posts"

        agency_part = re.split(
            r"\b(?:\d[\d,]*|Various|Online|Offline|Walk-in|Recruitment|Notification)\b",
            clean, maxsplit=1, flags=re.IGNORECASE
        )[0].strip(" -–")
        agency = agency_part.upper() if agency_part else "GOVT JOB"

        return agency, post_name, vacancy_count

    def scout_job_notifications_section(self, page) -> list[dict]:
        """
        STRICTLY scrapes ONLY the bulleted lists directly under:
        1. 'Job Notifications'
        2. 'State Job Notifications'
        Deduplicates across both lists by canonical URL and 7-digit Article ID.
        """
        print("Opening FreeJobAlert homepage and locating 'Job Notifications' & 'State Job Notifications' columns...")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)

        links_data = page.evaluate("""() => {
            const targetHeaders = ['Job Notifications', 'State Job Notifications'];
            const allElements = Array.from(document.querySelectorAll('h2, h3, th, td, div, span'));
            const results = [];

            for (const headerName of targetHeaders) {
                const headerEl = allElements.find(el => {
                    const normalized = el.textContent.replace(/\\s+/g, ' ').trim();
                    return el.children.length === 0 && normalized === headerName;
                });

                if (!headerEl) continue;

                let colBox = headerEl.parentElement;
                while (colBox && colBox.querySelectorAll('ul').length === 0) {
                    colBox = colBox.parentElement;
                }
                if (!colBox) continue;

                const jobList = colBox.querySelector('ul');
                if (!jobList) continue;

                Array.from(jobList.querySelectorAll('li a')).forEach(a => {
                    results.push({
                        section: headerName,
                        title: a.innerText.trim(),
                        url: a.href
                    });
                });
            }

            return results;
        }""")

        valid_targets = []
        seen_urls = set()
        seen_article_ids = set()

        for item in links_data:
            title = item.get("title", "")
            raw_url = item.get("url", "")
            if not title or not raw_url:
                continue

            clean_url = raw_url.split("#")[0].split("?")[0].rstrip("/")
            art_id_match = re.search(r"-(\d{6,8})$", clean_url)
            art_id = art_id_match.group(1) if art_id_match else None

            if clean_url in seen_urls or (art_id and art_id in seen_article_ids):
                print(f" [DEDUP SCOUT] Skipping cross-section duplicate: {title[:45]}...")
                continue

            lower_title = title.lower()
            if any(bad in lower_title for bad in [
                "admit card", "result", "answer key", "syllabus",
                "whatsapp", "mobile app", "telegram", "view all"
            ]):
                continue

            seen_urls.add(clean_url)
            if art_id:
                seen_article_ids.add(art_id)
            valid_targets.append({"title": title, "url": clean_url})

        print(f"Scout found {len(valid_targets)} unique listings across 'Job Notifications' & 'State Job Notifications'.")
        return valid_targets

    def scrape_job_page(self, page, target: dict, job_id: str) -> dict:
        """PHASE 1: browser scrape only. No LLM, no DB."""
        url = target["url"]
        raw_title = target["title"]
        print(f" -> Scraping job page: {raw_title}...")

        page.goto(url, wait_until="domcontentloaded", timeout=45000)

        page_data = page.evaluate("""() => {
            const root = document.querySelector('article, .entry-content, main') || document.body;
            const h1 = document.querySelector('h1')?.innerText.trim() || '';

            const tableRows = [];
            root.querySelectorAll('table tr').forEach((tr, rowIndex) => {
                const thCount = tr.querySelectorAll('th').length;
                const tdCount = tr.querySelectorAll('td').length;
                if (thCount >= 2 && tdCount === 0) return;

                const cells = Array.from(tr.querySelectorAll('th, td')).map(c => c.innerText.trim());
                const links = Array.from(tr.querySelectorAll('a')).map(a => ({
                    text: a.innerText.trim().toLowerCase(),
                    href: a.href
                }));
                if (cells.length >= 2) {
                    tableRows.push({
                        rowIndex,
                        colCount: cells.length,
                        key: cells[0].toLowerCase().replace(/[:*]/g, '').trim(),
                        val: cells.slice(1).join(' | ').trim(),
                        firstVal: cells[1].trim(),
                        links: links
                    });
                }
            });

            const paragraphs = Array.from(root.querySelectorAll('p, li'))
                .map(el => el.innerText.trim())
                .filter(t => t.length > 10 && !t.toLowerCase().includes('whatsapp'));

            const allLinks = Array.from(root.querySelectorAll('a')).map(a => ({
                text: a.innerText.trim().toLowerCase(),
                context: (a.closest('tr, p, li')?.innerText || '').trim().toLowerCase(),
                href: a.href
            }));

            return { h1, tableRows, paragraphs, allLinks, rawText: root.innerText };
        }""")

        h1_title = page_data.get("h1") or raw_title
        table_rows = page_data.get("tableRows", [])
        paragraphs = page_data.get("paragraphs", [])
        all_links = page_data.get("allLinks", [])
        full_article_text = "\n".join(paragraphs)

        verified_external_links = [
            {"label": l["text"], "context": l["context"][:80], "url": l["href"]}
            for l in all_links
            if self._is_valid_official_url(l["href"])
        ]

        combined_scan_text = full_article_text + " " + " ".join(r["val"] for r in table_rows)
        for match in self.gov_domain_regex.finditer(combined_scan_text):
            raw_domain = match.group(1).strip(".,;)")
            candidate_url = raw_domain if raw_domain.startswith("http") else f"https://{raw_domain}"
            if self._is_valid_official_url(candidate_url):
                verified_external_links.append({"label": "plain_text_domain", "context": "article_body", "url": candidate_url})

        return {
            "job_id": job_id,
            "url": url,
            "raw_title": raw_title,
            "h1_title": h1_title,
            "table_rows": table_rows,
            "full_article_text": full_article_text,
            "raw_text": page_data.get("rawText", full_article_text),
            "verified_external_links": verified_external_links,
        }

    def evaluate_scraped(self, raw: dict) -> dict | None:
        """PHASE 2: AI evaluation of one scraped page (cached, paced, retried)."""
        return self._extract_with_llm(
            h1_title=raw["h1_title"],
            clean_article_text=self._compact_for_llm(raw),
            valid_links=raw["verified_external_links"],
        )

    def build_notice(self, raw: dict, llm_data: dict | None) -> ScrapedJobNotice:
        """PHASE 3a: turn scraped data (+ optional AI result) into a ScrapedJobNotice."""
        job_id = raw["job_id"]
        url = raw["url"]
        raw_title = raw["raw_title"]
        table_rows = raw["table_rows"]
        full_article_text = raw["full_article_text"]
        verified_external_links = raw["verified_external_links"]

        hl_agency, hl_post_name, hl_vacancies = self._parse_headline_fallbacks(raw_title)

        if llm_data:
            agency = (llm_data.get("agency") or hl_agency).strip().upper()
            post_name = (llm_data.get("post_name") or hl_post_name).strip()
            if self._is_fake_table_header_value(post_name):
                post_name = hl_post_name
            vacancy_count = int(llm_data.get("vacancies_int") or hl_vacancies or 0)
            qualification = (llm_data.get("qualification") or "Refer Official Notification").strip()
            age_limit = (llm_data.get("age_limit") or "As per official rules").strip()
            last_date = (llm_data.get("last_date") or "Refer Official Notice").strip()
            candidate_link = (llm_data.get("official_apply_url") or "").strip()

            if candidate_link and not candidate_link.startswith("http") and "." in candidate_link:
                candidate_link = f"https://{candidate_link}"

            final_official_link = (
                candidate_link
                if self._is_valid_official_url(candidate_link)
                else (verified_external_links[0]["url"] if verified_external_links else "Refer Official Notification")
            )
            vacancies_str = str(vacancy_count) if vacancy_count > 0 else "Multiple"
            priority = self._calculate_dynamic_score(vacancy_count, is_today=True)

            return ScrapedJobNotice(
                job_id=job_id,
                raw_title=raw_title,
                detail_page_url=url,
                agency=agency,
                post_name=post_name,
                vacancies=vacancies_str,
                qualification=qualification,
                age_limit=age_limit,
                last_date=last_date,
                official_apply_url=final_official_link,
                official_website=final_official_link,
                status="QUEUED",
                priority_score=priority,
            )

        # --- LAYER 2: Bulletproof Deterministic Parser ---
        agency, post_name, vacancy_count = hl_agency, hl_post_name, hl_vacancies
        qualification = "Refer Official Notification"
        age_limit = "As per official rules"
        last_date = ""
        apply_url = None
        official_site = None

        for row in table_rows:
            key = row["key"]
            val = row["firstVal"]
            full_val = row["val"]
            links = row["links"]

            if row["rowIndex"] == 0 and self._is_fake_table_header_value(val):
                continue

            if key in ("organisation", "organization", "recruiting body", "company name", "department", "board"):
                if val and len(val) < 100 and not self._is_fake_table_header_value(val):
                    acronym = re.search(r"\(([A-Z]{2,10})\)", val)
                    agency = acronym.group(1) if acronym else val.split(",")[0].strip().upper()[:35]

            elif row["colCount"] == 2 and key in (
                "post name", "post names", "post name(s)", "name of the post",
                "name of post", "post / trade name", "post"
            ):
                if val and len(val) < 95 and not val.isdigit() and not self._is_fake_table_header_value(val):
                    post_name = val

            elif row["colCount"] == 2 and key in (
                "vacancies", "total vacancies", "no of posts", "no. of posts", "total posts", "vacancy"
            ):
                nums = re.findall(r"\b(\d[\d,]*)\b", val)
                if nums:
                    vacancy_count = int(nums[0].replace(",", ""))

            elif row["colCount"] == 2 and any(k == key or key.startswith(k) for k in (
                "qualification", "educational qualification", "essential qualification",
                "eligibility", "who can apply", "education"
            )):
                if val and len(val) < 140 and not self._is_fake_table_header_value(val):
                    qualification = val

            elif row["colCount"] == 2 and key in (
                "age limit", "age", "maximum age", "age requirement", "upper age limit"
            ):
                if val and len(val) < 90 and not self._is_fake_table_header_value(val):
                    age_limit = val

            elif any(k in key for k in (
                "last date", "closing date", "end date", "apply till",
                "submission of application", "application close"
            )) and not any(start_w in key for start_w in ("start", "opening", "begin", "commence")):
                all_dates_in_row = self.date_regex.findall(full_val)
                if all_dates_in_row:
                    last_date = all_dates_in_row[-1]
                elif "days from" in full_val.lower() or "employment news" in full_val.lower():
                    last_date = "21 Days from Emp. News" if "21" in full_val else "Within Prescribed Days"

            if any(k in key for k in ("apply online", "online form", "registration", "application link")):
                for l_item in links:
                    if self._is_valid_official_url(l_item["href"]) and not l_item["href"].lower().endswith(".pdf"):
                        apply_url = l_item["href"]
                        break

            if any(k in key for k in ("official website", "official portal", "web portal")):
                for l_item in links:
                    if self._is_valid_official_url(l_item["href"]) and not l_item["href"].lower().endswith(".pdf"):
                        official_site = l_item["href"]
                        break

        if not last_date:
            date_patterns = [
                r"from\s+\d{1,2}[-/.\s]+[A-Za-z0-9]+[-/.\s]+\d{4}\s+to\s+(\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
                r"(?:last\s+date|closing\s+date|applications?\s+close(?:\s+on)?|accepted\s+till|apply\s+(?:online\s+)?(?:on\s+or\s+)?before|complete\s+the\s+application\s+(?:process\s+)?by|open\s+until|received\s+by|deadline\s+is)\s*[:\-–]?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            ]
            for pat in date_patterns:
                m = re.search(pat, full_article_text, re.IGNORECASE)
                if m:
                    last_date = m.group(1).strip()
                    break

        if not last_date:
            last_date = (
                "21 Days from Publication"
                if "21 days from" in full_article_text.lower()
                else "Refer Official Notice"
            )

        if age_limit == "As per official rules":
            m_range = self.age_range_regex.search(full_article_text)
            if m_range:
                age_limit = m_range.group(1).strip()
            else:
                m_max = self.age_max_regex.search(full_article_text)
                if m_max:
                    age_limit = f"Up to {m_max.group(1).strip()}"

        if qualification == "Refer Official Notification":
            qual_patterns = [
                r"(?:must\s+have\s+passed|qualification\s+in|candidates\s+with\s+a|possess\s+a)\s+([^.;]{10,85})",
                r"(10\+2\s+with\s+[^.;]{5,60}|Class\s+12\s+[^.;]{5,60}|ITI\s+certificate[^.;]{0,50}|Bachelor['’]?s\s+Degree[^.;]{0,50}|Post\s+Graduation\s+in\s+[^.;]{5,60})",
            ]
            for pat in qual_patterns:
                m_q = re.search(pat, full_article_text, re.IGNORECASE)
                if m_q:
                    qualification = m_q.group(1).strip()
                    break

        non_pdf_links = [l["url"] for l in verified_external_links if not l["url"].lower().endswith(".pdf")]
        final_official_link = (
            apply_url
            or official_site
            or (non_pdf_links[0] if non_pdf_links else None)
            or (verified_external_links[0]["url"] if verified_external_links else "Refer Official Notification")
        )
        vacancies_str = str(vacancy_count) if vacancy_count > 0 else "Multiple"
        priority = self._calculate_dynamic_score(vacancy_count, is_today=True)

        return ScrapedJobNotice(
            job_id=job_id,
            raw_title=raw_title,
            detail_page_url=url,
            agency=agency,
            post_name=post_name,
            vacancies=vacancies_str,
            qualification=qualification,
            age_limit=age_limit,
            last_date=last_date,
            official_apply_url=final_official_link,
            official_website=official_site,
            status="QUEUED",
            priority_score=priority,
        )

    def deep_dive(self, page, target: dict, job_id: str) -> ScrapedJobNotice:
        raw = self.scrape_job_page(page, target, job_id)
        return self.build_notice(raw, self.evaluate_scraped(raw))

    def sync_new_jobs_to_firestore(self, force_rescrape: bool = False) -> int:
        # ---------------- PHASE 1: scrape 'Job Notifications' & 'State Job Notifications' ----------------
        scraped: list[dict] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            targets = self.scout_job_notifications_section(page)

            for item in targets:
                job_id = self.generate_job_id(item["url"])

                # Pre-check against Firestore before opening any job page
                if not force_rescrape and self.db.job_exists(job_id):
                    print(f" [SKIP] Already in DB: {item['title'][:45]}...")
                    continue

                try:
                    scraped.append(self.scrape_job_page(page, item, job_id))
                except Exception as e:
                    print(f"Error scraping {item['url']}: {e}")

            browser.close()

        if not scraped:
            print("\nNo new jobs to evaluate. All listings in both sections are already in Firestore!")
            return 0

        print(f"\n[PHASE 1] Scraped {len(scraped)} new job page(s).")

        # ---------------- PHASE 2: AI evaluation (cached + paced) ----------------
        print("[PHASE 2] AI evaluation...")
        evaluated: list[tuple[dict, dict | None]] = []
        ai_ok = 0
        for idx, raw in enumerate(scraped, start=1):
            print(f" ({idx}/{len(scraped)}) {raw['raw_title'][:60]}")
            try:
                llm_data = self.evaluate_scraped(raw)
            except Exception as e:
                print(f"   [AI ERROR] {e}")
                llm_data = None
            if llm_data:
                ai_ok += 1
            evaluated.append((raw, llm_data))

        print(f"[PHASE 2] AI succeeded for {ai_ok}/{len(scraped)}; rest use the deterministic parser.")

        # ---------------- PHASE 3: deduplicate (in-memory + DB) & write to Firestore ----------------
        print("[PHASE 3] Saving to Firestore...")
        new_count = 0
        batch_seen_keys = set()

        for raw, llm_data in evaluated:
            try:
                notice = self.build_notice(raw, llm_data)

                # 1. In-memory check for two different URLs in the same run that resolved to the same job
                mem_key = f"{notice.agency}_{notice.vacancies}_{notice.post_name.lower()[:15]}"
                if mem_key in batch_seen_keys:
                    print(f"   [SKIP BATCH DUPLICATE] {notice.agency} - {notice.post_name} already processed in this run.")
                    continue

                # 2. Firestore check against previously saved jobs
                if not force_rescrape and self.db.is_duplicate_content(notice):
                    print(
                        f"   [SKIP DB DUPLICATE] {notice.agency} - {notice.post_name} "
                        f"({notice.vacancies} posts) already in Firestore."
                    )
                    continue

                batch_seen_keys.add(mem_key)
                self.db.save_job_to_queue(notice)
                new_count += 1
            except Exception as e:
                print(f"Error saving {raw['url']}: {e}")

        print(f"\nSync complete! Added {new_count} new job(s) to Firestore queue.")
        return new_count


if __name__ == "__main__":
    db_manager = FirestoreManager()
    scraper = JobScraper(db=db_manager)

    # Normal mode (force_rescrape=False): only scrapes brand-new jobs not yet in Firestore
    scraper.sync_new_jobs_to_firestore(force_rescrape=False)

    print("\n--- TOP 5 QUEUED JOBS IN FIRESTORE ---")
    top_batch = db_manager.get_next_batch_to_publish(batch_size=5)
    for idx, job in enumerate(top_batch, start=1):
        print(
            f"{idx}. [{job['priority_score']} pts] {job['agency']} | "
            f"Post: {job['post_name']} | Vacancies: {job['vacancies']} | "
            f"Last Date: {job['last_date']} | Link: {job['official_apply_url']}"
        )