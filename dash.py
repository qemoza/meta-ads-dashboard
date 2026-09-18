#!/usr/bin/env python3
"""Meta ads dashboard. One script that pulls the numbers, one page that shows them.

  python3 dash.py                 pull fresh numbers, then open the page
  python3 dash.py pull            pull only, then print what landed and yesterday's spend
  python3 dash.py serve           open the page without pulling
  python3 dash.py check [DAY]     one day's spend from the Meta API next to the table
                                  (DAY is YYYY-MM-DD, default yesterday)
  python3 dash.py import FILE     load bookings from a CSV export (GoHighLevel, Calendly, any tool)
  python3 dash.py --sample        open the page with fake data, nothing connected
  python3 dash.py --sample meta-only   fake Meta numbers, no calendar (see the not wired rows)

Options:  --design clean|ledger|night   --port 8787   --no-open

Settings live in .env next to this file (it is git ignored). This script never prints a key
and never sends one to the page. Python 3.9 or newer, standard library only.
"""
import argparse, base64, csv, hashlib, hmac, json, os, random, re, sqlite3, sys, tempfile, threading
import urllib.error, urllib.parse, urllib.request, webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from zoneinfo import ZoneInfo
except ImportError:  # very old Python: fall back to UTC days
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGN_DIR = os.path.join(HERE, "designs")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")  # Cal.com and some other APIs block Python's default agent
CAL = "https://api.cal.com/v2"
CALENDLY = "https://api.calendly.com"
DEFAULT_AD_SOURCES = "facebook,fb,meta,instagram,ig,messenger,msg,an,audience_network,facebook_ads,meta_ads"
SECRET_KEYS = ("META_ACCESS_TOKEN", "CAL_API_KEY", "CALENDLY_TOKEN", "DASH_PASSWORD")
SETTINGS = ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID", "META_API_VERSION", "CAL_API_KEY", "CALENDLY_TOKEN",
            "SALES_EVENTS", "SALES_EVENT_SLUGS", "AD_SOURCES", "UNTAGGED_BOOKINGS", "DAYS", "DESIGN",
            "PORT", "HOST", "DASH_PASSWORD", "DASH_DB")


# ---------------------------------------------------------------- settings

def load_env(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


ENV_PATH = os.environ.get("DASH_ENV") or os.path.join(HERE, ".env")
E = {**load_env(ENV_PATH), **{k: os.environ[k] for k in SETTINGS if os.environ.get(k)}}
DB = E.get("DASH_DB") or os.path.join(HERE, "data.db")


def need(*keys):
    missing = [k for k in keys if not E.get(k)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}. Copy .env.example to .env and fill it in.")


def csv_set(text):
    return {w.strip().lower() for w in (text or "").split(",") if w.strip()}


# ---------------------------------------------------------------- small helpers

def get_tz(name):
    if ZoneInfo and name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone.utc


DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
              "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%b %d %Y %I:%M %p", "%b %d, %Y %I:%M %p",
              "%B %d, %Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d")


def parse_dt(value, tz=None):
    """Any date or time an API or a CSV hands us, as an aware datetime. None if it cannot be read."""
    if not value:
        return None
    s = str(value).strip()
    d = None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        s = s.replace("Z", "+00:00").replace("z", "+00:00")
        s = re.sub(r"^(\d{4}-\d{2}-\d{2}) ", r"\1T", s)
        s = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], s)  # Python 3.9 wants 6 digits
        s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            d = None
    if d is None:
        for f in DT_FORMATS:
            try:
                d = datetime.strptime(s, f)
                break
            except ValueError:
                continue
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz or timezone.utc)
    return d


