"""ScrumAgent — production UI.  Run: streamlit run app.py"""

import html
import logging
import os
import re

import streamlit as st

from agent import AgentError, run_agent, run_sprint_report
from background import BackgroundRun, start_background_run
from config import ConfigError, make_settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

st.set_page_config(page_title="ScrumAgent", page_icon="🧭", layout="wide",
                   initial_sidebar_state="collapsed")

esc = html.escape

# ============================================================ styles (Unified Modern Dark)
st.markdown("""
<style>
:root {
  --bg:        #0B0D12;
  --card:      #14171F;
  --card-2:    #1A1E28;
  --stroke:    #242A36;
  --stroke-2:  #313846;
  --ink:       #E7EAF0;
  --ink-2:     #8A93A3;
  --accent:    #6E8BFF;
  --accent-2:  #8AA0FF;
  --accent-sf: rgba(110,139,255,0.14);
  --ease:      cubic-bezier(0.2, 0.75, 0.25, 1);
}

[data-testid="stAppViewContainer"], [data-testid="stHeader"],
.stButton button, input, textarea, select,
.stMarkdown, [data-testid="stMarkdownContainer"], [data-testid="stHeading"],
[data-testid="stMetricValue"], [data-testid="stMetricLabel"],
[data-testid="stCaptionContainer"], .stDataFrame, [data-baseweb="select"] {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text',
               'Inter', 'Segoe UI', Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
html { scroll-behavior: smooth; }

#MainMenu, footer, .stDeployButton, [data-testid="stToolbar"],
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stDecoration"], [data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent; height: 0; }

[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1000px 560px at 88% -12%, rgba(110,139,255,0.10), transparent 56%),
    radial-gradient(760px 520px at 2% 4%, rgba(138,160,255,0.06), transparent 52%),
    var(--bg) !important;
  background-attachment: fixed;
}

.block-container { max-width: none !important; padding: 1.5rem clamp(1.25rem, 3vw, 3.5rem) 3rem !important; }

/* ============================= Left Navigation Rail */
.sa-rail-brand { padding: 0.4rem 0.3rem 1.3rem; }
.sa-rail-brand .eyebrow { color: var(--accent); font-size: 0.7rem; font-weight: 750;
  letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 0.45rem; }
.sa-rail-brand .name { color: var(--ink); font-size: 1.45rem; font-weight: 750; letter-spacing: -0.04em; }
.sa-rail-brand .copy { color: var(--ink-2); font-size: 0.82rem; line-height: 1.45; margin-top: 0.35rem; }
.sa-rail-note { border-top: 1px solid var(--stroke); color: var(--ink-2); font-size: 0.78rem;
  line-height: 1.55; margin-top: 1.25rem; padding: 0.95rem 0.35rem 0; }

.block-container [role="radiogroup"] { align-items: stretch; display: flex; flex-direction: column;
  gap: 0.3rem; justify-content: flex-start; }
.block-container [role="radiogroup"] > label { box-sizing: border-box; border: 1px solid transparent;
  border-radius: 10px; color: var(--ink-2); font-size: 0.9rem; font-weight: 600; padding: 0.72rem 0.8rem; width: 100%; transition: all .2s var(--ease); cursor: pointer; }

/* FIX: Force inner wrappers (like Streamlit's <p> tags) to inherit the custom label color and weight */
.block-container [role="radiogroup"] > label p,
.block-container [role="radiogroup"] > label div { color: inherit !important; font-weight: inherit !important; }

.block-container [role="radiogroup"] > label:hover { background: rgba(255,255,255,0.05); color: var(--ink) !important; }
.block-container [role="radiogroup"] > label:has(input:checked) { background: var(--accent-sf) !important;
  border-color: rgba(110,139,255,0.4) !important; color: #B9C4FF !important; font-weight: 700 !important; }
.block-container [role="radiogroup"] > label > div:first-child { display: none; }
/* ============================= Header & Typography */
.sa-head { display: flex; justify-content: space-between; align-items: flex-end;
  border-bottom: 1px solid var(--stroke); margin: 0 0 1.5rem; padding: 0 0 1.15rem; gap: 1rem; }
.sa-title { color: var(--ink); font-size: 2rem; font-weight: 750; letter-spacing: -0.045em; line-height: 1.05; }
.sa-sub { color: var(--ink-2); font-size: 0.95rem; margin-top: 0.35rem; }

.sa-tokchip { background: var(--card); border: 1px solid var(--stroke); border-radius: 10px;
  padding: 0.55rem 1rem; display: flex; align-items: center; gap: 0.6rem; min-width: 120px; }
.sa-tokchip .ic { width: 32px; height: 32px; border-radius: 9px; background: var(--accent-sf);
  color: #B9C4FF; display: flex; align-items: center; justify-content: center; font-size: 0.95rem; }
.sa-tokchip .n { font-size: 1.2rem; font-weight: 750; color: var(--ink); line-height: 1; }
.sa-tokchip .l { font-size: 0.7rem; color: var(--ink-2); }

/* ============================= Cards & Components */
.sa-card, [data-testid="stExpander"], [data-testid="stForm"] { background: var(--card); border: 1px solid var(--stroke);
  border-radius: 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.35); padding: 1.15rem 1.2rem; margin-bottom: 1rem; position: relative; overflow: hidden; }
.sa-card-h { display: flex; align-items: center; gap: 0.55rem; margin-bottom: 0.85rem; }
.sa-card-h .ic { width: 32px; height: 32px; border-radius: 9px; display: flex;
  align-items: center; justify-content: center; font-size: 0.95rem; background: var(--accent-sf); color: #B9C4FF; }
.sa-card-h .t { font-weight: 700; font-size: 1.05rem; color: var(--ink); }

.sa-summary-text { color: #AEB6C4; font-size: 0.94rem; line-height: 1.6; padding-right: 0.4rem; }

.sa-qcard { border-color: rgba(110,139,255,0.45); box-shadow: 0 10px 34px rgba(110,139,255,0.12); }
.sa-q { color: var(--ink); font-weight: 600; font-size: 0.98rem; margin: 0.2rem 0 0.1rem; }
.sa-qctx { color: var(--ink-2); font-style: italic; font-size: 0.86rem; margin-bottom: 0.2rem; }

/* ============================= Tiles */
.sa-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.8rem; margin: 0.3rem 0 1.1rem; }
.sa-tile { background: var(--card); border: 1px solid var(--stroke); border-radius: 12px;
  padding: 0.9rem 1rem; display: flex; align-items: center; gap: 0.7rem; transition: transform 0.3s var(--ease), box-shadow 0.3s var(--ease); }
.sa-tile:hover { transform: translateY(-2px); box-shadow: 0 8px 22px rgba(0,0,0,0.4); border-color: var(--stroke-2); }
.sa-tile .ic { width: 38px; height: 38px; border-radius: 11px; flex-shrink: 0; display: flex;
  align-items: center; justify-content: center; font-size: 1.1rem; }
.sa-tile .v { font-size: 1.45rem; font-weight: 750; color: var(--ink); line-height: 1; }
.sa-tile .l { font-size: 0.78rem; color: var(--ink-2); margin-top: 0.12rem; }

.ic-purple { background: rgba(110,139,255,0.16); color: #A9B8FF; }
.ic-green { background: rgba(52,211,153,0.16); color: #4ADE80; }
.ic-orange { background: rgba(251,146,60,0.16); color: #FDBA74; }
.ic-pink { background: rgba(244,114,182,0.16); color: #F0A6D0; }
.ic-blue { background: rgba(96,165,250,0.16); color: #93C5FD; }

/* ============================= Tables & Pills */
.sa-tablewrap { overflow-x: auto; border: 1px solid var(--stroke); border-radius: 12px; }
.sa-table { width: 100%; min-width: 760px; border-collapse: collapse; font-size: 0.9rem; }
.sa-table th { text-align: left; background: var(--card-2); color: var(--ink-2); font-weight: 600; font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.05em; padding: 0.45rem 0.6rem; }
.sa-table td { padding: 0.7rem 0.6rem; border-top: 1px solid var(--stroke); color: var(--ink); }
.sa-table tr:hover td { background: rgba(255,255,255,0.03); }
.sa-table .key { font-weight: 600; color: var(--ink-2); }

.pri { padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.74rem; font-weight: 650; white-space: nowrap; }
.pri.high { background: rgba(244,63,94,0.18); color: #FB7185; }
.pri.medium { background: rgba(251,146,60,0.18); color: #FDBA74; }
.pri.low { background: rgba(96,165,250,0.18); color: #93C5FD; }

.sa-pill { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0.6rem;
  border-radius: 999px; font-size: 0.73rem; font-weight: 650; }
.sa-pill.ok { background: rgba(52,211,153,0.16); color: #4ADE80; }
.sa-pill.warn { background: rgba(251,146,60,0.16); color: #FDBA74; }
.sa-pill.err { background: rgba(244,63,94,0.16); color: #FB7185; }
.sa-pill.info { background: var(--accent-sf); color: #A9B8FF; }
.sa-pill.muted { background: var(--card-2); color: var(--ink-2); }

.sa-prog { background: var(--stroke); border-radius: 999px; height: 10px; overflow: hidden; margin: 0.2rem 0 1.3rem; }
.sa-prog > div { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }

/* ============================= Inputs & Buttons */
.stTextArea textarea, .stTextInput input {
  background: rgba(255,255,255,0.03) !important; border: 1px solid var(--stroke-2) !important;
  color: var(--ink) !important; border-radius: 9px !important; font-size: 0.93rem !important;
  transition: all .2s var(--ease) !important; }
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(110,139,255,0.18) !important; }
[data-baseweb="select"] > div { background: rgba(255,255,255,0.03) !important; border-color: var(--stroke-2) !important; }

.stButton > button, .stDownloadButton > button { border-radius: 9px; font-weight: 650; transition: all .22s var(--ease); }
.stButton > button[kind="primary"], .stFormSubmitButton > button {
  background: var(--accent); border: none; color: #0B0D12; padding: 0.48rem 1.35rem; }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover {
  background: var(--accent-2); transform: translateY(-1px); }
.stButton > button[kind="secondary"], .stDownloadButton > button { background: var(--card); border: 1px solid var(--stroke-2); color: var(--ink); }
.stButton > button[kind="secondary"]:hover, .stDownloadButton > button:hover { border-color: var(--accent); color: #B9C4FF; }

[data-testid="stStatusWidget"] { border-color: var(--stroke); border-radius: 12px; background: var(--card); }
.stAlert { border-radius: 10px; }
::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.14); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.24); }
</style>
""", unsafe_allow_html=True)

