# markapp-orders-trigger

Every 5 minutes, checks MarkApp's order channels in Slack for new activity and wakes the private order bot. It contains no business logic or data and logs only counts. All order work happens in the private bot repo.

Public on purpose: GitHub Actions minutes are free for public repos. Secrets (`SLACK_BOT_TOKEN`, `DISPATCH_TOKEN`) are encrypted repository secrets. The workflow runs only on schedule and manual dispatch, never on pull requests.
