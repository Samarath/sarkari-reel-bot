import {
  BookOpen,
  GraduationCap,
  Calendar,
  UserCheck,
  ArrowUpRight,
  Bookmark,
  Building2,
  Users,
  Laptop,
  Sparkles,
} from "lucide-react";
import React, { useState, useMemo, useRef, useLayoutEffect } from "react";

// Aspirant & Student-Centric Background Themes (Bright White / Study Aesthetic)
const ASPIRANT_THEMES = [
  {
    id: "physical_rally",
    keywords: ["army", "navy", "air force", "defence", "nda", "cds", "crpf", "itbp", "bsf", "assam rifles", "police", "constable", "icg", "dgqa"],
    tag: "DEFENCE & PHYSICAL BHARTI",
    studyVibe: "Aspirant Ground & Prep",
    accent: "#15803D", // Forest Green
    accentSoft: "#DCFCE7",
    highlight: "#BBF7D0",
    // Morning track / physical training run
    bgUrl: "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&q=85",
  },
  {
    id: "desk_study",
    keywords: ["upsc", "civil services", "ias", "psc", "cabinet secretariat", "supreme court", "high court", "ccras"],
    tag: "OFFICER & COMMISSION EXAM",
    studyVibe: "Library & Syllabus Prep",
    accent: "#B91C1C", // Crimson Ink
    accentSoft: "#FEE2E2",
    highlight: "#FECACA",
    // Student studying with books and notes at desk
    bgUrl: "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?auto=format&fit=crop&w=1200&q=85",
  },
  {
    id: "online_form",
    keywords: ["bank", "uco", "sbi", "ibps", "rbi", "nabard", "canara", "clerk", "apprentice", "so", "po"],
    tag: "BANKING & ONLINE APPLICATION",
    studyVibe: "Online Form & Mock Test",
    accent: "#1D4ED8", // Royal Pen Blue
    accentSoft: "#DBEAFE",
    highlight: "#BFDBFE",
    // Student applying online on laptop with notebooks
    bgUrl: "https://images.unsplash.com/photo-1513258496099-48168024aec0?auto=format&fit=crop&w=1200&q=85",
  },
  {
    id: "exam_hall",
    keywords: ["rrb", "railway", "ntpc", "metro", "dmrc", "bhel", "isro", "drdo", "oil india", "npcc", "cdac", "artisan", "technician", "engineer"],
    tag: "TECHNICAL & RAILWAY EXAM",
    studyVibe: "Competitive Exam Alert",
    accent: "#0369A1", // Deep Sky Blue
    accentSoft: "#E0F2FE",
    highlight: "#BAE6FD",
    // Students studying in library / desk setup
    bgUrl: "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?auto=format&fit=crop&w=1200&q=85",
  },
];

// Default Student Study Fallback Pool (Used when agency is a state/local board)
const DEFAULT_STUDY_BACKGROUNDS = [
  "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1200&q=85", // Students studying together with laptop & notes
  "https://images.unsplash.com/photo-1488190211105-8b0e65b80b4e?auto=format&fit=crop&w=1200&q=85", // Student writing notes & preparing application
  "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=1200&q=85", // Student filling online form on laptop
];

// Presets for browser preview
const SAMPLE_PRESETS = {
  study: {
    agency: "UPSC / STATE PSC",
    raw_title: "UPSC Civil Services Examination 2026",
    post_name: "IAS / IPS / IFS All India Services",
    vacancies: "1056",
    qualification: "Bachelor's Degree in Any Stream",
    age_limit: "21 - 32 Years",
    last_date: "05 Nov 2026",
    official_apply_url: "https://upsc.gov.in/apply-online",
  },
  applying: {
    agency: "CANARA BANK",
    raw_title: "Canara Bank 3500 Apprentice Online Form 2026",
    post_name: "Graduate Apprentice",
    vacancies: "3500",
    qualification: "Graduation Degree in Any Discipline",
    age_limit: "20 - 28 Years",
    last_date: "17 October 2026",
    official_apply_url: "https://ibpsreg.ibps.in/cabgasep26/",
  },
  running: {
    agency: "ASSAM RIFLES",
    raw_title: "Assam Rifles 354 Technical & Tradesman Rally 2026",
    post_name: "Technical & Tradesman",
    vacancies: "354",
    qualification: "10th / 12th Pass / ITI / Diploma",
    age_limit: "18 - 23 Years",
    last_date: "28 October 2026",
    official_apply_url: "https://assamrifles.gov.in",
  },
  general: {
    agency: "DSSSB DELHI",
    raw_title: "DSSSB 641 Peon, PA and More Posts Online Form 2026",
    post_name: "Peon, Personal Assistant & Group C",
    vacancies: "641",
    qualification: "10th / 12th Pass / Graduate",
    age_limit: "18 - 27 Years",
    last_date: "28 Oct 2026",
    official_apply_url: "https://dsssb.delhi.gov.in",
  },
};

