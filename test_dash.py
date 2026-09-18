"""Tests for the numbers the page shows, the utm tie back, the calendar readers and the page itself.
Run: python3 -m unittest -v
Nothing here touches the internet. Every name and number is made up.
"""
import base64, http.client, io, json, os, tempfile, threading, unittest
from datetime import datetime, timedelta, timezone
import dash

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)


class Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.old_db, self.old_env = dash.DB, dict(dash.E)
        dash.DB = self.path
        dash.E.clear()
        self.con = dash.db()

    def tearDown(self):
        self.con.close()
        dash.DB = self.old_db
        dash.E.clear()
        dash.E.update(self.old_env)
        os.remove(self.path)

    def info(self, calendars="Cal.com"):
        dash.set_info(self.con, since="2026-08-19", until="2026-09-17", currency="USD", timezone="UTC",
                      active_ads=2, active_ads_tagged=1, calendars=calendars, pulled_at="2026-09-18T09:00:00Z")
        self.con.commit()

    def meta_rows(self, *rows):
        self.con.executemany("INSERT INTO meta_daily VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self.con.commit()

    def booking(self, uid, created="2026-09-10", start="2026-09-11T10:00:00Z", status="accepted",
                src=None, camp=None, cal_showed=None):
        dash.put_bookings(self.con, [{"uid": uid, "source": "Cal.com", "created_day": created, "start": start,
                                      "event": "discovery-call", "status": status, "utm_source": src,
                                      "utm_campaign": camp, "who": "Test", "cal_showed": cal_showed}])
        self.con.commit()

    def mark(self, uid, from_ads, showed=None):
        self.con.execute("INSERT OR REPLACE INTO marks VALUES (?,?,?)", (uid, from_ads, showed))
        self.con.commit()


class TheMaths(Base):
    def setUp(self):
        super().setUp()
        self.info()
        self.meta_rows(("2026-09-16", "s1", "Set one", "c1", "Campaign One", 100.0, 500, 20, 14),
                       ("2026-09-17", "s1", "Set one", "c1", "Campaign One", 72.5, 1200, 16, 11),
                       ("2026-07-01", "s1", "Set one", "c1", "Campaign One", 999.0, 1, 1, 1))  # outside the window
        self.booking("past1", created="2026-09-10", start="2026-09-11T10:00:00Z")
        self.booking("past2", created="2026-09-12", start="2026-09-13T10:00:00Z")
        self.booking("future", created="2026-09-17", start="2099-01-01T10:00:00Z")
        self.booking("gone", created="2026-09-14", start="2026-09-15T10:00:00Z", status="cancelled")

    def test_meta_totals_only_count_the_window(self):
        s = dash.summary(NOW)
        self.assertAlmostEqual(s["spend"], 172.5)
        self.assertEqual(s["landed"], 25)
        self.assertEqual(s["clicks"], 36)

    def test_untagged_bookings_leave_booked_showed_and_cost_not_wired(self):
        s = dash.summary(NOW)
        self.assertIsNone(s["booked"])
        self.assertIsNone(s["showed"])
        self.assertIsNone(s["cpb"])
        self.assertEqual(s["cpb_state"], "not_wired")
        self.assertEqual(s["booked_total"], 3)  # the cancelled one is left out
        self.assertEqual(s["booked_unmarked"], 3)

    def test_zero_booked_gives_blank_cost_never_zero(self):
        for u in ("past1", "past2", "future"):
            self.mark(u, 0)
        s = dash.summary(NOW)
        self.assertEqual(s["booked"], 0)
        self.assertIsNone(s["cpb"])
        self.assertEqual(s["cpb_state"], "blank")
        self.assertTrue(all(c["cpb"] is None for c in s["campaigns"]))

    def test_showed_waits_for_every_past_ad_call(self):
        self.mark("past1", 1, 1)
        self.mark("past2", 1)
        self.mark("future", 1)
        s = dash.summary(NOW)
        self.assertEqual(s["booked"], 3)
        self.assertAlmostEqual(s["cpb"], round(172.5 / 3, 2))
        self.assertIsNone(s["showed"])  # past2 is not marked yet
        self.assertEqual(s["showed_unmarked"], 1)
        self.mark("past2", 1, 0)
        s = dash.summary(NOW)
        self.assertEqual(s["showed"], 1)
        self.assertEqual(s["ad_calls_held"], 2)
        self.assertEqual(s["ad_calls_upcoming"], 1)

    def test_calendar_no_show_counts_without_a_hand_mark(self):
        self.con.execute("UPDATE bookings SET utm_source='facebook'")
        self.con.execute("UPDATE bookings SET cal_showed=0 WHERE uid='past2'")
        self.con.commit()
        self.mark("past1", None, 1)
        s = dash.summary(NOW)
        self.assertEqual(s["showed"], 1)
        self.assertEqual([b["showed_by"] for b in s["books"] if b["uid"] == "past2"], ["calendar"])

    def test_no_calendar_means_booked_showed_cost_not_wired(self):
        self.con.execute("DELETE FROM bookings")
        self.info(calendars="")
        s = dash.summary(NOW)
        self.assertFalse(s["calendar_wired"])
        self.assertIsNone(s["booked"])
        self.assertIsNone(s["showed"])
        self.assertEqual(s["cpb_state"], "not_wired")

    def test_calendar_wired_with_no_bookings_is_zero_booked_and_blank_cost(self):
        self.con.execute("DELETE FROM bookings")
        self.con.commit()
        s = dash.summary(NOW)
        self.assertEqual(s["booked"], 0)
        self.assertEqual(s["cpb_state"], "blank")

    def test_no_meta_rows_means_not_wired(self):
        self.con.execute("DELETE FROM meta_daily")
        self.con.commit()
        s = dash.summary(NOW)
        self.assertIsNone(s["spend"])
        self.assertIsNone(s["landed"])
        self.assertEqual(s["cpb_state"], "not_wired")

    def test_no_landing_page_views_means_landed_not_wired(self):
        self.con.execute("UPDATE meta_daily SET landing_page_views=NULL")
        self.con.commit()
        s = dash.summary(NOW)
        self.assertIsNotNone(s["spend"])
        self.assertIsNone(s["landed"])

    def test_empty_table_says_empty(self):
        self.con.execute("DELETE FROM info")
        self.con.commit()
        self.assertEqual(dash.summary(NOW), {"empty": True})


class UtmTieBack(Base):
    def setUp(self):
        super().setUp()
        self.info()
        self.meta_rows(("2026-09-16", "s1", "Set A", "111", "Spring Offer", 300.0, 900, 30, 20),
                       ("2026-09-16", "s2", "Set B", "222", "Retargeting", 100.0, 300, 10, 8))

    def test_ad_sources_count_without_a_hand_mark(self):
        self.booking("a", src="facebook")
        self.booking("b", src="IG")
        self.booking("c", src="google")
        s = dash.summary(NOW)
        self.assertEqual(s["booked"], 2)
        self.assertEqual({b["uid"]: b["from_ads_by"] for b in s["books"]}, {"a": "tag", "b": "tag", "c": "tag"})

    def test_a_mark_beats_the_tag(self):
        self.booking("a", src="facebook")
        self.mark("a", 0)
        self.assertEqual(dash.summary(NOW)["booked"], 0)

    def test_campaign_tag_matches_name_loosely_or_id(self):
        self.booking("a", src="facebook", camp="spring+offer")
        self.booking("b", src="facebook", camp="Spring%20Offer")
        self.booking("c", src="fb", camp="222")          # {{campaign.id}} works too
        self.booking("d", src="facebook", camp="Old campaign")  # matches nothing
        self.booking("e", src="facebook")                 # no campaign tag
        s = dash.summary(NOW)
        by = {c["name"]: c for c in s["campaigns"]}
        self.assertEqual(by["Spring Offer"]["booked"], 2)
        self.assertEqual(by["Spring Offer"]["cpb"], 150.0)
        self.assertEqual(by["Retargeting"]["booked"], 1)
        self.assertEqual(s["unmatched_booked"], 2)
        self.assertEqual(s["booked"], 5)

    def test_campaign_column_not_wired_when_no_booking_carries_a_campaign(self):
        self.booking("a", src="facebook")
        s = dash.summary(NOW)
        self.assertEqual(s["booked"], 1)
        self.assertTrue(all(c["booked"] is None for c in s["campaigns"]))
        self.assertIsNone(s["unmatched_booked"])

    def test_campaign_with_no_bookings_has_blank_cost(self):
        self.booking("a", src="facebook", camp="Spring Offer")
        by = {c["name"]: c for c in dash.summary(NOW)["campaigns"]}
        self.assertEqual(by["Retargeting"]["booked"], 0)
        self.assertIsNone(by["Retargeting"]["cpb"])

    def test_untagged_can_mean_not_ads_once_you_trust_your_tags(self):
        self.booking("a", src="facebook")
        self.booking("b")
        self.assertIsNone(dash.summary(NOW)["booked"])
        dash.E["UNTAGGED_BOOKINGS"] = "not_ads"
        self.assertEqual(dash.summary(NOW)["booked"], 1)


class Readers(unittest.TestCase):
    def test_meta_rows_take_landing_page_views_from_actions(self):
        rows = dash.parse_meta_rows([
            {"date_start": "2026-09-17", "adset_id": "1", "adset_name": "A", "campaign_id": "9", "campaign_name": "C",
             "spend": "12.34", "impressions": "1000", "inline_link_clicks": "20",
             "actions": [{"action_type": "link_click", "value": "20"}, {"action_type": "landing_page_view", "value": "15"}]},
            {"date_start": "2026-09-17", "adset_id": "2", "spend": "5", "impressions": "10"}])
        self.assertEqual(rows[0][5:], (12.34, 1000, 20, 15))
        self.assertIsNone(rows[1][8])  # no landing page views sent means None, never 0

    def test_cal_booking(self):
        tz = dash.get_tz("America/New_York")
        b = dash.parse_cal({"uid": "u1", "createdAt": "2026-09-10T02:30:00.000Z", "start": "2026-09-12T15:00:00.000Z",
                            "status": "accepted", "eventType": {"slug": "discovery-call"},
                            "attendees": [{"name": "Sample Person Three", "absent": True}],
                            "bookingFieldsResponses": {"utm_source": " Facebook "},
                            "metadata": {"utm_campaign": "Spring Offer"}}, tz)
        self.assertEqual(b["created_day"], "2026-09-09")  # 02:30 UTC is still the 9th in New York
        self.assertEqual(b["start"], "2026-09-12T15:00:00Z")
        self.assertEqual((b["utm_source"], b["utm_campaign"]), ("Facebook", "Spring Offer"))
        self.assertEqual(b["who"], "Sample")  # first name only is stored
        self.assertEqual(b["cal_showed"], 0)
        self.assertEqual(dash.parse_cal({"uid": "u2", "createdAt": "2026-09-10T02:30:00Z", "start": "2026-09-12T15:00:00Z",
                                         "status": "cancelled", "tracking": {"utm_source": "fb"}}, tz)["utm_source"], "fb")

    def test_calendly_booking(self):
        ev = {"uri": "https://api.calendly.com/scheduled_events/EV123", "name": "Discovery Call", "status": "active",
              "start_time": "2026-09-12T15:00:00.000000Z", "created_at": "2026-09-10T11:00:00.123456Z"}
        inv = [{"name": "Test Invitee", "status": "active", "no_show": {"uri": "x"},
                "tracking": {"utm_source": "facebook", "utm_campaign": "Spring Offer", "utm_medium": None}}]
        b = dash.parse_calendly(ev, inv, dash.get_tz("UTC"))
        self.assertEqual(b["uid"], "calendly:EV123")
        self.assertEqual((b["utm_source"], b["utm_campaign"], b["who"], b["cal_showed"]), ("facebook", "Spring Offer", "Test", 0))
        self.assertEqual(dash.parse_calendly({**ev, "status": "canceled"}, [], dash.get_tz("UTC"))["status"], "cancelled")
        self.assertTrue(dash.event_wanted("Discovery Call", {"discovery-call"}))
        self.assertFalse(dash.event_wanted("Coffee chat", {"discovery-call"}))

    def test_dates_in_every_shape(self):
        for s in ("2026-09-12T15:00:00Z", "2026-09-12T15:00:00.000Z", "2026-09-12T15:00:00.123456Z",
                  "2026-09-12T17:00:00+0200", "2026-09-12 15:00:00", "09/12/2026 3:00 PM"):
            self.assertEqual(dash.utc_str(dash.parse_dt(s)), "2026-09-12T15:00:00Z", s)
        self.assertIsNone(dash.parse_dt("not a date"))


class CsvImport(Base):
    def test_a_funnel_export_loads_with_its_own_column_names(self):
        text = ("Contact Name,Appointment Time,Date Added,Appointment Status,utm_source,UTM Campaign,Calendar\n"
                "Sample A,2026-09-11 10:00,2026-09-09 08:00,showed,facebook,Spring Offer,Sales call\n"
                "Sample B,2026-09-12 11:00,2026-09-10 08:00,noshow,facebook,Spring Offer,Sales call\n"
                "Sample C,2026-09-13 12:00,2026-09-10 09:00,cancelled,google,,Sales call\n"
                "Bad Row,someday,,confirmed,,,Sales call\n")
        rows, skipped = dash.parse_csv_rows(io.StringIO(text), dash.get_tz("UTC"))
        self.assertEqual(skipped, 1)
        self.assertEqual([r["cal_showed"] for r in rows], [1, 0, None])
        self.assertEqual([r["status"] for r in rows], ["accepted", "accepted", "cancelled"])
        self.assertEqual(rows[0]["created_day"], "2026-09-09")
        self.assertEqual(rows[0]["who"], "Sample")
        self.assertTrue(rows[0]["uid"].startswith("csv:"))

    def test_import_command_adds_csv_as_a_calendar(self):
        self.info(calendars="")
        fd, p = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w") as f:
            f.write("name,start time,created at,utm_source\nSample D,2026-09-11T10:00:00Z,2026-09-10T10:00:00Z,facebook\n")
        try:
            dash.import_csv(p)
        finally:
            os.remove(p)
        s = dash.summary(NOW)
        self.assertEqual(s["info"]["calendars"], "CSV import")
        self.assertEqual(s["booked"], 1)


class Safety(unittest.TestCase):
    def test_errors_never_show_the_token_or_account(self):
        old = dict(dash.E)
        try:
            dash.E["META_ACCESS_TOKEN"] = "fake-token-abc123"
            msg = dash.clean("GET https://graph.facebook.com/v26.0/act_123456789/insights?access_token=fake-token-abc123&x=1 "
                             "Authorization: Bearer abc.def-ghi fake-token-abc123")
        finally:
            dash.E.clear()
            dash.E.update(old)
        self.assertNotIn("fake-token-abc123", msg)
        self.assertNotIn("123456789", msg)
        self.assertNotIn("abc.def-ghi", msg)

    def test_meta_permission_error_explains_ads_read(self):
        self.assertIn("ads_read", dash.hint(400, '{"error":{"message":"(#200) Ad account owner has NOT grant ads_management or ads_read permission","code": 200}}'))


class ThePage(unittest.TestCase):
    """Sample mode renders: every design, the shared script, the summary, marks, and the locks."""

    def start(self, password=None, design="clean"):
        srv = dash.make_server(design, 0, "127.0.0.1", password)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def get(self, port, path, method="GET", body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": host or f"localhost:{port}", **(headers or {})}
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def setUp(self):
        self.old = dash.DB
        dash.DB = dash.make_sample(os.path.join(tempfile.gettempdir(), "meta-ads-dashboard-test-sample.db"))
        self.addCleanup(lambda: setattr(dash, "DB", self.old))

    def test_sample_summary_has_all_five_numbers(self):
        s = dash.summary()
        self.assertTrue(s["sample"])
        for k in ("spend", "landed", "booked", "showed", "cpb"):
            self.assertIsNotNone(s[k], k)
        self.assertEqual(s["cpb_state"], "ok")
        self.assertEqual(len(s["days"]), 30)
        self.assertTrue(all(b["who"].startswith("Sample") for b in s["books"]))
        self.assertTrue(any(c["booked"] == 0 and c["cpb"] is None for c in s["campaigns"]))  # campaign C: blank cost

    def test_sample_meta_only_shows_not_wired_rows(self):
        dash.DB = dash.make_sample(os.path.join(tempfile.gettempdir(), "meta-ads-dashboard-test-meta-only.db"), "meta-only")
        s = dash.summary()
        self.assertIsNotNone(s["spend"])
        self.assertFalse(s["calendar_wired"])
        self.assertIsNone(s["booked"])
        self.assertEqual(s["cpb_state"], "not_wired")

    def test_every_design_serves(self):
        port = self.start()
        for name in dash.designs():
            status, html = self.get(port, "/d/" + name)
            self.assertEqual(status, 200, name)
            self.assertIn(b'<script src="/dash.js"></script>', html, name)
            self.assertIn(b"not wired", html + dash.read_bytes(os.path.join(dash.DESIGN_DIR, "dash.js")))
        self.assertEqual(self.get(port, "/")[0], 200)
        self.assertEqual(self.get(port, "/dash.js")[0], 200)
        self.assertEqual(self.get(port, "/d/nope")[0], 404)
        status, body = self.get(port, "/api/summary")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["sample"])
        self.assertGreaterEqual(len(dash.designs()), 3)

    def test_marks_save_and_bad_marks_are_refused(self):
        port = self.start()
        uid = next(b["uid"] for b in dash.summary()["books"] if b["from_ads"] == 1)
        status, body = self.get(port, "/api/mark", "POST", {"uid": uid, "field": "from_ads", "value": 0},
                                {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(next(b for b in json.loads(body)["books"] if b["uid"] == uid)["from_ads"], 0)
        self.assertEqual(self.get(port, "/api/mark", "POST", {"uid": uid, "field": "spend", "value": 1})[0], 400)
        self.assertEqual(self.get(port, "/api/mark", "POST", {"uid": "nope", "field": "showed", "value": 1})[0], 404)

    def test_other_hosts_are_turned_away(self):
        port = self.start()
        self.assertEqual(self.get(port, "/api/summary", host="evil.example:80")[0], 403)

    def test_password_when_set(self):
        port = self.start(password="letmein")
        self.assertEqual(self.get(port, "/api/summary")[0], 401)
        ok = base64.b64encode(b"me:letmein").decode()
        bad = base64.b64encode(b"me:nope").decode()
        self.assertEqual(self.get(port, "/api/summary", headers={"Authorization": "Basic " + bad})[0], 401)
        self.assertEqual(self.get(port, "/api/summary", headers={"Authorization": "Basic " + ok})[0], 200)

    def test_open_to_the_network_needs_a_password(self):
        with self.assertRaises(SystemExit):
            dash.make_server("clean", 0, "0.0.0.0", None)


if __name__ == "__main__":
    unittest.main()