# ============================================================ state + config
ss = st.session_state
ss.setdefault("page", "meeting")
ss.setdefault("cfg_key", os.getenv("ANTHROPIC_API_KEY", ""))
ss.setdefault("cfg_model_label", "Claude Sonnet 4.6")
ss.setdefault("cfg_mock", os.getenv("MOCK_MODE", "true").strip().lower() != "false")
ss.setdefault("cfg_jira_url", os.getenv("JIRA_BASE_URL", ""))
ss.setdefault("cfg_jira_email", os.getenv("JIRA_EMAIL", ""))
ss.setdefault("cfg_jira_token", os.getenv("JIRA_API_TOKEN", ""))
ss.setdefault("cfg_jira_proj", os.getenv("JIRA_PROJECT_KEY", ""))

MODEL_CHOICES = {"Claude Sonnet 4.6": "claude-sonnet-4-6",
                 "Claude Sonnet 5": "claude-sonnet-5",
                 "Claude Haiku 4.5": "claude-haiku-4-5-20251001"}

def current_settings():
    try:
        s = make_settings(
            api_key=(ss.cfg_key or "").strip() or os.getenv("ANTHROPIC_API_KEY", ""),
            model=MODEL_CHOICES.get(ss.cfg_model_label, "claude-sonnet-4-6"),
            mock_mode=ss.cfg_mock,
            jira_base_url=ss.cfg_jira_url, jira_email=ss.cfg_jira_email,
            jira_api_token=(ss.cfg_jira_token or "").strip() or os.getenv("JIRA_API_TOKEN", ""),
            jira_project_key=ss.cfg_jira_proj)
        return s, ""
    except ConfigError as e:
        return None, str(e)

