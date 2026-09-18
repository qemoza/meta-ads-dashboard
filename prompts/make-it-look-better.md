# Make it look better

The `designs/` folder has three pages: `clean`, `ledger` and `night`. Run `python3 dash.py --sample` and open `http://localhost:8787/d/clean`, `/d/ledger` and `/d/night` to compare them with fake numbers. Pick one with `--design` or `DESIGN=` in `.env`.

To make your own, open Claude Code inside this repo and paste this.

```
Read CLAUDE.md first. I want my own design for the dashboard page.

Look at designs/clean.html, designs/ledger.html and designs/night.html, and at
designs/dash.js, which they all share. Ask me which one is closest to what I want and what I
would change (colours, fonts, my brand, what goes first, what I never look at).

Then copy the closest one to designs/mine.html and change only the HTML and CSS. Keep using
the Dash helpers so these stay true:
  the five numbers stay top to bottom: spend, landed, booked, showed, cost per booked call,
  every number says where it came from,
  anything not connected shows grey and says not wired,
  a division with nothing to divide by stays blank,
  booked sits next to showed.

Check it with python3 dash.py --sample and python3 dash.py --sample meta-only.
Take screenshots at 375px and 1280px wide, look at them, and fix anything that overflows or
is hard to read before you show me. Then set DESIGN=mine in .env.
```
