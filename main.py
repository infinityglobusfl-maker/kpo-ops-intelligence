from datetime import date, datetime, timedelta
import os
import secrets
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from demo_data import build_demo_data


load_dotenv()

app = FastAPI(title="KPO Ops Intelligence", version="1.0.0")
@app.get("/health")
def health():
    return {"status": "ok"}
URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_KEY")
HEADERS = {
    "apikey": KEY or "",
    "Authorization": f"Bearer {KEY}" if KEY else "",
    "Content-Type": "application/json",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = httpx.Client(headers=HEADERS, timeout=20.0, trust_env=False)
DEMO_DATA = build_demo_data()
DEMO_MANAGER_EMAIL = os.getenv("DEMO_MANAGER_EMAIL", "admin@kpoops.local")
DEMO_MANAGER_PASSWORD = os.getenv("DEMO_MANAGER_PASSWORD", "demo1234")
DEMO_MANAGER_TOKEN = os.getenv("DEMO_MANAGER_TOKEN", "demo-manager-token")

if os.path.isdir(WEB_DIR):
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


class LoginRequest(BaseModel):
    email: str
    password: str


class TaskCreateRequest(BaseModel):
    client_id: str
    staff_id: str
    reviewer_id: str
    title: str
    status: str
    jurisdiction: str
    due_date: str


class TeamsActionRequest(BaseModel):
    update_token: str
    status: str


def ensure_env() -> None:
    if not URL or not KEY:
        raise HTTPException(status_code=500, detail="Missing Supabase environment variables")


def use_demo_fallback() -> bool:
    return os.getenv("USE_DEMO_FALLBACK", "true").lower() == "true"


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1]


