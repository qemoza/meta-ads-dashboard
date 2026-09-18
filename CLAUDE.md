# Read this first

You are in the Meta Ads Dashboard repo. One script (`dash.py`) pulls Meta ads numbers and calendar bookings into one SQLite file (`data.db`) and serves one page on localhost. Your job is to get the person in front of you from nothing to a working page with their own numbers, then keep it honest.

Talk in plain words. Short sentences. One step at a time. Ask for one thing, wait for it, then move on.

## Where to start

1. Run `python3 --version`. Python 3.9 or newer is all this needs. Nothing to install.
2. Run `python3 -m unittest -v`. Every test should pass before you touch anything.
3. If there is no `.env`, run `cp .env.example .env`.
4. Offer the preview first: `python3 dash.py --sample` opens the page with fake numbers, so they see where this is going.
5. Then walk the six steps below in order. Skip any step that is already done, and say so.

To see which settings are filled in without showing them, run:

```bash
python3 -c "import dash; print({k: ('set' if dash.E.get(k) else 'empty') for k in ('META_ACCESS_TOKEN','META_AD_ACCOUNT_ID','CAL_API_KEY','CALENDLY_TOKEN','SALES_EVENTS')})"
```

## The six steps

1. **Their Meta key.** Walk them through Meta Business settings click by click: System users, add one, assign the ad account with view performance, generate a token with `ads_read`. If they have no Meta app, walk them through making one at developers.facebook.com and connecting it to their business portfolio. Then get the ad account number from Ads Manager (the digits after `act=`). Write both into `.env` as `META_ACCESS_TOKEN` and `META_AD_ACCOUNT_ID`. Meta renames buttons often. If they are stuck, ask for a screenshot and read it.
2. **Pull the numbers.** Run `python3 dash.py pull`. It prints the first rows and yesterday's spend. Show them the rows. If it fails, read the error: `dash.py` adds a plain hint under every Meta error it knows.
3. **Tag their ad links.** Each ad's URL parameters box (Ads Manager, the ad, Tracking) gets `utm_source=facebook&utm_medium=paid&utm_campaign={{campaign.name}}&utm_content={{ad.name}}`. The pull prints how many live ads carry `utm_source`. Tell them the count.
4. **Send bookings in.** Ask which calendar or funnel they use. Cal.com goes in as `CAL_API_KEY`. Calendly goes in as `CALENDLY_TOKEN`. Anything else: a CSV export and `python3 dash.py import FILE.csv`, or wire a new source (see below). Ask which event types are sales calls and put them in `SALES_EVENTS`. Then have them make one test booking through a tagged link, pull, and check the booking carries the tag. If it does not, the tags are lost between the landing page and the calendar. Fix that before anything else, using `prompts/connect-your-funnel.md`.
5. **One page.** Run `python3 dash.py`. It pulls, then opens `http://localhost:8787`. Show them the five numbers and how to mark untagged bookings and past calls on the page.
6. **Check one day.** Run `python3 dash.py check` and have them open Ads Manager for that same single day and read Amount spent. It must match to the cent. If it does not, say so and find out why. Never adjust a number to make it match.

After that, offer to keep it running (`prompts/run-it-every-hour.md`) and to change the look (`prompts/make-it-look-better.md`).

## Rules. These do not bend.

- **Never print a key.** Do not `cat .env`, do not echo a token, do not paste one into a page, a log, a commit or a screenshot. When they paste a key to you, write it straight into `.env` and say only that it is saved. Use the settings check above to see what is filled in.
- **Not wired, never guessed.** A number with no source behind it is `None` in `summary()` and shows grey with the words **not wired**. Never estimate one, never fill one with a made up value, never use 0 as a stand in.
- **Blank on divide by nothing.** Cost per booked call with zero booked is blank. Never 0, never NaN, never Infinity. The same goes for every rate you add.
- **Booked sits next to showed.** A bot can book a call. Showed only counts past calls that were marked as happened, by hand or by the calendar's no show flag. If any past ad call is unmarked, showed is not wired.
- **Every number names its source** on the page.
- **Check one day against Ads Manager** after any change to how Meta numbers are pulled.
- **Do not fix a mismatch silently.** Tell them what does not match and why you think so.
- **Tests stay green.** Run `python3 -m unittest -v` after every change. Add a test for any new maths.

## How it fits together

| Piece | What it does |
|---|---|
| `pull()` | Meta insights at ad set level, one row per day (`meta_daily`). Live ads checked for `utm_source`. Then each connected calendar into `bookings`. Ends with `check_day()` for yesterday |
| `check_day(day)` | Spend for one day from the API next to the table |
| `import_csv(path)` | Any booking export into `bookings`, source `CSV import`. Column names are matched loosely |
| `summary()` | Every number on the page. `None` means not wired. Ties bookings to campaigns by `utm_campaign` (name or id) |
| `marks` table | Hand marks from the page: `from_ads` and `showed` per booking. A mark beats a tag |
| `make_sample()` | The fake account behind `--sample` |
| `designs/*.html` | The pages. Each one only decides the look |
| `designs/dash.js` | Shared by every design: loads `/api/summary`, builds the five rows, draws the chart, saves marks |

## Adding a new booking source

Every source writes rows into the same `bookings` table, so the page and the maths never change. A row is a dict:

| Key | Meaning |
|---|---|
| `uid` | Unique id, prefixed with the source, like `ghl:abc123` |
| `source` | Shown on the page, like `GoHighLevel` |
| `created_day` | The day the booking was made, `YYYY-MM-DD`, in the ad account's time zone |
| `start` | When the call is, UTC, `YYYY-MM-DDTHH:MM:SSZ` (use `utc_str()`) |
| `event` | Event type name, matched against `SALES_EVENTS` |
| `status` | `accepted` or `cancelled` |
| `utm_source`, `utm_campaign` | The tags, or `None` |
| `who` | First name only (use `first_name()`). Never store emails or phone numbers |
| `cal_showed` | `1` if the tool says the call happened, `0` if it says no show, else `None` |

Write a fetch function that returns a list of these, add it to the `sources` list in `pull()` with its name, and read its key from `.env` the way `CAL_API_KEY` is read. Send a browser user agent (`get_json()` already does). Add a parser test with a made up fixture. Then run a real pull and show them the counts.

## Changing the look

Copy one of `designs/*.html` to a new name. It shows up at `http://localhost:8787/d/<name>` and with `--design <name>`. Only change HTML and CSS. Keep using the `Dash` helpers so the rules above hold. Check it with `python3 dash.py --sample` and `python3 dash.py --sample meta-only`, at 375px and 1280px wide, with no sideways scroll.

## Commands

```bash
python3 dash.py                  # pull, then open the page
python3 dash.py pull             # pull only
python3 dash.py serve            # open the page, no pull
python3 dash.py check [DAY]      # one day against the Meta API
python3 dash.py import FILE.csv  # bookings from any export
python3 dash.py --sample         # fake data
python3 -m unittest -v           # tests
```
