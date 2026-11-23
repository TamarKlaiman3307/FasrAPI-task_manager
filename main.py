from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import psycopg2
import psycopg2.errors
from security import hash_password, verify_password, create_access_token, decode_access_token
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from fastapi.security import OAuth2PasswordRequestForm
from dotenv import load_dotenv
import os

load_dotenv()

##קיחת הטוקן מהבקשה ואם אין שגיאה 401
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

##פונקצית לשליחת הטוקן לבדיקה והחזרת המשתמש
def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Token does not contain user ID"
        )

    return user_id

app = FastAPI()

# ---------- פרטי חיבור למסד ----------
DB_CONFIG = {
    "host": "localhost",
    "database": "task_manager",
    "user": "postgres",
    "password":os.getenv("DB_PASSWORD"),
    "port": 5432,
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


# ---------- מודלים (מבנה הנתונים שנכנסים) ----------
#הרשמה
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
##תחברות
class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    name: str
    email: str

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "todo"
    priority: str = "medium"
    user_id: Optional[int] = None
    project_id: Optional[int] = None

class TaskUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    user_id: Optional[int] = None
    project_id: Optional[int] = None


# ================= משתמשים =================

@app.post("/register", response_model=UserResponse, status_code=201)
def register(user: UserCreate):
    hashed = hash_password(user.password)
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (user.name, user.email, hashed),
        )
        user_id = cur.fetchone()[0]
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="האימייל כבר רשום")
    finally:
        cur.close()
        conn.close()
    return {"id": user_id, "name": user.name, "email": user.email}
##התחברות בדיקה והוספת טוקן
@app.post("/login")
def login(user: OAuth2PasswordRequestForm = Depends()):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, password_hash FROM users WHERE email = %s",
        (user.username,)

    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    if row is None:
        raise HTTPException(status_code=401, detail="Email or password incorrect")

    user_id = row[0]
    hashed_password = row[1]

    if not verify_password(user.password, hashed_password):
        raise HTTPException(status_code=401, detail="Email or password incorrect")

    access_token = create_access_token({"sub": str(user_id)})

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@app.get("/users")
def get_users(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email FROM users")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "name": r[1], "email": r[2]} for r in rows]


@app.get("/users/{user_id}")
def get_user(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="לא נמצא")
    return {"id": row[0], "name": row[1], "email": row[2]}


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    deleted = cur.rowcount
    cur.close()
    conn.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="לא נמצא")
    return {"message": "נמחק"}


# ================= פרויקטים =================

@app.post("/projects", status_code=201)
def create_project(project: ProjectCreate):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO projects (name, description) VALUES (%s, %s) RETURNING id",
        (project.name, project.description),
    )
    project_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": project_id, "message": "פרויקט נוצר"}


@app.get("/projects")
def get_projects():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description FROM projects")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "name": r[1], "description": r[2]} for r in rows]


@app.get("/projects/{project_id}")
def get_project(project_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description FROM projects WHERE id = %s", (project_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="לא נמצא")
    return {"id": row[0], "name": row[1], "description": row[2]}


# ================= משימות =================

@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tasks (title, description, status, priority, user_id, project_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (task.title, task.description, task.status, task.priority,
         task.user_id, task.project_id),
    )
    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": task_id, "message": "משימה נוצרה"}


@app.get("/tasks")
def get_tasks():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, status, priority, user_id, project_id FROM tasks")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "title": r[1], "status": r[2],
         "priority": r[3], "user_id": r[4], "project_id": r[5]}
        for r in rows
    ]


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, status, priority, user_id, project_id FROM tasks WHERE id = %s", (task_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="לא נמצא")
    return {"id": row[0], "title": row[1], "status": row[2],
            "priority": row[3], "user_id": row[4], "project_id": row[5]}


@app.put("/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE tasks SET status = %s, priority = %s, user_id = %s, project_id = %s
           WHERE id = %s""",
        (task.status, task.priority, task.user_id, task.project_id, task_id),
    )
    conn.commit()
    updated = cur.rowcount
    cur.close()
    conn.close()
    if updated == 0:
        raise HTTPException(status_code=404, detail="לא נמצא")
    return {"message": "עודכן"}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    deleted = cur.rowcount
    cur.close()
    conn.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="לא נמצא")
    return {"message": "נמחק"}

## בדיקת טוקן
@app.get("/protected")
def protected_route(user_id: str = Depends(get_current_user)):
    return {"message": f"Hello user {user_id}"}