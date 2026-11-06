"""Early warnings for markapp-media/ads-txt-monitor, run by the watcher every GUARD_EVERY (Sotiris 4 Nov 2026: "fix
this and similar issues in advance"). Stateless: each check looks at a time window, so a restart repeats nothing.

1. Unanswered tags: a tag of the adstxt-crawler bot in #adstxt-crawler with no bot answer in its thread after
   WAKE_AFTER wakes the bot again; after DM_AFTER the owner gets one DM with the link.
2. Missed schedules: GitHub starts scheduled workflows hours late or not at all. A job that has not started by
   its deadline is started here (the daily crawl, the Wednesday sellers.json read, the weekend CTV / store jobs).
3. Failed runs: any ads-txt-monitor run that failed reaches the owner as one DM with the run links.

Public repo: logs say only "ok" or an error type; Slack text goes to the owner's DM only.
"""
import calendar
import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request

REPO = "markapp-media/ads-txt-monitor"
CHANNEL, BOT = "C0C6PSH3WVB", "U0C6ZR34WJ0"
OWNER = "U0927E76VLP"
GUARD_EVERY = 5 * 60
WAKE_AFTER, DM_AFTER, GIVE_UP = 5 * 60, 15 * 60, 6 * 3600
# workflow file, weekday (0 = Monday, None = daily), deadline UTC "HH:MM": started here when no run began in the
# CATCH hours before the deadline and the deadline passed less than LATE hours ago.
SCHEDULES = [
    ("adstxt.yml", 2, "03:30"),         # Wednesday crawl, cron 02:00 / 03:00 UTC (05:00 Athens); weekly since 4 Nov
    ("ssp-db.yml", 1, "23:30"),          # Tuesday 22:30 UTC = Wednesday 00:30 Athens, before the Wednesday post
    ("ctv-stores.yml", 5, "08:45"),      # Saturday 08:00 UTC
    ("store-sweep.yml", 6, "09:45"),     # Sunday 09:00 UTC
]
CATCH, LATE = 3, 6


def _req(url, auth, data=None, method=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, method=method,
                                 headers={"Authorization": f"Bearer {auth}", "Accept": "application/json",
                                          "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return json.loads(body) if body else {}


def _slack(method, slack, **params):
    return _req(f"https://slack.com/api/{method}?" + urllib.parse.urlencode(params), slack)


def _ts(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def dm(slack, text):
    return _req("https://slack.com/api/chat.postMessage", slack, {"channel": OWNER, "text": text}, "POST")


def dispatch(gh, workflow):
    _req(f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches", gh, {"ref": "main"}, "POST")


# ------------------------------------------------------------------ 1. unanswered tags
ALIASES = ("U0C6ENRTSAK",)   # look-alike 'adstxtcrawler' app people tag by mistake
ORDER_WORD = re.compile(r"(?i)^\W*(find|scan|crawl|fill|lookup)\b")


def for_bot(text):
    text = text or ""
    if any(f"<@{u}" in text for u in (BOT, *ALIASES)):
        return True
    return "<@" not in text and bool(ORDER_WORD.match(text))

def unanswered(slack, now=None):
    """[(age seconds, message ts, thread ts)] tags of the bot with no bot message after them in their thread."""
    now = now or time.time()
    hist = _slack("conversations.history", slack, channel=CHANNEL, oldest=f"{now - 2 * 86400:.0f}", limit=200)
    if not hist.get("ok"):
        return []
    threads = {}
    for m in hist.get("messages", []):
        if m.get("reply_count") and now - float(m.get("latest_reply", 0)) < GIVE_UP + 86400:
            r = _slack("conversations.replies", slack, channel=CHANNEL, ts=m["ts"], limit=200)
            threads[m["ts"]] = r.get("messages", []) if r.get("ok") else [m]
        else:
            threads[m["ts"]] = [m]
    out = []
    for parent, msgs in threads.items():
        for m in msgs:
            age = now - float(m["ts"])
            if m.get("bot_id") or not for_bot(m.get("text")) or not WAKE_AFTER <= age < GIVE_UP:
                continue
            if not any(x.get("user") == BOT and float(x["ts"]) > float(m["ts"]) for x in msgs):
                out.append((age, m["ts"], parent))
    return out


def guard_tags(slack, gh, wake):
    late = unanswered(slack)
    if any(age < DM_AFTER for age, _, _ in late):
        wake()
    for age, ts, parent in late:
        if DM_AFTER <= age < DM_AFTER + GUARD_EVERY:   # one DM per request: the round whose window holds 15 min
            link = _slack("chat.getPermalink", slack, channel=CHANNEL, message_ts=ts).get("permalink", "")
            dm(slack, f":warning: *#adstxt-crawler*: a request to the bot is unanswered after 15 min "
                      f"(woken twice). {link}\nCheck the ads-txt-monitor Actions runs: https://github.com/{REPO}/actions")
    return len(late)


# ------------------------------------------------------------------ 2. missed schedules
def missed(runs_for, now=None):
    """[workflow] whose deadline passed (less than LATE hours ago) with no run started in the CATCH hours before."""
    now = now or time.time()
    out = []
    for wf, wday, hhmm in SCHEDULES:
        d = dt.datetime.fromtimestamp(now, dt.timezone.utc)
        h, m = map(int, hhmm.split(":"))
        deadline = d.replace(hour=h, minute=m, second=0, microsecond=0)
        if deadline.timestamp() > now:
            deadline -= dt.timedelta(days=1)
        if wday is not None and deadline.weekday() != wday:
            continue
        if not 0 <= now - deadline.timestamp() < LATE * 3600:
            continue
        since = deadline.timestamp() - CATCH * 3600
        if not any(_ts(r["created_at"]) >= since for r in runs_for(wf)):
            out.append(wf)
    return out


def guard_schedules(gh):
    def runs_for(wf):
        return _req(f"https://api.github.com/repos/{REPO}/actions/workflows/{wf}/runs?per_page=5", gh).get(
            "workflow_runs", [])
    started = missed(runs_for)
    for wf in started:
        dispatch(gh, wf)
    return len(started)


# ------------------------------------------------------------------ 3. failed runs
def failures(gh, cut):
    runs = _req(f"https://api.github.com/repos/{REPO}/actions/runs?status=failure&per_page=20", gh).get(
        "workflow_runs", [])
    return [r for r in runs if _ts(r["updated_at"]) > cut]


def guard_failures(slack, gh, cut):
    bad = failures(gh, cut)
    if bad:
        dm(slack, ":x: *ads-txt-monitor*: " + ("a job failed" if len(bad) == 1 else f"{len(bad)} jobs failed") + "\n"
           + "\n".join(f"• <{r['html_url']}|{r['name']} #{r['run_number']}> ({r['event']})" for r in bad[:6]))
    return len(bad)


def run(slack, gh, wake, cut):
    """All three guards; one failing never stops the others. Returns nothing (public log: 'ok' / error types)."""
    for name, fn in (("tags", lambda: guard_tags(slack, gh, wake)), ("schedules", lambda: guard_schedules(gh)),
                     ("failures", lambda: guard_failures(slack, gh, cut))):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"guard {name} failed ({type(e).__name__})")
