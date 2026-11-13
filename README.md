# markapp-orders-trigger

A run starts every 20 minutes and watches for about 50 minutes, checking every 45 seconds MarkApp's order channels in Slack for new activity and wakes the private order bot. It contains no business logic or data, and its logs say only "ok" or an error type (no message content, channel ids or counts). All order work happens in the private bot repo.

Public on purpose: GitHub Actions minutes are free for public repos. Secrets (`SLACK_BOT_TOKEN`, `HARION_DSP_OPS_BOT_TOKEN`, `DISPATCH_TOKEN`) are encrypted repository secrets. The workflow runs only on schedule and manual dispatch, never on pull requests.

## Guards for ads-txt-monitor (guards.py, every 5 minutes)

- A tag of the adstxt-crawler bot in #adstxt-crawler that the bot has not answered after 5 minutes wakes it again;
  after 15 minutes the owner gets one DM with the link.
- A scheduled ads-txt-monitor job that GitHub has not started by its deadline is started here
  (Wednesday sellers.json read, Saturday CTV stores, Sunday store sweep). The crawl itself runs on request only.
- A failed ads-txt-monitor run reaches the owner as one DM with the run link.
- Each run starts the next one when it ends, so the watcher never depends on GitHub's scheduler.
