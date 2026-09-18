# The build prompt

This is the prompt from the video. Open Claude Code in an empty folder and paste everything inside the box. It tells you what it needs first, then connects everything and opens the dashboard on your own computer.

Want the finished version instead? Open Claude Code inside this repo. It reads `CLAUDE.md` and walks you through the six steps with the script that is already here.

```
Build me a dashboard for my Meta ads that runs on my own computer. Keep it as simple as
possible: one script that pulls the numbers, one page that shows them. Work in this folder.

STEP 1. TELL ME WHAT YOU NEED BEFORE YOU BUILD ANYTHING.
Give me a short checklist of what you need from me, then walk me through getting each one,
click by click. At minimum:
  1. My Meta ad account number.
  2. An access token that can read my ads. Walk me through it in Meta Business settings:
     a system user, my ad account assigned to it, a token with ads_read. If that needs a
     Meta app first, walk me through making one.
  3. Which calendar I use for sales calls (Cal.com, Calendly, other), and a key or export
     so you can read my bookings.
  4. Whether my ad links carry tags (utm_source, utm_campaign). If they do not, show me
     exactly what to paste into the URL parameters box on each ad.
Ask for these one at a time. Save every key in a .env file, add .env to .gitignore, and
never print a key back to me or put one in the page.

STEP 2. CONNECT EVERYTHING.
Pull the last 30 days from the Meta Marketing API, one row per day per ad set: spend,
impressions, link clicks, landing page views. Pull my bookings from the calendar and tie
each one to the ad that brought it using the tags. Store it all in one local file or
SQLite table. Show me the first few rows so I can see it worked.

STEP 3. BUILD ONE PAGE.
Top to bottom, in this order, for the last 30 days:
  spend, landed (landing page views), booked, showed, cost per booked call.
Rules:
  * Every number says where it came from (Meta, my calendar).
  * If a number is not connected yet, show the row greyed out and labelled "not wired".
    Never estimate it and never fill it with a made-up number.
  * Put booked and showed side by side. A bot can book a call. If my calendar cannot tell
    you whether a call happened, show "showed" as not wired and let me mark calls by hand.
  * If a division has nothing to divide by, leave it blank. Never 0 and never NaN.
  * Readable on a phone and on a laptop.
Then serve it on localhost and open it in my browser.

STEP 4. PROVE IT.
Print yesterday's spend from the API, so I can put it next to Meta Ads Manager for the
same day. If anything does not match, tell me. Do not fix it silently.

Give me one command I can run tomorrow to refresh the numbers.
```