settings, config_err = current_settings()
config_ok = settings is not None

def last_tokens():
    r = ss.get("result")
    return (r.usage.input_tokens + r.usage.output_tokens) if r else 0

# ============================================================ workspace shell
side_rail, workspace = st.columns([1.15, 5.85], gap="large")
with side_rail:
    st.markdown("""<div class="sa-rail-brand">
      <div class="eyebrow">Scrum workspace</div>
      <div class="name">ScrumAgent</div>
      <div class="copy">Turn team conversations into clear, accountable work.</div>
      </div>""", unsafe_allow_html=True)
    labels = {"meeting": "Meeting notes", "sprint": "Sprint health",
              "reports": "Reports", "settings": "Settings"}
    page = st.radio("Workspace", options=list(labels),
                    format_func=lambda k: labels[k], key="page",
                    label_visibility="collapsed")
    mode = "Demo mode" if ss.cfg_mock else "Connected to Jira"
    st.markdown(f"<div class='sa-rail-note'><b>{mode}</b><br>"
                "Your latest meeting and sprint reports stay available here.</div>",
                unsafe_allow_html=True)

def page_header(title, sub, show_tokens=False):
    tok = ""
    if show_tokens:
        tok = (f"<div class='sa-tokchip'><div class='ic'>🗄️</div>"
               f"<div><div class='n'>{last_tokens():,}</div>"
               f"<div class='l'>Tokens used</div></div></div>")
    st.markdown(f"<div class='sa-head'><div><div class='sa-title'>{title}</div>"
                f"<div class='sa-sub'>{sub}</div></div>{tok}</div>",
                unsafe_allow_html=True)

