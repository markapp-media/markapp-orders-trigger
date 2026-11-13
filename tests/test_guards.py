import calendar
import time

import guards


def t(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M"))


def run_at(s):
    return {"created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t(s)))}


def test_the_crawl_is_never_started_by_the_guard():   # on request only since 13 Nov 2026
    assert "adstxt.yml" not in guards.missed(lambda wf: [], t("2026-11-04 03:31"))


def test_weekly_jobs_only_on_their_day():
    none = lambda wf: []   # noqa: E731
    assert "ssp-db.yml" in guards.missed(none, t("2026-11-03 23:40"))              # Tuesday night
    assert "ssp-db.yml" not in guards.missed(none, t("2026-11-04 23:40"))          # Wednesday night
    assert "store-sweep.yml" in guards.missed(none, t("2026-11-08 10:00"))         # Sunday


def test_unanswered_tags(monkeypatch):
    now = t("2026-11-04 12:00")
    tag = f"<@{guards.BOT}>"
    hist = {"ok": True, "messages": [
        {"ts": str(now - 600), "user": "U1", "text": f"{tag} find a.com, 1"},                       # no answer
        {"ts": str(now - 900), "user": "U1", "text": f"{tag} find b.com, 2", "reply_count": 1,
         "latest_reply": str(now - 800)},                                                           # answered
        {"ts": str(now - 60), "user": "U1", "text": f"{tag} find c.com, 3"},                        # too fresh
    ]}
    replies = {"ok": True, "messages": [hist["messages"][1], {"ts": str(now - 800), "user": guards.BOT, "text": "ok"}]}
    monkeypatch.setattr(guards, "_slack", lambda m, s, **p: hist if m == "conversations.history" else replies)
    late = guards.unanswered("x", now)
    assert [round(a) for a, _, _ in late] == [600]


def test_order_words_and_alias_tags_count():
    assert guards.for_bot("<@U0C6ENRTSAK> find\na.com, 1, RESELLER")
    assert guards.for_bot("find\nmarkappmedia.site, C-1035, RESELLER")
    assert not guards.for_bot("den ton ekanes tag") and not guards.for_bot("<@U0927CST3V5> find it")
