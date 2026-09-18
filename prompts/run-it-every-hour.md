# Run it every hour

On your laptop the page only runs while the laptop is open. On a small server it runs all day. Open Claude Code inside this repo and paste the one you want.

## On my laptop

```
Read CLAUDE.md first. I want the numbers to refresh every hour on this computer, and the page
to be there when I open my browser.

Set up an hourly job that runs python3 dash.py pull from this folder and writes its output to
pull.log. On a Mac use cron or launchd, and check the folder is not inside Desktop, Documents
or Downloads, where macOS blocks background jobs. On Windows use Task Scheduler.
Also start python3 dash.py serve --no-open when I log in.

Run the job once by hand, show me the last lines of pull.log, and show me how to turn it off.
```

## On a server

```
Read CLAUDE.md first. I want this dashboard running all day on a server, for example a
Hostinger VPS, so it keeps refreshing when my laptop is closed.

Walk me through it one step at a time:
1. Log in to the server over SSH and check Python 3.9 or newer is there.
2. Copy this folder up without data.db. Make the .env on the server and help me paste my
   keys into it without printing them.
3. Run python3 dash.py pull once and show me the counts and yesterday's spend.
4. Add a cron line that runs the pull every hour and logs to pull.log.
5. Keep python3 dash.py serve --no-open running with systemd, so it comes back after a restart.
6. Keep HOST=127.0.0.1 and show me how to open the page from my laptop with
   ssh -L 8787:localhost:8787 me@my-server.

Only if I ask for a public address: set a long DASH_PASSWORD, set HOST=0.0.0.0, put HTTPS in
front of it (Caddy is the simplest), and prove a request with no password gets refused.
```