def need_key_notice():
    st.markdown("<div class='sa-card' style='text-align:center;padding:2.4rem'>"
                "<div style='font-size:1.9rem'>🔑</div>"
                "<div class='sa-card-h' style='justify-content:center'>"
                "<div class='t'>Connect your Claude API key</div></div>"
                "<p style='color:var(--ink-2)'>Open <b>Settings</b> to add your "
                "Anthropic API key (and Jira, if you want real tickets).</p></div>",
                unsafe_allow_html=True)

# ============================================================ shared
def build_export_md(result):
    ctx = result.ctx
    out = ["# ScrumAgent — Meeting Report\n", f"{result.summary}\n", "## Tickets\n"]
    for t in ctx.tickets:
        v = {True: "verified", False: "UNVERIFIED", None: "-"}[t.verified]
        out.append(f"- **{t.key}** {t.title} — owner: {t.owner}, due: "
                   f"{t.due or '—'}, priority: {t.priority} [{v}]")
    if ctx.email_draft:
        out.append(f"\n## Follow-up email\n**Subject:** "
                   f"{ctx.email_draft['subject']}\n\n{ctx.email_draft['body']}")
    return "\n".join(out)

def compact_summary(summary, limit=700):
    summary = re.sub(r"\s+", " ", summary or "").strip()
    if len(summary) > limit:
        summary = summary[:limit].rsplit(" ", 1)[0] + "…"
    return summary or "No summary returned."

def render_run_progress(run: BackgroundRun):
    with st.status(f"{run.label} is still working…", expanded=False):
        for event in run.events():
            if event["type"] == "text":
                st.markdown(f"🧠 {esc(event['text'])}")
            elif event["type"] == "tool_call":
                title = event["input"].get("title") or event["input"].get("question", "")
                st.markdown(f"🔧 **{esc(event['name'])}**{(' — ' + esc(title)) if title else ''}")
            elif event["type"] == "tool_error":
                st.markdown(f"❌ `{esc(event['error'])}`")
    st.caption("You can switch tabs or leave this page. The run continues in the background "
               "and this view updates automatically when it finishes.")

def render_live_run_progress(run: BackgroundRun):
    fragment = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
    if fragment is None:
        render_run_progress(run)
        return

    @fragment(run_every=1.5)
    def poll():
        render_run_progress(run)
        if run.done:
            st.rerun()

    poll()

def collect_background_run(key, result_key):
    run = ss.get(key)
    if not run:
        return False
    if not run.done:
        return True
    ss.pop(key, None)
    try:
        ss[result_key] = run.future.result()
        return False
    except AgentError as e:
        st.error(str(e))
    except Exception:
        logging.exception("Background run failed")
        st.error("Unexpected error — check the logs. Any tickets created before "
                 "the failure are already in your tracker.")
    return False

