# Add showed

A bot can book a call. Only a call that happened is worth paying for. So showed sits next to booked, and it stays grey (not wired) until every past call from the ads is accounted for.

The simplest way already works: open the page, find each past call in the list, and press Yes or No under Showed. Your marks are saved in `data.db` and stay when you refresh.

To fill it in without clicking, open Claude Code inside this repo and paste this.

```
Read CLAUDE.md first. I want showed on my dashboard to fill in by itself where it can.

Ask me where I can tell that a sales call really happened. For example:
  a no show button in my calendar (Cal.com, Calendly and GoHighLevel all have one),
  a call recorder or meeting tool (Zoom, Google Meet, Fathom and similar) that logs every call,
  my CRM, where I move a lead after the call.

Then wire the one I pick into the cal_showed column of the bookings table:
1 means the call happened, 0 means no show, None means we do not know.
Never guess. A call with no signal stays None so I can mark it by hand on the page.
A hand mark on the page always wins over anything the script reads.

Add a test with made up data. Then run a real pull and show me how many past ad calls now
have a showed value and how many still need me.
```
