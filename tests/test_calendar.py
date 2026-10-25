import os
os.environ["COMPANION_LOAD_DOTENV"] = "0"

import asyncio
import tempfile
import unittest
from datetime import datetime, UTC
from pathlib import Path
from uuid import UUID, uuid4
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import IntegrityError
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from backend.app.config.settings import PROJECT_ROOT, Settings
from backend.app.db import get_db
from backend.app.db.base import Base
from backend.app.db.session import make_engine, write_transaction, engine
from backend.app.main import create_app
from backend.app.models import EventSeries, RecurrenceRule, EventException
from backend.app.dto.events import RecurrenceRuleCreate
from backend.app.services.calendar import calendarService
from backend.app.services.recurrence import generate_occurrences
from backend.app.services.errors import InvalidCalendarData, CalendarNotFound


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


PAYLOAD = dict(title="Meeting", start_at="2026-10-22T09:00:00+03:00",
               finish_at="2026-10-22T10:00:00+03:00", timezone="Europe/Moscow")


class CalendarAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = make_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        app = create_app()
        async def db():
            async with self.factory() as session:
                yield session
        app.dependency_overrides[get_db] = db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                       base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()


    async def create(self, **overrides):
        response = await self.client.post("/api/events", json={**PAYLOAD, **overrides})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()


    async def schedule(self, start, end):
        response = await self.client.get("/api/schedule", params={"range_start": start, "range_end": end})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["occurrences"]


    async def action(self, event, action, original="2026-10-22T06:00:00Z", **kwargs):
        return await self.client.post(f"/api/events/{event['id']}/occurrences/{original}/{action}", **kwargs)


    async def test_crud_and_rule_cleanup(self):
        event = await self.create(recurrence_rule={"frequency": "daily", "count": 3})
        self.assertEqual(event["recurrence_rule"]["count"], 3)
        response = await self.client.get("/api/events/" + event["id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recurrence_rule"]["count"], 3)
        response = await self.client.get("/api/events")
        self.assertEqual(len(response.json()), 1)
        response = await self.client.patch("/api/events/" + event["id"], json={"title": " Changed "})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], "Changed")
        self.assertEqual((await self.action(event, "cancel")).status_code, 200)
        self.assertEqual((await self.client.delete("/api/events/" + event["id"])).status_code, 204)
        self.assertEqual((await self.client.get("/api/events/" + event["id"])).status_code, 404)
        async with self.factory() as session:
            for model in (EventSeries, EventException, RecurrenceRule):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 0)


    async def test_timezone_roundtrip(self):
        event = await self.create(recurrence_rule={"frequency": "daily", "count": 2})
        self.assertEqual(dt(event["start_at"]), dt("2026-10-22T06:00:00Z"))
        self.assertIsNotNone(dt(event["start_at"]).tzinfo)
        rows = await self.schedule("2026-10-22T00:00:00+03:00", "2026-10-24T00:00:00+03:00")
        self.assertEqual(len(rows), 2)
        self.assertEqual(dt(rows[0]["start_at"]), dt("2026-10-22T06:00:00Z"))


    async def test_invalid_create(self):
        for change in [
            {"finish_at": PAYLOAD["start_at"]}, {"title": "   "}, {"timezone": "Not/AZone"},
            {"start_at": "2026-10-22T09:00:00"},
            {"start_at": "0001-01-01T00:00:00+14:00"},
            {"recurrence_rule": {"frequency": "daily", "count": 2, "until": "2026-10-24T00:00:00Z"}},
            {"recurrence_rule": {"frequency": "weekly", "by_weekday": ["BAD"]}},
            {"recurrence_rule": {"frequency": "daily", "by_month": [13]}},
            {"recurrence_rule": {"frequency": "monthly", "by_monthday": [0]}},
            {"recurrence_rule": {"frequency": "daily", "until": "2026-10-20T00:00:00Z"}},
            {"recurrence_rule": {"frequency": "daily", "interval": 0}},
            {"recurrence_rule": {"frequency": "weekly", "by_weekday": []}},
        ]:
            with self.subTest(change=change):
                response = await self.client.post("/api/events", json={**PAYLOAD, **change})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.client.get("/api/events")).json(), [])


    async def test_invalid_queries_and_health(self):
        for start, end in [
            ("2026-10-23T00:00:00Z", "2026-10-22T00:00:00Z"),
            ("2026-10-22T00:00:00", "2026-10-23T00:00:00Z"),
            ("2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"),
        ]:
            response = await self.client.get("/api/schedule", params={"range_start": start, "range_end": end})
            self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.client.get("/api/health")).json(), {"status": "ok"})
        self.assertEqual((await self.client.get("/api/events", params={"limit": 0})).status_code, 422)


    async def test_overlap_and_exclusive_end(self):
        await self.create()
        await self.create(recurrence_rule={"frequency": "daily", "count": 2})
        self.assertEqual(len(await self.schedule("2026-10-22T06:30:00Z", "2026-10-22T07:30:00Z")), 2)
        self.assertEqual(await self.schedule("2026-10-22T05:00:00Z", "2026-10-22T06:00:00Z"), [])
        self.assertEqual(await self.schedule("2026-10-22T07:00:00Z", "2026-10-22T08:00:00Z"), [])


    async def test_incoming_and_outgoing_moves(self):
        event = await self.create(recurrence_rule={"frequency": "daily", "count": 3})
        response = await self.action(event, "move", json={"start_at": "2026-10-27T06:00:00Z",
                                                        "finish_at": "2026-10-27T07:00:00Z"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.schedule("2026-10-22T00:00:00Z", "2026-10-23T00:00:00Z"), [])
        rows = await self.schedule("2026-10-27T00:00:00Z", "2026-10-28T00:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertEqual(dt(rows[0]["original_start_at"]), dt("2026-10-22T06:00:00Z"))
        response = await self.action(event, "move", json={"start_at": "2026-10-01T06:00:00Z",
                                                        "finish_at": "2026-10-01T07:00:00Z"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(await self.schedule("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")), 1)
        self.assertEqual(await self.schedule("2026-10-27T00:00:00Z", "2026-10-28T00:00:00Z"), [])


    async def test_single_and_recurring_cancel_restore(self):
        for rule in (None, {"frequency": "daily", "count": 1}):
            event = await self.create(recurrence_rule=rule)
            for _ in range(2):
                self.assertEqual((await self.action(event, "cancel")).status_code, 200)
            self.assertEqual(await self.schedule("2026-10-22T00:00:00Z", "2026-10-23T00:00:00Z"), [])
            self.assertEqual((await self.action(event, "restore")).status_code, 204)
            self.assertEqual(len(await self.schedule("2026-10-22T00:00:00Z", "2026-10-23T00:00:00Z")), 1)
            await self.client.delete("/api/events/" + event["id"])


    async def test_cancelled_move_restores_and_cancel_after_move(self):
        event = await self.create()
        await self.action(event, "cancel")
        self.assertEqual((await self.action(event, "move", json={"start_at": "2026-10-25T06:00:00Z",
                              "finish_at": "2026-10-25T07:00:00Z"})).status_code, 200)
        self.assertEqual(len(await self.schedule("2026-10-25T00:00:00Z", "2026-10-26T00:00:00Z")), 1)
        await self.action(event, "cancel")
        self.assertEqual(await self.schedule("2026-10-25T00:00:00Z", "2026-10-26T00:00:00Z"), [])
        async with self.factory() as session:
            exception = await session.scalar(select(EventException))
            self.assertIsNotNone(exception.created_at.tzinfo)
            self.assertGreaterEqual(exception.updated_at, exception.created_at)


    async def test_membership_and_offset_identity(self):
        event = await self.create(recurrence_rule={"frequency": "daily", "count": 1})
        self.assertEqual((await self.action(event, "cancel", "2026-10-23T06:00:00Z")).status_code, 404)
        self.assertEqual((await self.action({"id": str(uuid4())}, "cancel")).status_code, 404)
        self.assertEqual((await self.action(event, "cancel", "2026-10-22T06:00:00")).status_code, 422)
        self.assertEqual((await self.action(event, "cancel", "2026-10-22T09:00:00+03:00")).status_code, 200)
        self.assertEqual((await self.action(event, "cancel")).status_code, 200)
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(EventException)), 1)


    async def test_update_requires_explicit_reset(self):
        event = await self.create(recurrence_rule={"frequency": "daily", "count": 3})
        await self.action(event, "cancel")
        response = await self.client.patch("/api/events/" + event["id"], json={"title": "Renamed"})
        self.assertEqual(response.status_code, 200)
        change = {"start_at": "2026-10-22T08:00:00Z", "finish_at": "2026-10-22T09:00:00Z"}
        response = await self.client.patch("/api/events/" + event["id"], json=change)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(await self.schedule("2026-10-22T00:00:00Z", "2026-10-23T00:00:00Z"), [])
        response = await self.client.patch("/api/events/" + event["id"],
                                           params={"reset_exceptions": "true"}, json=change)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(await self.schedule("2026-10-22T00:00:00Z", "2026-10-23T00:00:00Z")), 1)


    async def test_clear_recurrence_and_invalid_patch(self):
        event = await self.create(recurrence_rule={"frequency": "daily", "count": 3})
        for change in ({"title": None}, {"title": " "}, {"finish_at": "2026-10-20T00:00:00Z"}):
            response = await self.client.patch("/api/events/" + event["id"], json=change)
            self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.patch("/api/events/" + event["id"], json={"recurrence_rule": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["recurrence_rule_id"])
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(RecurrenceRule)), 0)


    async def test_direct_service_validation_and_rollback(self):
        async with self.factory() as session:
            with self.assertRaises(InvalidCalendarData):
                await calendarService.create_event(title=" ", start_at=dt(PAYLOAD["start_at"]),
                    finish_at=dt(PAYLOAD["finish_at"]), timezone="Europe/Moscow", description=None,
                    recurrence_rule=None, session=session)
            with self.assertRaises(RuntimeError):
                async with write_transaction(session):
                    await calendarService.create_event(title="Rollback", start_at=dt(PAYLOAD["start_at"]),
                        finish_at=dt(PAYLOAD["finish_at"]), timezone="Europe/Moscow", description=None,
                        recurrence_rule=None, session=session)
                    raise RuntimeError("rollback")
        self.assertEqual((await self.client.get("/api/events")).json(), [])


    async def test_database_constraints(self):
        event = await self.create()
        async with self.factory() as session:
            with self.assertRaises(IntegrityError):
                await session.execute(text("INSERT INTO event_exceptions "
                    "(id,event_series_id,original_start_at,status,start_at,finish_at) "
                    "VALUES (:id,:parent,'2026-10-22 06:00:00','MODIFIED',NULL,NULL)"),
                    {"id": uuid4().hex, "parent": UUID(event["id"]).hex})
            await session.rollback()


    async def test_missing_schema_health(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        self.assertEqual((await self.client.get("/api/health")).status_code, 503)


class RecurrenceTests(unittest.TestCase):
    def expand(self, start, rule, lower, upper, zone="UTC"):
        return generate_occurrences(dt(start), RecurrenceRuleCreate(**rule), dt(lower), dt(upper), zone)


    def test_daily_weekly_monthly_yearly(self):
        cases = [
            ({"frequency": "daily", "interval": 2, "count": 3}, "2026-01-01T09:00:00Z", ["2026-01-01", "2026-01-03", "2026-01-05"]),
            ({"frequency": "weekly", "by_weekday": ["MO"], "count": 2}, "2026-01-01T09:00:00Z", ["2026-01-05", "2026-01-12"]),
            ({"frequency": "monthly", "count": 3}, "2026-01-31T09:00:00Z", ["2026-01-31", "2026-03-31", "2026-05-31"]),
            ({"frequency": "yearly", "count": 2}, "2024-02-29T09:00:00Z", ["2024-02-29", "2028-02-29"]),
        ]
        for rule, start, expected in cases:
            with self.subTest(rule=rule):
                rows = self.expand(start, rule, start, "2029-01-01T00:00:00Z")
                self.assertEqual([r.date().isoformat() for r in rows], expected)


    def test_until_and_filters(self):
        rows = self.expand("2026-01-01T09:00:00Z",
                           {"frequency": "daily", "until": "2026-01-03T09:00:00Z"},
                           "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
        self.assertEqual(len(rows), 3)
        rows = self.expand("2026-01-01T09:00:00Z",
                           {"frequency": "monthly", "by_month": [2], "by_monthday": [-1], "count": 2},
                           "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z")
        self.assertEqual([r.date().isoformat() for r in rows], ["2026-02-28", "2027-02-28"])


    def test_dst_preserves_wall_clock(self):
        rows = self.expand("2026-03-28T09:00:00+01:00", {"frequency": "daily", "count": 3},
                           "2026-03-28T00:00:00Z", "2026-04-01T00:00:00Z", "Europe/Berlin")
        self.assertEqual([r.hour for r in rows], [8, 7, 7])


    def test_dst_gap_skips_and_count_counts_real_instances(self):
        rows = self.expand("2026-03-28T02:30:00+01:00", {"frequency": "daily", "count": 3},
                           "2026-03-28T00:00:00Z", "2026-04-02T00:00:00Z", "Europe/Berlin")
        self.assertEqual([r.day for r in rows], [28, 30, 31])


    def test_dst_fold_first_and_explicit_start(self):
        rows = self.expand("2026-10-24T02:30:00+02:00", {"frequency": "daily", "count": 3},
                           "2026-10-24T00:00:00Z", "2026-10-28T00:00:00Z", "Europe/Berlin")
        self.assertEqual([r.hour for r in rows], [0, 0, 1])
        rows = self.expand("2026-10-25T02:30:00+01:00", {"frequency": "daily", "count": 1},
                           "2026-10-25T00:00:00Z", "2026-10-26T00:00:00Z", "Europe/Berlin")
        self.assertEqual(rows, [dt("2026-10-25T01:30:00Z")])


    def test_microseconds_and_empty_rule(self):
        rows = self.expand("2026-01-01T09:00:00.123456Z", {"frequency": "daily", "count": 1},
                           "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        self.assertEqual(rows[0].microsecond, 123456)
        rows = self.expand("2026-01-01T09:00:00Z", {"frequency": "monthly", "by_month": [2], "by_monthday": [30]},
                           "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
        self.assertEqual(rows, [])


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "calendar.db"
        self.url = "sqlite+aiosqlite:///" + self.path.as_posix()
        self.config = Config(str(PROJECT_ROOT / "alembic.ini"))
        self.config.set_main_option("sqlalchemy.url", self.url)


    def tearDown(self):
        self.temp.cleanup()


    def sql(self, operation):
        async def run():
            engine = make_engine(self.url)
            try:
                async with engine.begin() as conn:
                    return await conn.run_sync(operation)
            finally:
                await engine.dispose()
        return asyncio.run(run())


    def seed_legacy(self):
        command.upgrade(self.config, "c1daa961f302")
        self.sql(lambda conn: conn.execute(text(
            "INSERT INTO event_series (id,title,start_at,finish_at,timezone,created_at,updated_at) "
            "VALUES ('11111111111111111111111111111111','Legacy','2026-10-22 09:00:00',"
            "'2026-10-22 10:00:00','Europe/Moscow','2026-10-21 12:00:00','2026-10-21 12:00:00')")))


    def test_clean_upgrade_metadata_and_downgrade(self):
        command.upgrade(self.config, "head")
        differences = self.sql(lambda conn: compare_metadata(MigrationContext.configure(conn,
            opts={"compare_server_default": True}), Base.metadata))
        self.assertEqual(differences, [])
        command.downgrade(self.config, "base")
        self.assertEqual(self.sql(lambda conn: conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event_series'")).fetchall()), [])


    def test_legacy_refuses_guess_and_rolls_back(self):
        self.seed_legacy()
        with self.assertRaisesRegex(RuntimeError, "unknown timezone"):
            command.upgrade(self.config, "head")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT version_num FROM alembic_version"))),
                         "c1daa961f302")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT start_at FROM event_series"))),
                         "2026-10-22 09:00:00")


    def test_legacy_explicit_conversion_and_downgrade_guard(self):
        self.seed_legacy()
        self.config.cmd_opts = SimpleNamespace(x=["legacy_time_policy=event_timezone",
                                                  "legacy_audit_timezone=Europe/Moscow"])
        command.upgrade(self.config, "head")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT start_at FROM event_series"))),
                         "2026-10-22 06:00:00.000000")
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            command.downgrade(self.config, "c1daa961f302")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT version_num FROM alembic_version"))),
                         ScriptDirectory.from_config(self.config).get_current_head())


    def test_settings_paths_are_stable(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///relative.db"}):
            settings = Settings()
        self.assertEqual(settings.database_url, "sqlite+aiosqlite:///" + (PROJECT_ROOT / "relative.db").as_posix())


    def test_populated_rules_and_exceptions_keep_links(self):
        self.seed_legacy()
        def seed(conn):
            conn.execute(text("INSERT INTO recurrence_rules (id,frequency,interval,until) VALUES "
                              "('22222222222222222222222222222222','DAILY',1,'2026-10-24 09:00:00')"))
            conn.execute(text("UPDATE event_series SET recurrence_rule_id='22222222222222222222222222222222'"))
            conn.execute(text("INSERT INTO event_exceptions "
                "(id,event_series_id,original_start_at,status,start_at,finish_at,created_at,updated_at) VALUES "
                "('33333333333333333333333333333333','11111111111111111111111111111111',"
                "'2026-10-22 09:00:00','MODIFIED','2026-10-27 11:00:00','2026-10-27 12:00:00',"
                "'2026-10-21 12:00:00','2026-10-21 12:00:00')"))
        self.sql(seed)
        self.config.cmd_opts = SimpleNamespace(x=["legacy_time_policy=event_timezone", "legacy_audit_timezone=Europe/Moscow"])
        command.upgrade(self.config, "head")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT until FROM recurrence_rules"))),
                         "2026-10-24 06:00:00.000000")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT start_at FROM event_exceptions"))),
                         "2026-10-27 08:00:00.000000")
        self.assertEqual(self.sql(lambda conn: conn.execute(text("PRAGMA foreign_key_check")).fetchall()), [])


    def test_migration_failure_rolls_back_converted_values(self):
        self.seed_legacy()
        self.sql(lambda conn: conn.execute(text("UPDATE event_series SET title='   '")))
        self.config.cmd_opts = SimpleNamespace(x=["legacy_time_policy=event_timezone", "legacy_audit_timezone=Europe/Moscow"])
        with self.assertRaises(IntegrityError):
            command.upgrade(self.config, "head")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT start_at FROM event_series"))),
                         "2026-10-22 09:00:00")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT version_num FROM alembic_version"))),
                         "c1daa961f302")


    def test_legacy_utc_policy_does_not_shift_dates(self):
        self.seed_legacy()
        self.config.cmd_opts = SimpleNamespace(x=["legacy_time_policy=utc"])
        command.upgrade(self.config, "head")
        self.assertEqual(self.sql(lambda conn: conn.scalar(text("SELECT start_at FROM event_series"))),
                         "2026-10-22 09:00:00.000000")


    def test_ambiguous_legacy_datetime_is_rejected(self):
        self.seed_legacy()
        self.sql(lambda conn: conn.execute(text(
            "UPDATE event_series SET timezone='Europe/Berlin',start_at='2026-10-25 02:30:00',finish_at='2026-10-25 03:30:00'")))
        self.config.cmd_opts = SimpleNamespace(x=["legacy_time_policy=event_timezone", "legacy_audit_timezone=Europe/Moscow"])
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            command.upgrade(self.config, "head")


class PersistenceAndConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.url = "sqlite+aiosqlite:///" + (Path(self.temp.name) / "calendar.db").as_posix()
        self.engine = make_engine(self.url)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)


    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()


    async def test_lifespan_migrates_and_restart_preserves_events(self):
        import backend.app.main as application
        app = create_app()
        async def db():
            async with self.factory() as session:
                yield session
        app.dependency_overrides[get_db] = db
        with patch.object(application, "engine", self.engine), patch.object(application.settings, "database_url", self.url):
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post("/api/events", json=PAYLOAD)
                    self.assertEqual(response.status_code, 201)
                    event_id = response.json()["id"]
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    self.assertEqual((await client.get("/api/health")).status_code, 200)
                    self.assertEqual((await client.get("/api/events/" + event_id)).status_code, 200)


    async def test_concurrent_moves_use_one_exception(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.factory() as session:
            async with write_transaction(session):
                event = await calendarService.create_event(title="Concurrent", description=None,
                    start_at=dt(PAYLOAD["start_at"]), finish_at=dt(PAYLOAD["finish_at"]),
                    timezone="Europe/Moscow", recurrence_rule=None, session=session)
                event_id = event.id
        async def move(day):
            async with self.factory() as session:
                async with write_transaction(session):
                    await calendarService.move_occurrence(event_id, dt(PAYLOAD["start_at"]),
                        datetime(2026, 10, day, 6, tzinfo=UTC), datetime(2026, 10, day, 7, tzinfo=UTC), session)
                    await asyncio.sleep(0.03)
        await asyncio.gather(move(25), move(26))
        async with self.factory() as session:
            exceptions = (await session.execute(select(EventException))).scalars().all()
            self.assertEqual(len(exceptions), 1)
            self.assertIn(exceptions[0].start_at.day, (25, 26))


    async def test_lifespan_fails_on_migration_error(self):
        import backend.app.main as application
        from unittest.mock import Mock
        app = create_app()
        with patch.object(application, "engine", self.engine), patch.object(application, "migrate", Mock(side_effect=RuntimeError("bad schema"))):
            with self.assertRaisesRegex(RuntimeError, "bad schema"):
                async with app.router.lifespan_context(app):
                    self.fail("Application started despite failed migration")


if __name__ == "__main__":
    unittest.main()