# ================================================================ meeting
def render_meeting():
    page_header("Meeting Agent",
                "Paste your meeting transcript and run the agent", show_tokens=True)
    if not config_ok:
        need_key_notice()
        return

    if "transcript_text" not in ss:
        sp = os.path.join(os.path.dirname(__file__), "sample_transcript.txt")
        ss["transcript_text"] = open(sp, encoding="utf-8").read() if os.path.exists(sp) else ""

    meeting_running = collect_background_run("meeting_run", "result")

    editor_col, guide_col = st.columns([2.1, 0.9], gap="large")
    with editor_col:
        st.markdown("<div class='sa-card-h'><div class='ic'>01</div>"
                    "<div class='t'>Meeting notes</div></div>", unsafe_allow_html=True)
        ss["transcript_text"] = st.text_area(
            "Meeting transcript", value=ss["transcript_text"], height=280,
            label_visibility="collapsed",
            placeholder="Paste a transcript, decisions, and action items…")
        transcript = ss["transcript_text"]
        c1, c2, _ = st.columns([1.25, 1.55, 4])
        run = c1.button("Create action plan", type="primary",
                        disabled=not transcript.strip() or meeting_running)
        if "result" in ss:
            c2.download_button("Download report", build_export_md(ss["result"]),
                               file_name="scrumagent_report.md", mime="text/markdown")
    with guide_col:
        st.markdown("""<div class='sa-card'>
          <div class='sa-card-h'><div class='ic'>✓</div><div class='t'>What happens next</div></div>
          <p style='color:var(--ink-2);line-height:1.65;margin:0'>
          We identify action items, assign clear ownership, verify the results against
          your notes, and prepare a concise follow-up.</p>
          </div>""", unsafe_allow_html=True)
        st.markdown("""<div class='sa-card'>
          <div style='font-size:.78rem;font-weight:700;color:var(--ink-2);text-transform:uppercase;letter-spacing:.08em'>Tip</div>
          <div style='color:var(--ink);font-size:.9rem;line-height:1.55;margin-top:.45rem'>
          Include names and deadlines for the most accurate tickets.</div></div>""",
                    unsafe_allow_html=True)
    if run:
        ss["meeting_run"] = start_background_run(
            "Meeting agent", run_agent, transcript, settings)
        st.rerun()

    if meeting_running:
        render_live_run_progress(ss["meeting_run"])

    if "result" not in ss:
        return
    result = ss["result"]
    ctx = result.ctx
    verified = sum(1 for t in ctx.tickets if t.verified)
    flagged = sum(1 for t in ctx.tickets if t.verified is False)

    if ctx.questions:
        st.markdown(
            f"<div class='sa-card sa-qcard'><div class='sa-card-h'><div class='ic'>❓</div>"
            f"<div class='t'>The agent needs {len(ctx.questions)} answer"
            f"{'s' if len(ctx.questions) != 1 else ''}</div></div>"
            f"<p style='color:var(--ink-2);margin-bottom:0.4rem'>Answer below and re-run "
            f"— your answers are treated as authoritative.</p></div>",
            unsafe_allow_html=True)
        with st.form("qa_form"):
            answers = []
            for i, q in enumerate(ctx.questions):
                ctx_line = (f"<div class='sa-qctx'>“{esc(q['context'])}”</div>"
                            if q.get("context") else "")
                tk = f" · {esc(q['ticket_key'])}" if q.get("ticket_key") else ""
                st.markdown(f"<div class='sa-q'>{esc(q['question'])}{tk}</div>{ctx_line}",
                            unsafe_allow_html=True)
                answers.append((q["question"],
                                st.text_input("Answer", key=f"qa_{i}",
                                              label_visibility="collapsed",
                                              placeholder="Your answer…")))
            submitted = st.form_submit_button("Submit answers & re-run", type="primary",
                                               disabled=meeting_running)
        if submitted and not meeting_running:
            clar = [{"question": qq, "answer": aa} for qq, aa in answers if aa.strip()]
            if clar:
                ss.pop("result", None)
                ss["meeting_run"] = start_background_run(
                    "Meeting agent", run_agent, transcript, settings,
                    clarifications=clar)
                st.rerun()
            else:
                st.warning("Type at least one answer before re-running.")

    st.markdown(
        "<div class='sa-tiles'>"
        f"<div class='sa-tile'><div class='ic ic-purple'>🎫</div><div><div class='v'>{len(ctx.tickets)}</div><div class='l'>Tickets</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-green'>✅</div><div><div class='v'>{verified}</div><div class='l'>Verified</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-orange'>🚩</div><div><div class='v'>{flagged}</div><div class='l'>Flagged</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-pink'>❓</div><div><div class='v'>{len(ctx.questions)}</div><div class='l'>Questions</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-blue'>🗄️</div><div><div class='v'>{last_tokens():,}</div><div class='l'>Tokens</div></div></div>"
        "</div>", unsafe_allow_html=True)

    for f in ctx.ticket_failures:
        st.warning(f"Ticket failed: {f}")
    if flagged:
        st.warning(f"{flagged} ticket(s) flagged as unverified — see the ⚠ notes below.")

    st.markdown(
        "<div class='sa-card'><div class='sa-card-h'><div class='ic'>📝</div>"
        "<div class='t'>Meeting overview</div></div>"
        f"<div class='sa-summary-text'>{esc(compact_summary(result.summary))}</div></div>",
        unsafe_allow_html=True)

    col_s, col_e = st.columns([1.45, 1], gap="large")
    with col_s:
        rows = ""
        for t in ctx.tickets:
            pc = t.priority.lower() if t.priority.lower() in ("high", "medium", "low") else "low"
            badge = " ⚠" if t.verified is False else ""
            rows += (f"<tr><td class='key'>{esc(t.key)}{badge}</td>"
                     f"<td class='title'>{esc(t.title)}</td><td class='owner'>{esc(t.owner)}</td>"
                     f"<td class='due'>{esc(t.due or '—')}</td>"
                     f"<td><span class='pri {pc}'>{esc(t.priority)}</span></td></tr>")
        st.markdown(
            f"<div class='sa-card'><div class='sa-card-h'><div class='ic'>📋</div>"
            f"<div class='t'>Action items · {len(ctx.tickets)} tickets</div></div>"
            f"<div class='sa-tablewrap'><table class='sa-table'><thead><tr><th>Key</th>"
            f"<th>Title</th><th>Owner</th><th>Due</th><th>Priority</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></div>", unsafe_allow_html=True)
    with col_e:
        if ctx.email_draft:
            st.markdown("<div class='sa-card-h'><div class='ic'>✉️</div>"
                        "<div class='t'>Follow-up email</div></div>", unsafe_allow_html=True)
            st.text_input("Subject", value=ctx.email_draft["subject"])
            st.text_area("Body", value=ctx.email_draft["body"], height=300)
        else:
            st.markdown("<div class='sa-card'><div class='sa-card-h'><div class='ic'>✉️</div>"
                        "<div class='t'>Follow-up email</div></div>"
                        "<p style='color:var(--ink-2)'>No email drafted for this run.</p></div>",
                        unsafe_allow_html=True)

