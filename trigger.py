"""Watch Slack for new activity and wake the private order bot. Logs counts only, never message content.

GitHub runs scheduled workflows late (often every 25-35 min), so each run keeps watching for
WATCH_MINUTES and the next queued run takes over when it ends: continuous coverage, ~1 min latency.
"""
import calendar
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


def active(channel, cut, slack):
    q = urllib.parse.urlencode({"channel": channel, "oldest": f"{time.time() - LOOKBACK_DAYS * 86400:.0f}", "limit": 200})
    body = get(f"https://slack.com/api/conversations.history?{q}", slack)
    if not body.get("ok"):
        print(f"{channel}: slack error {body.get('error')}")
        return False
    for m in body.get("messages", []):
        human_post = float(m["ts"]) > cut and not m.get("bot_id") and not m.get("subtype")
        new_reply = float(m.get("latest_reply", 0)) > cut
        if human_post or new_reply:
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
