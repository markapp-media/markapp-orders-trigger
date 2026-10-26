# markapp-orders-trigger

A run starts every 20 minutes and watches for about 50 minutes, checking every 45 seconds MarkApp's order channels in Slack for new activity and wakes the private order bot. It contains no business logic or data, and its logs say only "ok" or an error type (no message content, channel ids or counts). All order work happens in the private bot repo.

Public on purpose: GitHub Actions minutes are free for public repos. Secrets (`SLACK_BOT_TOKEN`, `HARION_DSP_OPS_BOT_TOKEN`, `DISPATCH_TOKEN`) are encrypted repository secrets. The workflow runs only on schedule and manual dispatch, never on pull requests.