# ================================================================ sprint
def render_sprint():
    page_header("Sprint Status",
                "Live health report on the current sprint — progress, risks &amp; actions")
    if not config_ok:
        need_key_notice()
        return
    sprint_running = collect_background_run("sprint_run", "sprint")
    action_col, source_col = st.columns([1.6, 1], gap="large")
    with action_col:
        st.markdown("<div class='sa-card-h'><div class='ic'>01</div>"
                    "<div class='t'>Refresh sprint health</div></div>", unsafe_allow_html=True)
        st.caption("Pull the current sprint, calculate delivery risk, and create a practical status report.")
        if st.button("Refresh sprint report", type="primary", disabled=sprint_running):
            ss["sprint_run"] = start_background_run(
                "Sprint report", run_sprint_report, settings)
            st.rerun()
    with source_col:
        source = "Demo sprint" if settings.mock_mode else f"Jira · {settings.jira_project_key}"
        detail = ("Using safe sample data. Connect Jira in Settings when you're ready."
                  if settings.mock_mode else "Using the active sprint from your connected Jira board.")
        st.markdown(f"<div class='sa-card'><div style='font-size:.78rem;font-weight:700;"
                    f"color:var(--ink-2);text-transform:uppercase;letter-spacing:.08em'>Data source</div>"
                    f"<div style='font-weight:700;color:var(--ink);margin:.4rem 0'>{esc(source)}</div>"
                    f"<div style='font-size:.86rem;line-height:1.5;color:var(--ink-2)'>{esc(detail)}</div></div>",
                    unsafe_allow_html=True)
    if sprint_running:
        render_live_run_progress(ss["sprint_run"])
    if "sprint" not in ss:
        return
    sprint = ss["sprint"]
    for w in sprint.warnings:
        st.warning(w)
    if not sprint.issues:
        return
    s = sprint.stats
    st.markdown(
        "<div class='sa-tiles'>"
        f"<div class='sa-tile'><div class='ic ic-purple'>📦</div><div><div class='v'>{s['total']}</div><div class='l'>Total</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-green'>✅</div><div><div class='v'>{s['done']}</div><div class='l'>Done</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-blue'>⚙️</div><div><div class='v'>{s['in_progress']}</div><div class='l'>In progress</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-orange'>📋</div><div><div class='v'>{s['todo']}</div><div class='l'>To do</div></div></div>"
        f"<div class='sa-tile'><div class='ic ic-purple'>📈</div><div><div class='v'>{s['completion_pct']}%</div><div class='l'>Complete</div></div></div>"
        "</div>"
        f"<div class='sa-prog'><div style='width:{s['completion_pct']}%'></div></div>",
        unsafe_allow_html=True)
    chips = ""
    if s["overdue"]:
        chips += f"<span class='sa-pill err'>Overdue: {esc(', '.join(s['overdue']))}</span>&nbsp;&nbsp;"
    if s["stale"]:
        chips += f"<span class='sa-pill warn'>Stale &gt;3d: {esc(', '.join(s['stale']))}</span>"
    if chips:
        st.markdown(f"<div style='margin-bottom:1rem'>{chips}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='sa-card'>{sprint.report_md}</div>", unsafe_allow_html=True)
    with st.expander(f"Sprint issues ({len(sprint.issues)})"):
        st.dataframe(
            [{"Key": i["key"], "Summary": i["summary"], "Status": i["status"],
              "Assignee": i["assignee"], "Priority": i["priority"],
              "Due": i["due"] or "—", "Updated": i["updated"] or "—"}
             for i in sprint.issues], use_container_width=True, hide_index=True)

