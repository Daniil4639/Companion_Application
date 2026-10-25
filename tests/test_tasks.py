import os
os.environ["COMPANION_LOAD_DOTENV"] = "0"

import asyncio
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select, func
from backend.app.db import get_db
from backend.app.db.base import Base
from backend.app.db.session import make_engine
from backend.app.main import create_app
from backend.app.models.event_series import EventSeries
from backend.app.dto.tasks import TaskCreate, TaskMove
from backend.app.services.tasks import taskService


class TasksAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.url = "sqlite+aiosqlite:///" + (Path(self.temp.name) / "tasks.db").as_posix()
        self.engine = make_engine(self.url)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.app = create_app()
        async def db():
            async with self.factory() as session:
                yield session
        self.app.dependency_overrides[get_db] = db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False), base_url="http://test")


    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        self.temp.cleanup()


    async def create(self, title="Task", **fields):
        response = await self.client.post("/api/tasks", json={"title": title, **fields})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()


    async def column(self, status="BACKLOG"):
        response = await self.client.get("/api/tasks", params={"status": status})
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual([r["position"] for r in rows], list(range(len(rows))))
        return rows


    async def move(self, task, status, position):
        response = await self.client.patch(f"/api/tasks/{task['id']}/move", json={"status": status, "position": position})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


    async def test_crud_without_dates(self):
        task = await self.create("  My task  ")
        self.assertEqual(task["title"], "My task")
        self.assertEqual(task["priority"], "Medium")
        self.assertIsNone(task["scheduled_date"])
        self.assertIsNone(task["due_date"])
        self.assertIsNone(task["completed_at"])
        url = "/api/tasks/" + task["id"]
        self.assertEqual((await self.client.get(url)).json(), task)
        edited = await self.client.patch(url, json={"title": "Edited", "description": "Notes", "priority": "High", "due_date": "2026-10-30"})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["due_date"], "2026-10-30")
        cleared = await self.client.patch(url, json={"due_date": None, "description": None})
        self.assertIsNone(cleared.json()["due_date"])
        self.assertEqual((await self.client.delete(url)).status_code, 204)
        self.assertEqual((await self.client.get(url)).status_code, 404)


    async def test_order_within_and_between_columns(self):
        a,b,c = [await self.create(x) for x in ["A","B","C"]]
        await self.move(c, "BACKLOG", 0)
        self.assertEqual([x["title"] for x in await self.column()], ["C","A","B"])
        await self.move(c, "BACKLOG", 2)
        self.assertEqual([x["title"] for x in await self.column()], ["A","B","C"])
        d = await self.create("D", status="TODO")
        await self.move(b, "TODO", 0)
        self.assertEqual([x["title"] for x in await self.column()], ["A","C"])
        self.assertEqual([x["title"] for x in await self.column("TODO")], ["B","D"])
        await self.move(a, "IN_PROGRESS", 999)
        self.assertEqual([x["title"] for x in await self.column("IN_PROGRESS")], ["A"])
        self.assertEqual((await self.client.delete("/api/tasks/"+b["id"])).status_code, 204)
        self.assertEqual([x["title"] for x in await self.column("TODO")], ["D"])


    async def test_insert_position_and_patch_move(self):
        await self.create("A")
        b = await self.create("B", position=0)
        self.assertEqual([x["title"] for x in await self.column()], ["B","A"])
        response = await self.client.patch("/api/tasks/"+b["id"], json={"status":"TODO","title":"B2"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([x["title"] for x in await self.column()], ["A"])
        self.assertEqual([x["title"] for x in await self.column("TODO")], ["B2"])


    async def test_completion_transitions(self):
        task = await self.create()
        done = await self.move(task, "DONE", 0)
        self.assertIsNotNone(done["completed_at"])
        edited = (await self.client.patch("/api/tasks/"+task["id"], json={"title":"Still done"})).json()
        self.assertEqual(edited["completed_at"], done["completed_at"])
        again = await self.move(task,"DONE",0)
        self.assertEqual(again["completed_at"], done["completed_at"])
        reopened = await self.move(task,"TODO",0)
        self.assertIsNone(reopened["completed_at"])
        finished = await self.move(task,"DONE",0)
        self.assertGreater(finished["completed_at"], done["completed_at"])
        born_done = await self.create("Already complete",status="DONE")
        self.assertIsNotNone(born_done["completed_at"])


    async def test_filters_and_calendar_independence(self):
        task = await self.create("Both dates",scheduled_date="2026-10-24",due_date="2026-10-24",priority="High")
        await self.create("Due only",due_date="2026-10-25")
        await self.create("No dates")
        rows=(await self.client.get("/api/tasks",params={"date_from":"2026-10-24","date_to":"2026-10-24"})).json()
        self.assertEqual([r["id"] for r in rows],[task["id"]])
        self.assertEqual(len((await self.client.get("/api/tasks",params={"priority":"High"})).json()),1)
        self.assertEqual(len((await self.client.get("/api/tasks",params={"due_date":"2026-10-25"})).json()),1)
        self.assertEqual(len((await self.client.get("/api/tasks",params={"scheduled_date":"2026-10-24"})).json()),1)
        self.assertEqual(len((await self.client.get("/api/tasks",params={"offset":1,"limit":1})).json()),1)
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(EventSeries)),0)
        self.assertEqual((await self.client.get("/api/schedule",params={"range_start":"2026-10-24T00:00:00Z","range_end":"2026-10-26T00:00:00Z"})).json()["occurrences"],[])


    async def test_validation_and_missing(self):
        for fields in [{"title":" "},{"priority":"Urgent"},{"status":"invalid"},{"position":-1},{"position":True},{"due_date":"2026-02-30"},{"scheduled_date":"2026-10-24T00:00:00Z"},{"completed_at":"2026-10-24"}]:
            response=await self.client.post("/api/tasks",json={"title":"Valid",**fields})
            self.assertEqual(response.status_code,422,response.text)
        task=await self.create()
        for fields in [{"title":None},{"status":None},{"priority":None},{"position":None},{"position":1.5},{"updated_at":"now"}]:
            response=await self.client.patch("/api/tasks/"+task["id"],json=fields)
            self.assertEqual(response.status_code,422,response.text)
        for method,path,body in [("get","",None),("delete","",None),("patch","",{"title":"x"}),("patch","/move",{"status":"TODO","position":0})]:
            response=await self.client.request(method,"/api/tasks/"+str(uuid4())+path,json=body)
            self.assertEqual(response.status_code,404,response.text)
        for params in [{"date_from":"2026-11-01","date_to":"2026-10-01"},{"limit":501},{"offset":-1},{"status":"bad"}]:
            self.assertEqual((await self.client.get("/api/tasks",params=params)).status_code,422)


    async def test_failed_reorder_rolls_back(self):
        a=await self.create("A")
        await self.create("B")
        original=taskService._reorder
        async def fail(*args):
            await original(*args)
            raise RuntimeError("simulated failure after flush")
        with patch.object(taskService,"_reorder",side_effect=fail):
            response=await self.client.patch("/api/tasks/"+a["id"]+"/move",json={"status":"DONE","position":0})
            self.assertEqual(response.status_code,500)
        self.assertEqual([r["title"] for r in await self.column()],["A","B"])
        self.assertEqual(await self.column("DONE"),[])
        self.assertIsNone((await self.client.get("/api/tasks/"+a["id"])).json()["completed_at"])


    async def test_concurrent_service_calls_and_restart(self):
        # Direct service use also exercises the future adapter boundary.
        async def create(i):
            async with self.factory() as session:
                return await taskService.create(TaskCreate(title=str(i)),session)
        rows=await asyncio.gather(*(create(i) for i in range(8)))
        async def move(row):
            async with self.factory() as session:
                await taskService.move(row.id,TaskMove(status="DONE",position=0),session)
        await asyncio.gather(*(move(row) for row in rows))
        before=await self.column("DONE")
        self.assertEqual(len(before),8)
        self.assertTrue(all(row["completed_at"] for row in before))
        await self.engine.dispose()
        self.assertEqual(await self.column("DONE"),before)


    async def test_migration_upgrade_and_downgrade(self):
        from alembic import command
        from alembic.config import Config
        from backend.app.config.settings import PROJECT_ROOT
        from alembic.migration import MigrationContext
        from alembic.autogenerate import compare_metadata
        url="sqlite+aiosqlite:///"+(Path(self.temp.name)/"migration.db").as_posix()
        config=Config(str(PROJECT_ROOT/"alembic.ini"))
        config.set_main_option("sqlalchemy.url",url)
        await asyncio.to_thread(command.upgrade,config,"head")
        engine=make_engine(url)
        try:
            async with engine.connect() as connection:
                diff=await connection.run_sync(lambda c:compare_metadata(MigrationContext.configure(c),Base.metadata))
                self.assertEqual(diff,[])
        finally:
            await engine.dispose()
        await asyncio.to_thread(command.downgrade,config,"e3f9b5c02871")
        await asyncio.to_thread(command.upgrade,config,"head")