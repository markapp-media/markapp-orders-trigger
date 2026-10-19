"""Watch Slack for new activity and wake the private order bot. Logs counts only, never message content.

GitHub runs scheduled workflows late (often every 25-35 min), so each run keeps watching for
WATCH_MINUTES and the next queued run takes over when it ends: continuous coverage, ~1 min latency.
"""
import calendar
import re
import json
import os
import time
import urllib.parse
import urllib.request

CHANNELS = ["C0C9KKMG53M", "C092GNL0E6A", "C0C6ECNBTQU", "C0C6EKFJ7UL", "C0C6PSH3WVB", "C0C9FU3TPCY",
            "C0C7P1Z52A3"]   # last = owner-only channel (bot must be invited)
TARGET = "markapp-media/markapp-remote-orders"
LOOKBACK_DAYS = 14
DEFAULT_WINDOW = 15 * 60
CHECK_EVERY = 45
WATCH_MINUTES = float(os.environ.get("WATCH_MINUTES", "50"))
# Named agents with their own Slack bot (secret name). Their channels are the ones that bot is in.
AGENT_TOKENS = ["HARION_DSP_OPS_BOT_TOKEN"]


def token(name):
    return os.environ[name].strip().lstrip(chr(0xFEFF))


def get(url, auth):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def since_last_run():
    """Start of the previous successful run, minus a minute of overlap."""
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://api.github.com/repos/{repo}/actions/workflows/trigger.yml/runs?status=success&per_page=1"
    try:
        runs = get(url, token("GITHUB_TOKEN")).get("workflow_runs", [])
        if runs:
            return calendar.timegm(time.strptime(runs[0]["run_started_at"], "%Y-%m-%dT%H:%M:%SZ")) - 60
    except Exception as e:
        print(f"previous run lookup failed ({type(e).__name__}); using default window")
    return time.time() - DEFAULT_WINDOW


def agent_channels(slack):
    """Channels a named agent's bot is a member of (empty list until its channel is set up; None on error)."""
    body = get("https://slack.com/api/users.conversations?" + urllib.parse.urlencode(
        {"types": "public_channel,private_channel", "limit": 200, "exclude_archived": "true"}), slack)
    if not body.get("ok"):
        print(f"agent bot: slack error {body.get('error')}")
        return None
    return [c["id"] for c in body.get("channels", [])]


def agent_hits(cut, setup_asked):
    """Activity in named agents' channels; a token without a channel asks for setup once per run."""
    hits = 0
    for env in AGENT_TOKENS:
        if not os.environ.get(env, "").strip():
            continue
        agent = token(env)
        chans = agent_channels(agent)
        if chans == []:
            if env not in setup_asked:
                setup_asked.add(env)
                hits += 1
            continue
        hits += sum(1 for c in (chans or []) if active(c, cut, agent))
    return hits


# Only activity the order bot acts on wakes it (private repo = billed minutes): a tag of the bot whose token reads
# the channel, a `repo:`/`dsp:` line, a post forwarded by the weekly-agenda relay bot ("Requested by"), a reply in
# an order thread, anything in the orders channel itself (untagged posts get a ❓ there), and posts that could carry
# owner-only figures or files (the bot's leak check must still see them quickly).
ORDERS_CHANNEL = "C0C9KKMG53M"
RELAY_BOT = "U0CA095JWQ5"                            # MarkApp Briefs (weekly agenda relay)
ORDER_TEXT = re.compile(r"^\W*(?:harion\s+)?(repo|dsp)\s*:|Requested by <@U", re.I | re.M)
LEAK_HINT = re.compile(r"salar|payroll|ebitda|\bgp\b|gross profit|p\s*&\s*l|\bprofit|\bcash\b|[$€£]\s?\d|\d\s?%", re.I)
ORDER_THREAD = ("Order `ORD-", "Which area is this for")
BOT_IDS = {}                                          # token -> that bot's own user id


def bot_id(slack):
    if slack not in BOT_IDS:
        BOT_IDS[slack] = get("https://slack.com/api/auth.test", slack).get("user_id") or "?"
    return BOT_IDS[slack]


def order_like(text, me):
    text = text or ""
    return f"<@{me}" in text or bool(ORDER_TEXT.search(text))


def wakes(m, me, channel):
    if m.get("user") == RELAY_BOT:
        return order_like(m.get("text"), me)
    if m.get("bot_id") or m.get("subtype") not in (None, "file_share", "thread_broadcast"):
        return False
    return (channel == ORDERS_CHANNEL or order_like(m.get("text"), me) or bool(m.get("files"))
            or bool(LEAK_HINT.search(m.get("text") or "")))


def thread_wakes(channel, ts, cut, slack, me):
    """A new reply counts when the thread is an order (the bot asked or acked in it) or the reply itself would."""
    q = urllib.parse.urlencode({"channel": channel, "ts": ts, "limit": 200})
    body = get(f"https://slack.com/api/conversations.replies?{q}", slack)
    msgs = body.get("messages", []) if body.get("ok") else []
    fresh = [m for m in msgs[1:] if float(m["ts"]) > cut]
    if any(k in (m.get("text") or "") for m in msgs for k in ORDER_THREAD):
        return any(not m.get("bot_id") or m.get("user") == RELAY_BOT for m in fresh)
    return any(wakes(m, me, None) for m in fresh)


def active(channel, cut, slack):
    q = urllib.parse.urlencode({"channel": channel, "oldest": f"{time.time() - LOOKBACK_DAYS * 86400:.0f}", "limit": 200})
    body = get(f"https://slack.com/api/conversations.history?{q}", slack)
    if not body.get("ok"):
        print(f"{channel}: slack error {body.get('error')}")
        return False
    me = bot_id(slack)
    for m in body.get("messages", []):
        if float(m["ts"]) > cut and wakes(m, me, channel):
            return True
        if float(m.get("latest_reply", 0)) > cut and thread_wakes(channel, m["ts"], cut, slack, me):
            return True
    return False


def wake():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{TARGET}/dispatches",
        data=json.dumps({"event_type": "slack"}).encode(),
        headers={"Authorization": f"Bearer {token('DISPATCH_TOKEN')}", "Accept": "application/vnd.github+json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def main():
    slack = token("SLACK_BOT_TOKEN")
    cut = since_last_run()
    stop = time.time() + WATCH_MINUTES * 60
    checks = wakes = 0
    setup_asked = set()
    while True:
        started = time.time()
        try:
            hits = sum(1 for c in CHANNELS if active(c, cut, slack)) + agent_hits(cut, setup_asked)
            if hits:
                wake()
                wakes += 1
            cut = started - 10
        except Exception as e:
            print(f"check failed ({type(e).__name__}); retrying next round")
        checks += 1
        if time.time() + CHECK_EVERY >= stop:
            break
        time.sleep(CHECK_EVERY)
    print(f"{checks} checks, woke the order bot {wakes} times")


if __name__ == "__main__":
    main()