def verify_token(authorization: str | None) -> dict[str, Any]:
    token = parse_bearer_token(authorization)
    if token == DEMO_MANAGER_TOKEN:
        return {
            "email": DEMO_MANAGER_EMAIL,
            "role": "manager",
            "source": "demo",
        }

    ensure_env()
    response = client.get(
        f"{URL}/auth/v1/user",
        headers={"apikey": KEY, "Authorization": f"Bearer {token}"},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = response.json()
    return {
        "email": user.get("email"),
        "id": user.get("id"),
        "role": "manager",
        "source": "supabase",
    }


def require_manager(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return verify_token(authorization)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def reviewer_flag_for(task: dict[str, Any]) -> bool:
    updated_at = parse_iso_datetime(task.get("updated_at"))
    if not updated_at:
        return bool(task.get("reviewer_flag"))
    if updated_at.tzinfo is not None:
        updated_at = updated_at.replace(tzinfo=None)
    return task.get("status") == "with_reviewer" and updated_at <= datetime.now() - timedelta(hours=24)


def fetch_staff_map() -> dict[str, dict[str, Any]]:
    response = client.get(
        f"{URL}/rest/v1/staff",
        params={"select": "id,name,role"},
    )
    response.raise_for_status()
    return {member["id"]: member for member in response.json()}


def demo_tasks() -> list[dict[str, Any]]:
    today = str(date.today())
    tasks = []
    for task in DEMO_DATA["tasks"]:
        if task["status"] == "done":
            continue
        if task["due_date"] <= today:
            tasks.append({**task, "reviewer_flag": reviewer_flag_for(task)})
    tasks.sort(key=lambda item: item["due_date"])
    return tasks


def demo_clients_utilisation() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for task in DEMO_DATA["tasks"]:
        if task["status"] != "done":
            counts[task["client_id"]] = counts.get(task["client_id"], 0) + 1

    result = []
    for client_row in DEMO_DATA["clients"]:
        active_task_count = counts.get(client_row["id"], 0)
        allocated_fte = float(client_row.get("allocated_fte") or 0)
        health_status = client_row.get("health_status") or "good"
        if active_task_count >= 5 and allocated_fte <= 1:
            health_status = "over"
        elif active_task_count <= 1 and allocated_fte >= 1.5:
            health_status = "low"

        result.append(
            {
                **client_row,
                "active_task_count": active_task_count,
                "health_status": health_status,
            }
        )
    return result


def demo_deadlines() -> list[dict[str, Any]]:
    today = str(date.today())
    future = str(date.today() + timedelta(days=30))
    deadlines = [
        deadline
        for deadline in DEMO_DATA["deadlines"]
        if today <= deadline["due_date"] <= future
    ]
    deadlines.sort(key=lambda item: item["due_date"])
    return deadlines


def demo_alerts() -> list[dict[str, Any]]:
    return [task for task in demo_tasks() if task["reviewer_flag"]]


def remote_tasks_today() -> list[dict[str, Any]]:
    ensure_env()
    today = str(date.today())
    staff_map = fetch_staff_map()
    response = client.get(
        f"{URL}/rest/v1/tasks",
        params={
            "select": "*,clients(name,country)",
            "due_date": f"lte.{today}",
            "status": "neq.done",
            "order": "due_date",
        },
    )
    response.raise_for_status()
    rows = response.json()
    if not rows and use_demo_fallback():
        return demo_tasks()

    enriched = []
    for task in rows:
        enriched.append(
            {
                **task,
                "staff": staff_map.get(task.get("staff_id")),
                "reviewer": staff_map.get(task.get("reviewer_id")),
                "reviewer_flag": reviewer_flag_for(task),
            }
        )
    return enriched


def remote_clients_utilisation() -> list[dict[str, Any]]:
    ensure_env()
    clients_response = client.get(f"{URL}/rest/v1/clients", params={"select": "*"})
    tasks_response = client.get(
        f"{URL}/rest/v1/tasks",
        params={"select": "client_id,status", "status": "neq.done"},
    )
    clients_response.raise_for_status()
    tasks_response.raise_for_status()

    clients_rows = clients_response.json()
    tasks_rows = tasks_response.json()
    if not clients_rows and use_demo_fallback():
        return demo_clients_utilisation()

    counts: dict[str, int] = {}
    for task in tasks_rows:
        client_id = task.get("client_id")
        if client_id:
            counts[client_id] = counts.get(client_id, 0) + 1

    enriched = []
    for client_row in clients_rows:
        active_task_count = counts.get(client_row["id"], 0)
        allocated_fte = float(client_row.get("allocated_fte") or 0)
        health_status = client_row.get("health_status") or "good"
        if active_task_count >= 5 and allocated_fte <= 1:
            health_status = "over"
        elif active_task_count <= 1 and allocated_fte >= 1.5:
            health_status = "low"
        enriched.append(
            {
                **client_row,
                "active_task_count": active_task_count,
                "health_status": health_status,
            }
        )
    return enriched


def remote_deadlines() -> list[dict[str, Any]]:
    ensure_env()
    today = str(date.today())
    future = str(date.today() + timedelta(days=30))
    response = client.get(
        f"{URL}/rest/v1/deadlines",
        params={
            "select": "*,clients(name)",
            "due_date": f"gte.{today}",
            "and": f"(due_date.lte.{future})",
            "order": "due_date",
        },
    )
    response.raise_for_status()
    rows = response.json()
    if not rows and use_demo_fallback():
        return demo_deadlines()
    return rows


def create_demo_task(payload: TaskCreateRequest) -> dict[str, Any]:
    staff_map = {member["id"]: member for member in DEMO_DATA["staff"]}
    clients_map = {row["id"]: row for row in DEMO_DATA["clients"]}
    new_task = {
        "id": f"task-{len(DEMO_DATA['tasks']) + 1}",
        "client_id": payload.client_id,
        "staff_id": payload.staff_id,
        "reviewer_id": payload.reviewer_id,
        "title": payload.title,
        "status": payload.status,
        "jurisdiction": payload.jurisdiction,
        "due_date": payload.due_date,
        "update_token": secrets.token_urlsafe(12),
        "updated_at": datetime.now().isoformat(),
        "reviewer_flag": payload.status == "with_reviewer",
        "clients": {
            "name": clients_map[payload.client_id]["name"],
            "country": clients_map[payload.client_id]["country"],
        },
        "staff": staff_map[payload.staff_id],
        "reviewer": staff_map[payload.reviewer_id],
    }
    DEMO_DATA["tasks"].append(new_task)
    return new_task


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "demo_fallback": use_demo_fallback()}


@app.post("/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    if payload.email == DEMO_MANAGER_EMAIL and payload.password == DEMO_MANAGER_PASSWORD:
        return {
            "access_token": DEMO_MANAGER_TOKEN,
            "token_type": "bearer",
            "user": {"email": DEMO_MANAGER_EMAIL, "role": "manager", "source": "demo"},
        }

    ensure_env()
    response = client.post(
        f"{URL}/auth/v1/token",
        params={"grant_type": "password"},
        json={"email": payload.email, "password": payload.password},
        headers={"apikey": KEY, "Content-Type": "application/json"},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    session = response.json()
    return {
        "access_token": session["access_token"],
        "refresh_token": session.get("refresh_token"),
        "token_type": session.get("token_type", "bearer"),
        "user": session.get("user"),
    }


@app.get("/auth/me")
def auth_me(current_user: dict[str, Any] = Depends(require_manager)) -> dict[str, Any]:
    return current_user


@app.get("/reference/options")
def reference_options(current_user: dict[str, Any] = Depends(require_manager)) -> dict[str, Any]:
    if use_demo_fallback():
        return {
            "staff": DEMO_DATA["staff"],
            "clients": DEMO_DATA["clients"],
        }

    ensure_env()
    staff_response = client.get(
        f"{URL}/rest/v1/staff",
        params={"select": "id,name,role,is_active", "is_active": "eq.true", "order": "name"},
    )
    clients_response = client.get(
        f"{URL}/rest/v1/clients",
        params={"select": "id,name,country,software", "order": "name"},
    )
    staff_response.raise_for_status()
    clients_response.raise_for_status()
    return {"staff": staff_response.json(), "clients": clients_response.json()}


@app.get("/tasks/today")
def get_today_tasks(current_user: dict[str, Any] = Depends(require_manager)) -> list[dict[str, Any]]:
    return remote_tasks_today()


@app.get("/clients/utilisation")
def get_utilisation(current_user: dict[str, Any] = Depends(require_manager)) -> list[dict[str, Any]]:
    return remote_clients_utilisation()


@app.get("/deadlines/upcoming")
def get_deadlines(current_user: dict[str, Any] = Depends(require_manager)) -> list[dict[str, Any]]:
    return remote_deadlines()


@app.get("/ops/alerts")
def get_alerts(current_user: dict[str, Any] = Depends(require_manager)) -> dict[str, Any]:
    tasks = demo_alerts() if use_demo_fallback() else [task for task in remote_tasks_today() if task["reviewer_flag"]]
    return {
        "review_bottlenecks": tasks,
        "count": len(tasks),
    }


@app.post("/tasks")
def create_task(
    payload: TaskCreateRequest, current_user: dict[str, Any] = Depends(require_manager)
) -> dict[str, Any]:
    valid_statuses = {"not_started", "on_track", "at_risk", "with_reviewer", "done", "delayed"}
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid task status")

    if use_demo_fallback():
        return create_demo_task(payload)

    ensure_env()
    response = client.post(
        f"{URL}/rest/v1/tasks",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={
            "client_id": payload.client_id,
            "staff_id": payload.staff_id,
            "reviewer_id": payload.reviewer_id,
            "title": payload.title,
            "status": payload.status,
            "jurisdiction": payload.jurisdiction,
            "due_date": payload.due_date,
            "update_token": secrets.token_urlsafe(12),
            "updated_at": datetime.now().isoformat(),
            "reviewer_flag": payload.status == "with_reviewer",
        },
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    rows = response.json()
    return rows[0] if rows else {"created": True}


@app.patch("/task/status/{token}/{new_status}")
def update_status(token: str, new_status: str) -> dict[str, Any]:
    valid = {"on_track", "at_risk", "done", "delayed", "with_reviewer", "not_started"}
    if new_status not in valid:
        raise HTTPException(status_code=400, detail="Invalid status")

    if use_demo_fallback():
        for task in DEMO_DATA["tasks"]:
            if task["update_token"] == token:
                task["status"] = new_status
                task["updated_at"] = datetime.now().isoformat()
                task["reviewer_flag"] = reviewer_flag_for(task)
                return {"updated": [task], "source": "demo"}
        return {"updated": [], "source": "demo"}

    ensure_env()
    response = client.patch(
        f"{URL}/rest/v1/tasks",
        headers={**HEADERS, "Prefer": "return=representation"},
        params={"update_token": f"eq.{token}"},
        json={"status": new_status, "updated_at": datetime.now().isoformat()},
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return {"updated": response.json()}


@app.get("/teams/card/{token}")
def teams_card(token: str) -> dict[str, Any]:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": "KPO Ops Task Update"},
            {"type": "TextBlock", "wrap": True, "text": "Update the task status in one tap."},
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "On Track",
                "data": {"update_token": token, "status": "on_track"},
            },
            {
                "type": "Action.Submit",
                "title": "With Reviewer",
                "data": {"update_token": token, "status": "with_reviewer"},
            },
            {
                "type": "Action.Submit",
                "title": "Done",
                "data": {"update_token": token, "status": "done"},
            },
        ],
    }


@app.post("/teams/action")
def teams_action(payload: TeamsActionRequest) -> dict[str, Any]:
    return update_status(payload.update_token, payload.status)