function cleanDomain(url) {
  if (!url || url.toLowerCase().includes("refer")) return "Check Official Notification";
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host;
  } catch {
    return url;
  }
}

function FitLink({ text, color, maxFont = 40, minFont = 12, boxHeight = 120 }) {
  const boxRef = useRef(null);
  const textRef = useRef(null);

  useLayoutEffect(() => {
    const fit = () => {
      const box = boxRef.current;
      const el = textRef.current;
      if (!box || !el) return;
      let size = maxFont;
      el.style.fontSize = `${size}px`;
      while (size > minFont && el.offsetHeight > box.clientHeight) {
        size -= 1;
        el.style.fontSize = `${size}px`;
      }
    };
    fit();
    // re-fit once web fonts load, since they change text width
    if (document.fonts?.ready) document.fonts.ready.then(fit);
  }, [text, maxFont, minFont]);

  return (
    <div ref={boxRef} style={{ height: boxHeight }} className="w-full flex items-center">
      <span
        ref={textRef}
        style={{ color, lineHeight: 1.15 }}
        className="block w-full font-mono-code font-extrabold break-all"
      >
        {text}
      </span>
    </div>
  );
}

export default function App() {
  const [presetKey, setPresetKey] = useState("applying");

  const searchParams = new URLSearchParams(window.location.search);
  const isCaptureMode = searchParams.get("capture") === "true";

  const jobData = useMemo(() => {
    if (window.__JOB_DATA__) return window.__JOB_DATA__;
    const encoded = searchParams.get("job");
    if (encoded) {
      try {
        return JSON.parse(decodeURIComponent(encoded));
      } catch (e) {
        console.error("Failed to parse job query param:", e);
      }
    }
    return SAMPLE_PRESETS[presetKey];
  }, [presetKey, searchParams]);

  // Match every job to an aspirant study/running/applying theme
  const theme = useMemo(() => {
    if (jobData.bg_image) {
      return {
        tag: "SARKARI EXAM ALERT",
        studyVibe: "Aspirant Desk Update",
        accent: "#1D4ED8",
        accentSoft: "#DBEAFE",
        highlight: "#FEF08A",
        bgUrl: jobData.bg_image,
      };
    }

    const combined = `${jobData.agency} ${jobData.raw_title} ${jobData.post_name}`.toLowerCase();
    const found = ASPIRANT_THEMES.find((t) =>
      t.keywords.some((kw) => combined.includes(kw))
    );
    if (found) return found;

    // Deterministic student background selection based on title length
    const fallbackIdx = combined.length % DEFAULT_STUDY_BACKGROUNDS.length;
    return {
      tag: "SARKARI JOB NOTIFICATION",
      studyVibe: "Student Application Alert",
      accent: "#4338CA", // Indigo Ink
      accentSoft: "#E0E7FF",
      highlight: "#FEF08A",
      bgUrl: DEFAULT_STUDY_BACKGROUNDS[fallbackIdx],
    };
  }, [jobData]);

  const domain = cleanDomain(jobData.official_apply_url);
  const isOffline = `${jobData.raw_title}`.toLowerCase().includes("offline");

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-200">
      {/* DEV PREVIEW BAR (Hidden automatically when Playwright captures) */}
      {!isCaptureMode && (
        <div className="fixed top-4 z-50 flex flex-wrap gap-2 bg-white/95 backdrop-blur border border-slate-300 px-5 py-2.5 rounded-full text-sm text-slate-800 shadow-xl">
          <span className="text-slate-500 font-semibold self-center mr-2">
            Student Theme Preview:
          </span>
          <button
            onClick={() => setPresetKey("applying")}
            className={`px-3.5 py-1 rounded-full cursor-pointer transition ${
              presetKey === "applying"
                ? "bg-blue-700 text-white font-bold"
                : "bg-slate-100 hover:bg-slate-200"
            }`}
          >
            Student Applying (Laptop)
          </button>
          <button
            onClick={() => setPresetKey("study")}
            className={`px-3.5 py-1 rounded-full cursor-pointer transition ${
              presetKey === "study"
                ? "bg-red-700 text-white font-bold"
                : "bg-slate-100 hover:bg-slate-200"
            }`}
          >
            Student Studying (Books)
          </button>
          <button
            onClick={() => setPresetKey("running")}
            className={`px-3.5 py-1 rounded-full cursor-pointer transition ${
              presetKey === "running"
                ? "bg-green-700 text-white font-bold"
                : "bg-slate-100 hover:bg-slate-200"
            }`}
          >
            Physical Rally (Running)
          </button>
          <button
            onClick={() => setPresetKey("general")}
            className={`px-3.5 py-1 rounded-full cursor-pointer transition ${
              presetKey === "general"
                ? "bg-indigo-700 text-white font-bold"
                : "bg-slate-100 hover:bg-slate-200"
            }`}
          >
            General Study Desk
          </button>
        </div>
      )}

      {/* =====================================================================
          MASTER REEL CANVAS (Strictly 1080x1920 for Instagram/Facebook Reels)
         ===================================================================== */}
      <div
        id="reel-canvas"
        style={{ width: "1080px", height: "1920px" }}
        className="relative overflow-hidden select-none shrink-0 bg-white text-slate-900"
      >
        {/* 1. Subtle Notebook Dot-Grid Texture across the white background */}
        <div
          className="absolute inset-0 opacity-40 pointer-events-none"
          style={{
            backgroundImage: "radial-gradient(#CBD5E1 1.5px, transparent 1.5px)",
            backgroundSize: "28px 28px",
          }}
        />

        {/* 2. Top Student / Aspirant Background Image with Bright White Fade */}
        <div className="absolute top-0 left-0 w-full h-[52%] overflow-hidden">
          <img
            src={theme.bgUrl}
            alt="Student Aspirant Background"
            className="w-full h-full object-cover object-center scale-105 filter saturate-110 contrast-105"
          />
          {/* Top-down and bottom-up white studio washes so dark text is 100% readable */}
          <div className="absolute inset-0 bg-white/35" />
          <div className="absolute inset-0 bg-gradient-to-b from-white/75 via-white/55 to-white" />
        </div>

        {/* 3. Foreground Content Container */}
        <div className="relative z-10 w-full h-full flex flex-col justify-between p-14">
          {/* Top Header Bar: Brand & Recruiting Board */}
          <div className="flex items-center justify-between pt-6">
            <div
              style={{
                borderColor: theme.accent,
                backgroundColor: "#FFFFFF",
                color: theme.accent,
              }}
              className="px-6 py-2.5 rounded-full border-2 text-xl font-extrabold tracking-widest uppercase shadow-md flex items-center gap-2.5"
            >
              <BookOpen className="w-6 h-6" />
              {theme.tag}
            </div>

            <div className="px-6 py-2.5 rounded-full border-2 border-slate-900 bg-yellow-300 text-slate-950 text-xl font-mono-code font-bold tracking-wider uppercase flex items-center gap-2 shadow-[4px_4px_0px_#0F172A]">
              <Sparkles className="w-5 h-5" />
              @SARKARIDROP
            </div>
          </div>

          {/* Center Main Study Sheet */}
          <div className="my-auto pt-6">
            {/* Agency Pill */}
            <div className="inline-flex items-center gap-2.5 px-5 py-2 rounded-xl bg-slate-900 text-white text-2xl font-mono-code font-bold uppercase tracking-wider shadow-sm">
              <Building2 className="w-6 h-6 text-yellow-300" />
              {jobData.agency}
            </div>

            {/* Bold Exam / Job Headline */}
            <h1
              className="mt-4 font-display font-bold uppercase leading-[1.04] tracking-tight text-slate-950 drop-shadow-[0_2px_10px_rgba(255,255,255,0.9)]"
              style={{ fontSize: jobData.raw_title.length > 52 ? "70px" : "82px" }}
            >
              {jobData.raw_title}
            </h1>

            {/* Highlighter Post Name Strip */}
            <div className="mt-5 flex items-center gap-3">
              <span className="px-5 py-2 rounded-xl bg-yellow-200 border-2 border-slate-900 text-slate-950 text-3xl font-extrabold uppercase tracking-wide shadow-[4px_4px_0px_#0F172A]">
                POST: {jobData.post_name}
              </span>
            </div>

            {/* Main White Study Note Card: Total Vacancies */}
            <div className="mt-9 p-8 rounded-3xl bg-white border-3 border-slate-900 shadow-[8px_8px_0px_#0F172A] flex items-center justify-between">
              <div>
                <div className="inline-block px-3 py-1 rounded-md bg-slate-100 text-slate-600 text-xl font-mono-code font-bold uppercase tracking-widest">
                  TOTAL VACANCIES ANNOUNCED
                </div>
                <div className="font-display text-8xl font-bold text-slate-950 mt-1 tracking-tight leading-none">
                  {jobData.vacancies}{" "}
                  <span className="text-4xl font-bold text-slate-500 uppercase">
                    SEATS
                  </span>
                </div>
              </div>

              <div
                style={{ backgroundColor: theme.accentSoft, borderColor: theme.accent }}
                className="w-24 h-24 rounded-2xl border-2 flex items-center justify-center shrink-0"
              >
                <Users className="w-12 h-12 stroke-[2.4]" style={{ color: theme.accent }} />
              </div>
            </div>

            {/* 2x2 Crisp White Student Spec Grid */}
            <div className="grid grid-cols-2 gap-6 mt-6">
              {/* Qualification */}
              <div className="p-7 rounded-3xl bg-white border-3 border-slate-900 shadow-[6px_6px_0px_#0F172A] flex flex-col justify-between">
                <div className="flex items-center gap-3">
                  <div
                    style={{ backgroundColor: theme.accentSoft }}
                    className="p-2.5 rounded-xl"
                  >
                    <GraduationCap
                      className="w-7 h-7"
                      style={{ color: theme.accent }}
                    />
                  </div>
                  <span className="text-slate-600 text-xl font-mono-code font-bold uppercase tracking-wider">
                    ELIGIBILITY
                  </span>
                </div>
                <div className="mt-3 text-3xl font-extrabold text-slate-950 leading-snug line-clamp-2">
                  {jobData.qualification}
                </div>
              </div>

              {/* Age Limit */}
              <div className="p-7 rounded-3xl bg-white border-3 border-slate-900 shadow-[6px_6px_0px_#0F172A] flex flex-col justify-between">
                <div className="flex items-center gap-3">
                  <div
                    style={{ backgroundColor: theme.accentSoft }}
                    className="p-2.5 rounded-xl"
                  >
                    <UserCheck className="w-7 h-7" style={{ color: theme.accent }} />
                  </div>
                  <span className="text-slate-600 text-xl font-mono-code font-bold uppercase tracking-wider">
                    AGE LIMIT
                  </span>
                </div>
                <div className="mt-3 text-4xl font-extrabold text-slate-950 leading-snug line-clamp-2">
                  {jobData.age_limit}
                </div>
              </div>

              {/* Form Mode */}
              <div className="p-7 rounded-3xl bg-white border-3 border-slate-900 shadow-[6px_6px_0px_#0F172A] flex flex-col justify-between">
                <div className="flex items-center gap-3">
                  <div
                    style={{ backgroundColor: theme.accentSoft }}
                    className="p-2.5 rounded-xl"
                  >
                    <Laptop className="w-7 h-7" style={{ color: theme.accent }} />
                  </div>
                  <span className="text-slate-600 text-xl font-mono-code font-bold uppercase tracking-wider">
                    APPLICATION MODE
                  </span>
                </div>
                <div className="mt-3 text-3xl font-extrabold text-slate-950 leading-snug">
                  {isOffline ? "Offline Form / Post" : "Online Application"}
                </div>
              </div>

              {/* Last Date */}
              <div className="p-7 rounded-3xl bg-white border-3 border-slate-900 shadow-[6px_6px_0px_#0F172A] flex flex-col justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-red-100">
                    <Calendar className="w-7 h-7 text-red-700" />
                  </div>
                  <span className="text-red-700 text-xl font-mono-code font-bold uppercase tracking-wider">
                    LAST DATE
                  </span>
                </div>
                <div className="mt-3 text-4xl font-extrabold text-red-600 leading-snug line-clamp-2">
                  {jobData.last_date}
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Official Apply Portal Bar */}
          <div className="pb-8">
            <div className="w-full p-7 rounded-3xl bg-white border-3 border-slate-900 shadow-[8px_8px_0px_#0F172A] flex items-center justify-between px-9">
          <div className="flex flex-col min-w-0 flex-1 pr-6">
  <span className="text-lg font-mono-code uppercase tracking-widest text-slate-500 font-bold">
    DIRECT OFFICIAL PORTAL (CHECK LINK IN CAPTION):
  </span>
  <FitLink text={domain} color={theme.accent} />
</div>
              <div
                style={{ backgroundColor: theme.accent }}
                className="w-16 h-16 rounded-2xl border-2 border-slate-900 flex items-center justify-center text-white shrink-0"
              >
                <ArrowUpRight className="w-10 h-10 stroke-[2.8]" />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-center gap-3 text-2xl text-slate-700 font-extrabold tracking-wider uppercase">
              <Bookmark className="w-6 h-6 text-slate-900 fill-yellow-300" />
              <span>Save for exam prep • Share with your study group</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}