# ================================================================ reports
def render_reports():
    page_header("Reports", "Download the artifacts from your latest runs")
    got = False
    meeting_running = collect_background_run("meeting_run", "result")
    sprint_running = collect_background_run("sprint_run", "sprint")
    if meeting_running:
        got = True
        st.markdown("<div class='sa-card'><div class='sa-card-h'><div class='ic'>⏳</div>"
                    "<div class='t'>Meeting report is being prepared</div></div>"
                    "<p style='color:var(--ink-2)'>You can keep navigating; the completed "
                    "report will replace this status as soon as it is ready.</p></div>",
                    unsafe_allow_html=True)
        render_live_run_progress(ss["meeting_run"])
    if sprint_running:
        got = True
        st.markdown("<div class='sa-card'><div class='sa-card-h'><div class='ic'>⏳</div>"
                    "<div class='t'>Sprint report is being prepared</div></div>"
                    "<p style='color:var(--ink-2)'>The sprint analysis is still running in "
                    "the background. Your latest completed report remains available below.</p></div>",
                    unsafe_allow_html=True)
        render_live_run_progress(ss["sprint_run"])
    if "result" in ss:
        got = True
        st.markdown("<div class='sa-card'><div class='sa-card-h'><div class='ic'>📋</div>"
                    "<div class='t'>Meeting report</div></div>"
                    "<p style='color:var(--ink-2)'>Tickets, verification results, and the "
                    "follow-up email from your last meeting run.</p></div>", unsafe_allow_html=True)
        st.download_button("⬇  Download meeting report (.md)", build_export_md(ss["result"]),
                           file_name="scrumagent_meeting_report.md", mime="text/markdown")
    if "sprint" in ss and ss["sprint"].issues:
        got = True
        sp = ss["sprint"]
        st.markdown("<div class='sa-card'><div class='sa-card-h'><div class='ic'>📊</div>"
                    "<div class='t'>Sprint report</div></div>"
                    "<p style='color:var(--ink-2)'>Health report and statistics from your "
                    "last sprint status run.</p></div>", unsafe_allow_html=True)
        body = (f"# Sprint report\n\nCompletion: {sp.stats['completion_pct']}% "
                f"({sp.stats['done']}/{sp.stats['total']})\n\n{sp.report_md}")
        st.download_button("⬇  Download sprint report (.md)", body,
                           file_name="scrumagent_sprint_report.md", mime="text/markdown")
    if not got:
        st.markdown("<div class='sa-card' style='text-align:center;padding:2.4rem'>"
                    "<div style='font-size:1.9rem'>📄</div><div class='sa-card-h' "
                    "style='justify-content:center'><div class='t'>No reports yet</div></div>"
                    "<p style='color:var(--ink-2)'>Run the Meeting Agent or a Sprint report "
                    "to create downloadable artifacts.</p></div>", unsafe_allow_html=True)

