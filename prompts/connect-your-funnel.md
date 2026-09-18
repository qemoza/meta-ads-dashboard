# Connect your funnel

The numbers before the click come from Meta and work the same for everyone. The numbers after the click depend on how people book with you. Open Claude Code inside this repo, pick the part below that matches your funnel, and paste it.

## Not sure which one you have

```
Read CLAUDE.md first. I want booked and showed on my dashboard, and I am not sure how to get
my bookings in. Ask me how people book a call with me after they click an ad, one question at
a time. Then tell me the simplest way to get those bookings into the bookings table, with the
ad tags (utm_source, utm_campaign) still on them. Do not build anything until I say yes.
```

## Cal.com

```
Read CLAUDE.md first. I use Cal.com. Help me put my API key into .env as CAL_API_KEY without
printing it. Ask me which event types are sales calls and put their slugs in SALES_EVENTS.
Then run python3 dash.py pull and show me the booking counts.

Then check the tags. I will open my landing page with ?utm_source=facebook&utm_campaign=test
on the end and book a test call. Pull again and tell me if that booking carries the tags.
If it does not, find out how my page hands people to Cal.com (a link, an embed, a redirect)
and change it so the utm tags reach the booking, as booking metadata or as hidden booking
questions. dash.py already reads tags from both places. Check the current Cal.com docs for
the right way, test it with one more booking, and show me it worked.
```

## Calendly

```
Read CLAUDE.md first. I use Calendly. Help me make a personal access token and put it into
.env as CALENDLY_TOKEN without printing it. Ask me which event types are sales calls and put
their names in SALES_EVENTS. Run python3 dash.py pull and show me the booking counts.

Then check the tags. I will open my landing page with ?utm_source=facebook&utm_campaign=test
on the end and book a test call. Pull again and tell me if that booking carries the tags.
If it does not, look at how my page shows Calendly (a link or an embed) and make the utm
tags from the page address reach Calendly. Test it with one more booking and show me.
```

## GoHighLevel

```
Read CLAUDE.md first. My funnel and calendar are in GoHighLevel. I want my GoHighLevel
appointments in the bookings table with their ad tags.

Start with the simple way: tell me exactly where to export my appointments as a CSV, then
run python3 dash.py import on it and show me what came in and what was skipped.

If I want it every hour instead, add a GoHighLevel source to dash.py the way CLAUDE.md
describes. Walk me through making a Private Integration token with read access to
calendars, appointments and contacts, and put it in .env without printing it. Read each
appointment's status (showed and no show count for cal_showed) and the contact's
attribution for utm_source and utm_campaign. Check the current GoHighLevel API docs for the
exact endpoints and fields. Send a browser user agent. Add a test with made up data, run a
real pull, and show me the counts.
```

## My own website or form

```
Read CLAUDE.md first. People land on my own website and book or fill in a form there. I want
those bookings in the bookings table with their ad tags.

Ask me what the site is built with and where a booking or form entry ends up (an email, a
spreadsheet, a CRM, a database, a calendar). Then pick the simplest path:
  1. If the tool can export a CSV, use python3 dash.py import.
  2. If it has an API, add a source to dash.py the way CLAUDE.md describes.
Also make sure the tags survive: the page should read utm_source and utm_campaign from its
own address and pass them into the form or the booking link as hidden fields. Test it with
one real booking through a tagged link and show me the tags arrived.
```