def utc_str(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def first_name(name):
    parts = (name or "").split()
    return parts[0][:40] if parts else ""


def norm(text):
    """Compare utm values and campaign names loosely: case, spaces, plus signs and %20 all ignored."""
    return " ".join(urllib.parse.unquote_plus(str(text or "")).lower().split())


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")


def event_wanted(event, wanted):
    """SALES_EVENTS narrows bookings to your sales calls. A booking with no event name is kept."""
    return not wanted or not event or norm(event) in wanted or slug(event) in wanted


def clean(text):
    """Strip anything secret out of a message before it is printed."""
    text = str(text)
    for k in SECRET_KEYS:
        v = E.get(k)
        if v and len(v) > 3:
            text = text.replace(v, "***")
    text = re.sub(r"(access_token=)[^&\s\"']+", r"\1***", text)
    text = re.sub(r"(Bearer )[A-Za-z0-9._\-]+", r"\1***", text)
    return re.sub(r"act_\d+", "act_***", text)


# ---------------------------------------------------------------- HTTP

class ApiError(Exception):
    pass


def hint(code, body):
    b = body.lower()
    if '"code":200' in b.replace(" ", "") or "ads_read" in b or "ads_management" in b:
        return ("\nMeta error #200 means the token cannot read this ad account. Give the system user the ad "
                "account (Business settings, System users, Assign assets) and make a new token with ads_read.")
    if '"code":190' in b.replace(" ", ""):
        return "\nMeta says the token is expired or wrong. Make a new one and paste it into .env."
    if '"code":2500' in b.replace(" ", "") or "unknown path" in b:
        return "\nMeta did not accept the API version. Set META_API_VERSION in .env to the newest version."
    if code == 403:
        return ("\nA 403 can be the API blocking the request itself. This script already sends a browser "
                "user agent. Check the key is live and has access.")
    if code == 401:
        return "\nThe key was refused. Make a new one and paste it into .env."
    return ""


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read()[:500].decode(errors="replace")
        raise ApiError(clean(f"HTTP {e.code} from {url.split('?')[0]}: {body}") + hint(e.code, body))
    except urllib.error.URLError as e:
        raise ApiError(clean(f"Could not reach {url.split('?')[0]}: {e.reason}"))


# ---------------------------------------------------------------- Meta

def graph():
    return f"https://graph.facebook.com/{E.get('META_API_VERSION') or 'v26.0'}"


def account_id():
    a = E["META_AD_ACCOUNT_ID"].strip()
    return a if a.startswith("act_") else "act_" + a


def meta(path, **params):
    params["access_token"] = E["META_ACCESS_TOKEN"]
    return get_json(f"{graph()}/{path}?{urllib.parse.urlencode(params)}")


def meta_all(path, **params):
    page = meta(path, **params)
    rows = list(page.get("data", []))
    for _ in range(200):
        nxt = (page.get("paging") or {}).get("next")
        if not nxt:
            break
        page = get_json(nxt)
        rows += page.get("data", [])
    return rows


def action_value(row, name):
    for a in row.get("actions") or []:
        if a.get("action_type") == name:
            return int(float(a.get("value") or 0))
    return None


def parse_meta_rows(raw):
    """Meta insights rows -> meta_daily rows. Landing page views stay None when Meta sends none."""
    return [(r["date_start"], r.get("adset_id"), r.get("adset_name"), r.get("campaign_id"), r.get("campaign_name"),
             float(r.get("spend") or 0), int(r.get("impressions") or 0), int(r.get("inline_link_clicks") or 0),
             action_value(r, "landing_page_view")) for r in raw]


def ad_is_tagged(ad):
    c = ad.get("creative") or {}
    return "utm_source" in ((c.get("url_tags") or "") + (c.get("link_url") or ""))


# ---------------------------------------------------------------- calendars

def find_tag(obj, key):
    """Cal.com keeps utm tags in different places depending on how the booking was made."""
    for where in ("tracking", "bookingFieldsResponses", "responses", "metadata"):
        src = obj.get(where)
        if isinstance(src, dict):
            v = src.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def status_of(text):
    s = (text or "").strip().lower()
    return "cancelled" if s in ("cancelled", "canceled", "rejected", "declined", "deleted", "invalid") else (s or "accepted")


def parse_cal(b, tz):
    created, start = parse_dt(b.get("createdAt"), tz), parse_dt(b.get("start"), tz)
    if not b.get("uid") or not created or not start:
        return None
    att = (b.get("attendees") or [{}])[0] or {}
    return {"uid": "cal:" + str(b["uid"]), "source": "Cal.com", "created_day": str(created.astimezone(tz).date()),
            "start": utc_str(start), "event": (b.get("eventType") or {}).get("slug") or b.get("title") or "",
            "status": status_of(b.get("status")), "utm_source": find_tag(b, "utm_source"),
            "utm_campaign": find_tag(b, "utm_campaign"), "who": first_name(att.get("name")),
            "cal_showed": 0 if att.get("absent") is True else None}


def cal_bookings(since):
    got, skip = [], 0
    for _ in range(100):
        page = get_json(f"{CAL}/bookings?{urllib.parse.urlencode({'take': 100, 'skip': skip, 'sortCreated': 'desc'})}",
                        {"Authorization": "Bearer " + E["CAL_API_KEY"], "cal-api-version": "2024-08-13"})
        data = page.get("data") or []
        got += data
        oldest = min((b.get("createdAt") or "" for b in data), default="")
        if not data or not (page.get("pagination") or {}).get("hasNextPage") or (oldest and oldest[:10] < str(since - timedelta(days=1))):
            break
        skip += 100
    return got


def parse_calendly(ev, invitees, tz):
    created, start = parse_dt(ev.get("created_at"), tz), parse_dt(ev.get("start_time"), tz)
    if not ev.get("uri") or not created or not start:
        return None
    live = [i for i in invitees if i.get("status") != "canceled"]
    inv = (live or invitees or [{}])[0]
    tr = inv.get("tracking") or {}
    return {"uid": "calendly:" + ev["uri"].rstrip("/").rsplit("/", 1)[-1], "source": "Calendly",
            "created_day": str(created.astimezone(tz).date()), "start": utc_str(start), "event": ev.get("name") or "",
            "status": "cancelled" if ev.get("status") == "canceled" else "accepted",
            "utm_source": (tr.get("utm_source") or "").strip() or None,
            "utm_campaign": (tr.get("utm_campaign") or "").strip() or None,
            "who": first_name(inv.get("name")), "cal_showed": 0 if inv.get("no_show") else None}


def calendly(url, **params):
    if not url.startswith("http"):
        url = CALENDLY + url
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return get_json(url, {"Authorization": "Bearer " + E["CALENDLY_TOKEN"]})


def calendly_bookings(since, until, tz):
    me = calendly("/users/me")["resource"]["uri"]
    lo = datetime.combine(since, datetime.min.time(), tz)
    page = calendly("/scheduled_events", user=me, count=100, sort="start_time:asc",
                    min_start_time=utc_str(lo), max_start_time=utc_str(lo + timedelta(days=150)))
    events = []
    for _ in range(100):
        events += page.get("collection") or []
        nxt = (page.get("pagination") or {}).get("next_page")
        if not nxt:
            break
        page = calendly(nxt)
    out = []
    for ev in events:
        c = parse_dt(ev.get("created_at"), tz)
        if c and since <= c.astimezone(tz).date() <= until:  # only ask for invitees on bookings we keep
            out.append(parse_calendly(ev, calendly(ev["uri"] + "/invitees", count=100).get("collection") or [], tz))
    return out


CSV_COLUMNS = {
    "uid": ("id", "uid", "booking id", "appointment id", "event id", "invitee uuid"),
    "created": ("created", "created at", "created_at", "date created", "date added", "booked at", "booked on",
                "invitee created at", "event created date & time", "scheduled at"),
    "start": ("start", "start time", "start_time", "starts at", "appointment time", "appointment start time",
              "event start date & time", "start date & time", "start date", "date"),
    "status": ("status", "appointment status", "event status", "booking status"),
    "utm_source": ("utm_source", "utm source"),
    "utm_campaign": ("utm_campaign", "utm campaign"),
    "who": ("name", "invitee name", "contact name", "full name", "attendee", "first name", "contact"),
    "event": ("event", "event type", "event type name", "calendar", "calendar name", "title"),
    "showed": ("showed", "show", "attended", "no show", "no-show", "marked as no-show"),
}
SHOWED_STATUSES, NO_SHOW_STATUSES = {"showed", "show", "attended", "completed"}, {"noshow", "no-show", "no show", "no_show"}


def parse_csv_rows(lines, tz):
    """Rows of any booking export -> bookings rows. Returns (rows, skipped)."""
    reader = csv.DictReader(lines)
    cols = {}
    for field, names in CSV_COLUMNS.items():
        for h in reader.fieldnames or []:
            if norm(h) in names and field not in cols:
                cols[field] = h
    rows, skipped = [], 0
    for r in reader:
        get = lambda f: (r.get(cols[f]) or "").strip() if f in cols else ""
        start = parse_dt(get("start"), tz)
        created = parse_dt(get("created"), tz) or start
        if not start:
            skipped += 1
            continue
        raw_status = get("status").lower()
        showed_col = get("showed").lower()
        cal_showed = None
        if raw_status in SHOWED_STATUSES:
            cal_showed = 1
        elif raw_status in NO_SHOW_STATUSES:
            cal_showed = 0
        if showed_col:
            yes = showed_col in ("yes", "true", "1", "y")
            no = showed_col in ("no", "false", "0", "n")
            if "no" in norm(cols.get("showed", "")).replace("-", " ").split():  # a "no show" column flips it
                yes, no = no, yes
            cal_showed = 1 if yes else 0 if no else cal_showed
        key = get("uid") or hashlib.sha1(f"{get('created')}|{get('start')}|{get('who')}|{get('event')}".encode()).hexdigest()[:16]
        rows.append({"uid": "csv:" + key, "source": "CSV import", "created_day": str(created.astimezone(tz).date()),
                     "start": utc_str(start), "event": get("event"),
                     "status": "cancelled" if status_of(raw_status) == "cancelled" else "accepted",
                     "utm_source": get("utm_source") or None, "utm_campaign": get("utm_campaign") or None,
                     "who": first_name(get("who")), "cal_showed": cal_showed})
    return rows, skipped


# ---------------------------------------------------------------- the table

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta_daily(day TEXT, adset_id TEXT, adset_name TEXT, campaign_id TEXT,
  campaign_name TEXT, spend REAL, impressions INTEGER, link_clicks INTEGER, landing_page_views INTEGER,
  PRIMARY KEY(day, adset_id));
CREATE TABLE IF NOT EXISTS bookings(uid TEXT PRIMARY KEY, source TEXT, created_day TEXT, start TEXT,
  event TEXT, status TEXT, utm_source TEXT, utm_campaign TEXT, who TEXT, cal_showed INTEGER);
CREATE TABLE IF NOT EXISTS marks(uid TEXT PRIMARY KEY, from_ads INTEGER, showed INTEGER);
CREATE TABLE IF NOT EXISTS info(k TEXT PRIMARY KEY, v TEXT);
"""
BOOKING_COLS = ("uid", "source", "created_day", "start", "event", "status", "utm_source", "utm_campaign", "who", "cal_showed")


def db(path=None):
    con = sqlite3.connect(path or DB)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def put_bookings(con, rows, replace_source=None):
    if replace_source:
        con.execute("DELETE FROM bookings WHERE source=?", (replace_source,))
    con.executemany(f"INSERT OR REPLACE INTO bookings VALUES ({','.join('?' * len(BOOKING_COLS))})",
                    [tuple(r[c] for c in BOOKING_COLS) for r in rows])


def set_info(con, **kv):
    con.executemany("INSERT OR REPLACE INTO info VALUES (?,?)", [(k, str(v)) for k, v in kv.items()])


def calendars_in(con, pulled):
    names = list(pulled)
    if con.execute("SELECT 1 FROM bookings WHERE source='CSV import' LIMIT 1").fetchone():
        names.append("CSV import")
    return ",".join(names)


# ---------------------------------------------------------------- pull

def pull(quiet=False):
    say = (lambda *a: None) if quiet else print
    need("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")
    con = db()
    acct = account_id()
    acc = meta(acct, fields="name,currency,timezone_name")
    tz = get_tz(acc.get("timezone_name"))
    today = datetime.now(tz).date()
    since, until = today - timedelta(days=int(E.get("DAYS") or 30)), today - timedelta(days=1)

    # 1. Meta: one row per day per ad set
    raw = meta_all(f"{acct}/insights", level="adset", time_increment=1, limit=500,
                   time_range=json.dumps({"since": str(since), "until": str(until)}),
                   fields="adset_id,adset_name,campaign_id,campaign_name,spend,impressions,inline_link_clicks,actions")
    rows = parse_meta_rows(raw)
    con.execute("DELETE FROM meta_daily WHERE day BETWEEN ? AND ?", (str(since), str(until)))
    con.executemany("INSERT OR REPLACE INTO meta_daily VALUES (?,?,?,?,?,?,?,?,?)", rows)

    # 2. Do the live ad links carry tags?
    try:
        ads = meta_all(f"{acct}/ads", fields="effective_status,creative{url_tags,link_url}", limit=200,
                       effective_status=json.dumps(["ACTIVE"]))
        active, tagged = len(ads), sum(1 for a in ads if ad_is_tagged(a))
    except ApiError:
        active, tagged = "", ""

    # 3. Calendars: bookings made in the same window
    wanted = csv_set(E.get("SALES_EVENTS") or E.get("SALES_EVENT_SLUGS"))
    pulled, cal_counts = [], {}
    sources = []
    if E.get("CAL_API_KEY"):
        sources.append(("Cal.com", lambda: [parse_cal(b, tz) for b in cal_bookings(since)]))
    if E.get("CALENDLY_TOKEN"):
        sources.append(("Calendly", lambda: calendly_bookings(since, until, tz)))
    for name, fetch in sources:
        keep = [b for b in fetch() if b and str(since) <= b["created_day"] <= str(until) and event_wanted(b["event"], wanted)]
        put_bookings(con, keep, replace_source=name)
        pulled.append(name)
        cal_counts[name] = (len(keep), sum(1 for b in keep if b["status"] != "cancelled"))

    set_info(con, account_name=acc.get("name") or "", currency=acc.get("currency") or "USD",
             timezone=acc.get("timezone_name") or "UTC", since=since, until=until,
             events=",".join(sorted(wanted)) or "all", active_ads=active, active_ads_tagged=tagged,
             calendars=calendars_in(con, pulled), pulled_at=utc_str(datetime.now(timezone.utc)))
    con.commit()

    cur = acc.get("currency") or ""
    say(f"\nAccount: {acc.get('name')} ({cur}, {acc.get('timezone_name')})   window {since} to {until}")
    say(f"Meta: {len(rows)} rows, one per day per ad set. Newest first:")
    say(f"  {'day':<11}{'ad set':<34}{'spend':>10}{'impr':>9}{'clicks':>8}{'landed':>8}")
    for r in con.execute("SELECT * FROM meta_daily WHERE day BETWEEN ? AND ? ORDER BY day DESC, spend DESC LIMIT 5",
                         (str(since), str(until))):
        lpv = "-" if r["landing_page_views"] is None else r["landing_page_views"]
        say(f"  {r['day']:<11}{(r['adset_name'] or '')[:32]:<34}{r['spend']:>10.2f}{r['impressions']:>9}"
            f"{r['link_clicks']:>8}{lpv:>8}")
    if not pulled:
        say("Calendar: none connected. Add CAL_API_KEY or CALENDLY_TOKEN to .env, or run: python3 dash.py import FILE.csv")
    for name, (n, live) in cal_counts.items():
        say(f"{name}: {n} bookings made in the window, {live} not cancelled (events: {','.join(sorted(wanted)) or 'all'}).")
        for r in con.execute("SELECT * FROM bookings WHERE source=? ORDER BY created_day DESC LIMIT 5", (name,)):
            say(f"  booked {r['created_day']}  call {r['start'][:16].replace('T', ' ')}  {(r['event'] or '')[:18]:<19}"
                f"{r['status']:<10} tag: {r['utm_source'] or 'none'}")
    if active != "":
        say(f"Ad links: {tagged} of {active} live ads carry utm_source in their URL parameters.")
    con.close()

    chk = check_day(str(until), quiet=quiet)
    return {"meta_rows": len(rows), "adsets": len({r[1] for r in rows}), "days_with_rows": len({r[0] for r in rows}),
            "calendars": cal_counts, "active_ads": active, "active_ads_tagged": tagged, **chk}


def check_day(day=None, quiet=False):
    """Spend for one day, straight from the Meta API, next to what the table holds for that day."""
    say = (lambda *a: None) if quiet else print
    need("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")
    acct = account_id()
    con = db()
    info = {r["k"]: r["v"] for r in con.execute("SELECT * FROM info")}
    if "timezone" not in info:
        acc = meta(acct, fields="currency,timezone_name")
        info.update(timezone=acc.get("timezone_name"), currency=acc.get("currency"))
    tz = get_tz(info.get("timezone"))
    day = day or str(datetime.now(tz).date() - timedelta(days=1))
    res = meta(f"{acct}/insights", level="account", fields="spend",
               time_range=json.dumps({"since": day, "until": day}))
    api = round(float((res.get("data") or [{}])[0].get("spend") or 0), 2)
    in_window = info.get("since", "9") <= day <= info.get("until", "0")
    tbl = round(con.execute("SELECT COALESCE(SUM(spend),0) FROM meta_daily WHERE day=?", (day,)).fetchone()[0], 2)
    con.close()
    cur = info.get("currency") or ""
    match = abs(api - tbl) < 0.005 if in_window else None
    say(f"\nCheck one day against Meta Ads Manager ({day}):")
    say(f"  Spend from the Meta API:     {cur} {api:,.2f}")
    if in_window:
        say(f"  Same day summed from table:  {cur} {tbl:,.2f}   "
            + ("MATCH" if match else "MISMATCH. Look before you trust the page. Run pull again, then compare."))
    else:
        say("  That day is not in the table yet. Run: python3 dash.py pull")
    say(f"  Now open Ads Manager, set the date to {day} only, and read Amount spent. It should say the same.")
    return {"day": day, "api_spend": api, "table_spend": tbl if in_window else None, "match": match}


def import_csv(path):
    con = db()
    info = {r["k"]: r["v"] for r in con.execute("SELECT * FROM info")}
    tz = get_tz(info.get("timezone"))
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows, skipped = parse_csv_rows(f, tz)
    wanted = csv_set(E.get("SALES_EVENTS") or E.get("SALES_EVENT_SLUGS"))
    rows = [r for r in rows if event_wanted(r["event"], wanted)]
    put_bookings(con, rows)
    pulled = [c for c in (info.get("calendars") or "").split(",") if c and c != "CSV import"]
    set_info(con, calendars=calendars_in(con, pulled))
    con.commit()
    con.close()
    print(f"Imported {len(rows)} bookings from {os.path.basename(path)}."
          + (f" Skipped {skipped} rows with no start time I could read." if skipped else ""))
    if not info.get("since"):
        print("Run python3 dash.py pull next, so the page has a window and Meta numbers.")
    return len(rows), skipped


# ---------------------------------------------------------------- the numbers on the page

def summary(now=None):
    """Everything the page shows. None means not wired. The page never guesses."""
    con = db()
    info = {r["k"]: r["v"] for r in con.execute("SELECT * FROM info")}
    if "since" not in info:
        con.close()
        return {"empty": True}
    since, until = info["since"], info["until"]
    now = utc_str(now or datetime.now(timezone.utc))
    ad_sources = csv_set(E.get("AD_SOURCES") or DEFAULT_AD_SOURCES)
    untagged_not_ads = (E.get("UNTAGGED_BOOKINGS") or "ask").strip().lower() == "not_ads"

    m = con.execute("SELECT COALESCE(SUM(spend),0) s, COALESCE(SUM(impressions),0) i, COALESCE(SUM(link_clicks),0) c,"
                    " SUM(landing_page_views) l, COUNT(landing_page_views) lrows, COUNT(*) n"
                    " FROM meta_daily WHERE day BETWEEN ? AND ?", (since, until)).fetchone()
    meta_wired = m["n"] > 0
    spend = round(m["s"], 2) if meta_wired else None
    landed = m["l"] if m["lrows"] else None
    calendar_wired = bool(info.get("calendars"))

    books = []
    for b in con.execute("SELECT b.*, k.from_ads mf, k.showed ms FROM bookings b LEFT JOIN marks k USING(uid)"
                         " WHERE b.created_day BETWEEN ? AND ? AND b.status != 'cancelled'"
                         " ORDER BY b.start DESC", (since, until)):
        if b["mf"] is not None:
            from_ads, by = b["mf"], "mark"
        elif b["utm_source"]:
            from_ads, by = int(norm(b["utm_source"]) in ad_sources), "tag"
        elif untagged_not_ads:
            from_ads, by = 0, "rule"
        else:
            from_ads, by = None, None
        if b["ms"] is not None:
            showed, sby = b["ms"], "mark"
        elif b["cal_showed"] is not None:
            showed, sby = b["cal_showed"], "calendar"
        else:
            showed, sby = None, None
        books.append({"uid": b["uid"], "source": b["source"], "created": b["created_day"], "start": b["start"],
                      "event": b["event"], "who": b["who"], "tag": b["utm_source"], "campaign": b["utm_campaign"],
                      "from_ads": from_ads, "from_ads_by": by, "held": b["start"] < now,
                      "showed": showed, "showed_by": sby})

    unmarked = [b for b in books if b["from_ads"] is None]
    ad_books = [b for b in books if b["from_ads"] == 1]
    held = [b for b in ad_books if b["held"]]
    unshown = [b for b in held if b["showed"] is None]
    booked = len(ad_books) if calendar_wired and not unmarked else None
    showed = sum(1 for b in held if b["showed"] == 1) if booked is not None and not unshown else None
    if spend is None or booked is None:
        cpb, cpb_state = None, "not_wired"
    elif booked == 0:
        cpb, cpb_state = None, "blank"
    else:
        cpb, cpb_state = round(spend / booked, 2), "ok"

    # Tie bookings back to the Meta campaign named in utm_campaign
    campaigns = [dict(r) for r in con.execute(
        "SELECT campaign_name name, campaign_id id, ROUND(SUM(spend),2) spend, SUM(landing_page_views) landed,"
        " COUNT(landing_page_views) lrows FROM meta_daily WHERE day BETWEEN ? AND ?"
        " GROUP BY campaign_id, campaign_name ORDER BY SUM(spend) DESC", (since, until))]
    tagged_campaigns = booked is not None and any(b["campaign"] for b in ad_books)
    keys = {}
    for c in campaigns:
        keys[norm(c["name"])] = keys[norm(c["id"])] = c
    matched = {}
    for b in ad_books:
        c = keys.get(norm(b["campaign"])) if b["campaign"] else None
        if c:
            matched[id(c)] = matched.get(id(c), 0) + 1
    for c in campaigns:
        c["landed"] = c["landed"] if c.pop("lrows") else None
        c["booked"] = matched.get(id(c), 0) if tagged_campaigns else None
        c["cpb"] = round(c["spend"] / c["booked"], 2) if c["booked"] else None
    unmatched = (len(ad_books) - sum(matched.values())) if tagged_campaigns else None

    # One row per day for the chart
    per_day = {r["day"]: r for r in con.execute(
        "SELECT day, SUM(spend) s, SUM(landing_page_views) l FROM meta_daily WHERE day BETWEEN ? AND ? GROUP BY day",
        (since, until))}
    days, d, end = [], date.fromisoformat(since), date.fromisoformat(until)
    while d <= end:
        r = per_day.get(str(d))
        days.append({"day": str(d), "spend": round(r["s"], 2) if r else 0, "landed": r["l"] if r else None,
                     "booked": sum(1 for b in ad_books if b["created"] == str(d)) if booked is not None else None})
        d += timedelta(days=1)
    con.close()

    return {
        "info": info, "sample": info.get("sample") == "1", "meta_wired": meta_wired, "calendar_wired": calendar_wired,
        "spend": spend, "impressions": m["i"], "clicks": m["c"], "landed": landed,
        "booked": booked, "booked_total": len(books), "booked_unmarked": len(unmarked),
        "showed": showed, "showed_unmarked": len(unshown), "ad_calls_held": len(held),
        "ad_calls_upcoming": len(ad_books) - len(held),
        "cpb": cpb, "cpb_state": cpb_state,
        "campaigns": campaigns, "unmatched_booked": unmatched, "days": days, "books": books,
    }


# ---------------------------------------------------------------- sample data (all fake)

def make_sample(path, scenario="full"):
    """A fake account so you can see the page before you connect anything. Every name says Sample."""
    for p in (path, path + "-journal"):
        if os.path.exists(p):
            os.remove(p)
    con = db(path)
    rnd = random.Random(30)
    today = date.today()
    since, until = today - timedelta(days=30), today - timedelta(days=1)
    plan = [("Sample campaign A", "900001", [("800011", "Sample ad set A1", 38), ("800012", "Sample ad set A2", 26)]),
            ("Sample campaign B", "900002", [("800021", "Sample ad set B1", 31)]),
            ("Sample campaign C", "900003", [("800031", "Sample ad set C1", 17)])]
    d = since
    while d <= until:
        for cid, cname, sets in [(p[1], p[0], p[2]) for p in plan]:
            for sid, sname, base in sets:
                spend = round(base * rnd.uniform(0.6, 1.35), 2)
                imps = int(spend * rnd.uniform(38, 72))
                clicks = int(imps * rnd.uniform(0.009, 0.021))
                con.execute("INSERT INTO meta_daily VALUES (?,?,?,?,?,?,?,?,?)",
                            (str(d), sid, sname, cid, cname, spend, imps, clicks, int(clicks * rnd.uniform(0.62, 0.86))))
        d += timedelta(days=1)

    calendars = ""
    if scenario != "meta-only":
        calendars = "Cal.com"
        # (days ago booked, days until the call, utm_source, utm_campaign, from_ads mark, showed mark)
        rows = [(28, 3, "facebook", "Sample campaign A", None, 1), (26, 2, "facebook", "Sample campaign A", None, 1),
                (25, 4, "google", None, None, None), (23, 2, "facebook", "Sample campaign B", None, 0),
                (21, 3, "facebook", "Sample campaign A", None, 1), (19, 1, None, None, 1, 1),
                (18, 2, "newsletter", None, None, None), (16, 3, "facebook", "Sample campaign B", None, 1),
                (14, 2, "facebook", "Sample campaign A", None, 0), (12, 4, None, None, 0, None),
                (11, 2, "instagram", "Sample campaign A", None, 1), (9, 3, "facebook", "Sample campaign B", None, 1),
                (7, 2, None, None, 1, 1), (5, 2, "facebook", "Sample campaign A", None, 0),
                (4, 5, "facebook", "Sample campaign A", None, None), (3, 6, "facebook", "Sample campaign B", None, None),
                (2, 4, "google", None, None, None), (1, 5, "facebook", "Sample campaign A", None, None)]
        for n, (ago, ahead, src, camp, mark_ads, mark_showed) in enumerate(rows, 1):
            created = today - timedelta(days=ago)
            start = datetime.combine(created + timedelta(days=ahead), datetime.min.time(), timezone.utc) + timedelta(hours=9 + n % 8)
            uid = f"cal:sample-{n:02d}"
            put_bookings(con, [{"uid": uid, "source": "Cal.com", "created_day": str(created), "start": utc_str(start),
                                "event": "discovery-call", "status": "accepted", "utm_source": src, "utm_campaign": camp,
                                "who": f"Sample {n:02d}", "cal_showed": None}])
            if mark_ads is not None or mark_showed is not None:
                con.execute("INSERT INTO marks VALUES (?,?,?)", (uid, mark_ads, mark_showed))
        put_bookings(con, [{"uid": "cal:sample-99", "source": "Cal.com", "created_day": str(today - timedelta(days=8)),
                            "start": utc_str(datetime.now(timezone.utc) - timedelta(days=6)), "event": "discovery-call",
                            "status": "cancelled", "utm_source": "facebook", "utm_campaign": "Sample campaign A",
                            "who": "Sample 99", "cal_showed": None}])

    set_info(con, account_name="Sample Ads Account", currency="USD", timezone="UTC", since=since, until=until,
             events="discovery-call", active_ads=6, active_ads_tagged=5, calendars=calendars, sample=1,
             pulled_at=utc_str(datetime.now(timezone.utc)))
    con.commit()
    con.close()
    return path


# ---------------------------------------------------------------- the local web server

def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def designs():
    return sorted(f[:-5] for f in os.listdir(DESIGN_DIR) if f.endswith(".html"))


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def make_handler(design, password=None, host="127.0.0.1"):
    local_only = host in LOCAL_HOSTS

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 401:
                self.send_header("WWW-Authenticate", 'Basic realm="dashboard"')
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            port = self.server.server_address[1]
            if local_only and (self.headers.get("Host") or "") not in {f"{h}:{port}" for h in ("localhost", "127.0.0.1", "[::1]")}:
                self.send(403, {"error": "wrong host"})  # blocks other websites reaching this page through DNS tricks
                return False
            if password:
                got = self.headers.get("Authorization") or ""
                ok = False
                if got.startswith("Basic "):
                    try:
                        given = base64.b64decode(got[6:]).decode().split(":", 1)[-1]
                        ok = hmac.compare_digest(given.encode(), password.encode())
                    except Exception:
                        ok = False
                if not ok:
                    self.send(401, {"error": "password needed"})
                    return False
            return True

        def page(self, name):
            return self.send(200, read_bytes(os.path.join(DESIGN_DIR, name + ".html")), "text/html; charset=utf-8")

        def do_GET(self):
            if not self.allowed():
                return
            path = self.path.split("?")[0]
            if path == "/api/summary":
                return self.send(200, summary())
            if path in ("/", "/index.html"):
                return self.page(design)
            if path == "/dash.js":
                return self.send(200, read_bytes(os.path.join(DESIGN_DIR, "dash.js")), "text/javascript; charset=utf-8")
            if path.startswith("/d/") and path[3:] in designs():
                return self.page(path[3:])
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if not self.allowed():
                return
            if self.path != "/api/mark":
                return self.send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10000)) or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad json"})
            field, value, uid = body.get("field"), body.get("value"), body.get("uid")
            if field not in ("from_ads", "showed") or value not in (0, 1, None) or not isinstance(uid, str):
                return self.send(400, {"error": "bad mark"})
            con = db()
            try:
                if not con.execute("SELECT 1 FROM bookings WHERE uid=?", (uid,)).fetchone():
                    return self.send(404, {"error": "unknown booking"})
                con.execute("INSERT OR IGNORE INTO marks(uid) VALUES (?)", (uid,))
                con.execute(f"UPDATE marks SET {field}=? WHERE uid=?", (value, uid))
                con.commit()
            finally:
                con.close()
            self.send(200, summary())

    return Handler


def make_server(design, port, host="127.0.0.1", password=None):
    if design not in designs():
        raise SystemExit(f"No design called {design}. Pick one of: {', '.join(designs())}")
    if host not in LOCAL_HOSTS and not password:
        raise SystemExit("HOST is not local. Set DASH_PASSWORD in .env first, so strangers cannot open your numbers.")
    return ThreadingHTTPServer((host, port), make_handler(design, password, host))


def serve(design, port, host="127.0.0.1", open_browser=True, sample=False):
    url = f"http://localhost:{port}"
    try:
        srv = make_server(design, port, host, E.get("DASH_PASSWORD"))
    except OSError:
        if sample:
            raise SystemExit(f"Port {port} is busy. Try: python3 dash.py --sample --port {port + 1}")
        print(f"\nThe dashboard is already running on {url}. It reads the table live, so just open it.")
        if open_browser:
            webbrowser.open(url)
        return
    print(f"\nDashboard on {url}  (design: {design}. Others: {url}/d/<name>. Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv=None):
    global DB
    ap = argparse.ArgumentParser(description="Meta ads dashboard. Pull the numbers, show them on one page.")
    ap.add_argument("cmd", nargs="?", default="all", choices=["all", "pull", "serve", "check", "import"])
    ap.add_argument("arg", nargs="?", help="check: the day (YYYY-MM-DD). import: the CSV file.")
    ap.add_argument("--sample", nargs="?", const="full", choices=["full", "meta-only"], help="fake data, nothing connected")
    ap.add_argument("--design", default=E.get("DESIGN") or "clean")
    ap.add_argument("--port", type=int, default=int(E.get("PORT") or 8787))
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    a = ap.parse_args(argv)
    try:
        if a.sample:
            DB = make_sample(os.path.join(tempfile.gettempdir(), f"meta-ads-dashboard-sample-{a.sample}.db"), a.sample)
            print("Sample mode. Every number is fake.")
            return serve(a.design, a.port, E.get("HOST") or "127.0.0.1", not a.no_open, sample=True)
        if a.cmd in ("pull", "all"):
            pull()
        if a.cmd == "check":
            check_day(a.arg)
        if a.cmd == "import":
            if not a.arg:
                raise SystemExit("Usage: python3 dash.py import bookings.csv")
            import_csv(a.arg)
        if a.cmd in ("serve", "all"):
            serve(a.design, a.port, E.get("HOST") or "127.0.0.1", not a.no_open)
    except ApiError as e:
        raise SystemExit(f"\n{e}")


if __name__ == "__main__":
    main()