# ================================================================ settings
def _mask_key(k):
    return (k[:7] + "…" + k[-4:]) if len(k) > 12 else "set"

def render_settings():
    page_header("Settings", "Connect your keys and choose how tickets are created")

    st.markdown("<div class='sa-card-h'><div class='ic'>🔑</div>"
                "<div class='t'>Claude API</div></div>", unsafe_allow_html=True)
    typed = st.text_input("Anthropic API key", value="", type="password",
                          placeholder=(f"Saved: {_mask_key(ss.cfg_key)} — paste to replace"
                                       if ss.cfg_key else "sk-ant-…"),
                          help="Get one at console.anthropic.com/settings/keys")
    if typed.strip():
        ss.cfg_key = typed.strip()
    if ss.cfg_key:
        st.caption(f"✓ Claude key saved · {_mask_key(ss.cfg_key)}")

    opts = list(MODEL_CHOICES)
    ss.cfg_model_label = st.selectbox(
        "Model", opts,
        index=opts.index(ss.cfg_model_label) if ss.cfg_model_label in opts else 0)

    st.markdown("<div class='sa-card-h' style='margin-top:1rem'><div class='ic'>🎫</div>"
                "<div class='t'>Ticket mode</div></div>", unsafe_allow_html=True)
    ss.cfg_mock = st.toggle("Mock mode — create fake tickets, no Jira needed",
                            value=ss.cfg_mock)
    if not ss.cfg_mock:
        st.caption("Real Jira mode — enter your Jira connection details:")
        ss.cfg_jira_url = st.text_input("Jira base URL", value=ss.cfg_jira_url,
                                        placeholder="https://yourteam.atlassian.net")
        ss.cfg_jira_email = st.text_input("Jira email", value=ss.cfg_jira_email,
                                          placeholder="you@example.com")
        jt = st.text_input("Jira API token", value="", type="password",
                           placeholder=(f"Saved: {_mask_key(ss.cfg_jira_token)} — paste to replace"
                                        if ss.cfg_jira_token else "your-jira-api-token"),
                           help="id.atlassian.com/manage-profile/security/api-tokens")
        if jt.strip():
            ss.cfg_jira_token = jt.strip()
        ss.cfg_jira_proj = st.text_input("Jira project key", value=ss.cfg_jira_proj,
                                         placeholder="SCRUM")

    st.write("")
    s2, err2 = current_settings()
    if s2:
        badge = ("<span class='sa-pill info'>MOCK MODE</span>" if s2.mock_mode
                 else f"<span class='sa-pill ok'>REAL JIRA · {esc(s2.jira_project_key)}</span>")
        st.markdown(f"<div class='sa-card'>✅ <b>Connected.</b> &nbsp;{badge}&nbsp; "
                    f"<span class='sa-pill muted'>{esc(s2.model)}</span></div>",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='sa-card' style='border-color:rgba(244,63,94,0.4)'>"
                    f"⚠️ {esc(err2)}</div>", unsafe_allow_html=True)

PAGES = {"meeting": render_meeting, "sprint": render_sprint,
         "reports": render_reports, "settings": render_settings}
with workspace:
    PAGES[page]()