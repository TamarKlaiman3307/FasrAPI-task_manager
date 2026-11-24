from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from db import get_db
from models import User, Project, Task
from security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token
)

app = FastAPI()

##קיחת הטוקן מהבקשה ואם אין שגיאה 401
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# ---------- Authentication ----------
##פונקצית לשליחת הטוקן לבדיקה והחזרת המשתמש
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(status_code=401, detail="Token does not contain user ID")

    try:
        user_id = int(user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID")

    current_user = db.query(User).filter(User.id == user_id).first()

    if current_user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return current_user


##בודק הרשאות
def require_roles(*roles: str):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail="אין לך הרשאה לבצע פעולה זו"
            )
        return current_user

    return role_checker


# ---------- Schemas ----------

class UserCreate(BaseModel):
    name: str
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


# ================= Users =================

@app.post("/register", response_model=UserResponse, status_code=201)
def register(user: UserCreate, db: Session = Depends(get_db)):
    hashed = hash_password(user.password)

    new_user = User(
        name=user.name,
        email=user.email,
        password_hash=hashed,
        role="user"
    )

    db.add(new_user)

    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="האימייל כבר רשום")

    return new_user


@app.post("/login")
def login(
    user: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    db_user = db.query(User).filter(User.email == user.username).first()

    if db_user is None:
        raise HTTPException(status_code=401, detail="Email or password incorrect")

    if not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password incorrect")

    access_token = create_access_token({"sub": str(db_user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@app.get("/users")
def get_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role in ["admin", "secretary"]:
        users = db.query(User).all()
    else:
        users = [current_user]

    return [
        {"id": user.id, "name": user.name, "email": user.email}
        for user in users
    ]


@app.get("/users/{user_id}")
def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role == "user" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="אין לך הרשאה לצפות במשתמש זה")

    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(status_code=404, detail="לא נמצא")

    return {"id": user.id, "name": user.name, "email": user.email}


@app.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(status_code=404, detail="לא נמצא")

    db.delete(user)
    db.commit()

    return {"message": "נמחק"}


# ================= Projects =================

@app.post("/projects", status_code=201)
def create_project(
    project: ProjectCreate,
    current_user: User = Depends(require_roles("admin", "user")),
    db: Session = Depends(get_db)
):
    new_project = Project(
        name=project.name,
        description=project.description,
        owner_id=current_user.id
    )

    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    return {"id": new_project.id, "message": "פרויקט נוצר"}


@app.get("/projects")
def get_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Project)

    if current_user.role == "user":
        query = query.filter(Project.owner_id == current_user.id)

    projects = query.all()

    return [
        {
            "id": project.id,
            "name": project.name,
            "description": project.description
        }
        for project in projects
    ]


@app.get("/projects/{project_id}")
def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(Project).filter(Project.id == project_id).first()

    if project is None:
        raise HTTPException(status_code=404, detail="לא נמצא")

    if current_user.role == "user" and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="אין לך הרשאה לצפות בפרויקט זה")

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description
    }


# ================= Tasks =================

@app.post("/tasks", status_code=201)
def create_task(
    task: TaskCreate,
    current_user: User = Depends(require_roles("admin", "user")),
    db: Session = Depends(get_db)
):
    if current_user.role == "user":
        if task.user_id is not None and task.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="אין לך הרשאה לשייך משימה למשתמש אחר")

        if task.project_id is not None:
            project = db.query(Project).filter(
                Project.id == task.project_id,
                Project.owner_id == current_user.id
            ).first()

            if project is None:
                raise HTTPException(status_code=403, detail="אין לך הרשאה להשתמש בפרויקט זה")

        task_user_id = current_user.id
    else:
        task_user_id = task.user_id

    new_task = Task(
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        user_id=task_user_id,
        project_id=task.project_id
    )

    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    return {"id": new_task.id, "message": "משימה נוצרה"}


@app.get("/tasks")
def get_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Task)

    if current_user.role == "user":
        query = query.filter(Task.user_id == current_user.id)

    tasks = query.all()

    return [
        {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "user_id": task.user_id,
            "project_id": task.project_id
        }
        for task in tasks
    ]


@app.get("/tasks/{task_id}")
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if task is None:
        raise HTTPException(status_code=404, detail="לא נמצא")

    if current_user.role == "user" and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="אין לך הרשאה לצפות במשימה זו")

    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "user_id": task.user_id,
        "project_id": task.project_id
    }


@app.put("/tasks/{task_id}")
def update_task(
    task_id: int,
    task: TaskUpdate,
    current_user: User = Depends(require_roles("admin", "user")),
    db: Session = Depends(get_db)
):
    db_task = db.query(Task).filter(Task.id == task_id).first()

    if db_task is None:
        raise HTTPException(status_code=404, detail="לא נמצא")

    if current_user.role == "user":
        if db_task.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="אין לך הרשאה לעדכן משימה זו")

        if task.user_id is not None and task.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="אין לך הרשאה להעביר משימה למשתמש אחר")

        if task.project_id is not None:
            project = db.query(Project).filter(
                Project.id == task.project_id,
                Project.owner_id == current_user.id
            ).first()

            if project is None:
                raise HTTPException(status_code=403, detail="אין לך הרשאה להשתמש בפרויקט זה")

    update_data = task.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_task, key, value)

    db.commit()

    return {"message": "עודכן"}


@app.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    current_user: User = Depends(require_roles("admin", "user")),
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if task is None:
        raise HTTPException(status_code=404, detail="לא נמצא")

    if current_user.role == "user" and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="אין לך הרשאה למחוק משימה זו")

    db.delete(task)
    db.commit()

    return {"message": "נמחק"}


# ================= Protected =================

@app.get("/protected")
def protected_route(current_user: User = Depends(get_current_user)):
    return {"message": f"Hello user {current_user.id}"}