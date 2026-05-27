# cseDiscordBot — Project Notes

## Bot Runner
- The bot runs on a **separate MacBook at home** (not this machine).
- The launchd plist at `deploy/com.user.cse-bot.plist` is the deployment template; it is **not loaded** on this dev machine.
- That home runner has its own clone of this repo and is what produces the daily `auto: calendar update ...` commits + pushes at 18:00 KST.
- **Implication:** when `git_publish` fails with "fetch first", the runner's clone is behind `origin/main`. Fixing it requires `git pull` on the home MacBook — pushing from this machine does not unblock the runner's next cycle.
- Likewise, refactors of `calendar_renderer.py` / `notifier.py` only take effect once the home runner is pulled to a commit that includes them.
