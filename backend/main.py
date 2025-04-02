import docker
import os
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from models import Base, Function
from schemas import FunctionCreate, FunctionRead, FunctionExecute
from database import engine, SessionLocal

# Create the database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Serverless Function API")

client = docker.from_env()  # Initialize Docker client

# Dependency to get a DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
async def root():
    return {"message": "Serverless Function API Running!"}

# Create a new function
@app.post("/functions/", response_model=FunctionRead)
def create_function(function: FunctionCreate, db: Session = Depends(get_db)):
    # Check for duplicate function names
    db_function = db.query(Function).filter(Function.name == function.name).first()
    if db_function:
        raise HTTPException(status_code=400, detail="Function already exists")
    new_function = Function(**function.dict())
    db.add(new_function)
    db.commit()
    db.refresh(new_function)
    return new_function

# Retrieve a list of functions
@app.get("/functions/", response_model=list[FunctionRead])
def read_functions(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    functions = db.query(Function).offset(skip).limit(limit).all()
    return functions

# Retrieve a single function by ID
@app.get("/functions/{function_id}", response_model=FunctionRead)
def read_function(function_id: int, db: Session = Depends(get_db)):
    function = db.query(Function).filter(Function.id == function_id).first()
    if function is None:
        raise HTTPException(status_code=404, detail="Function not found")
    return function

# Update a function by ID
@app.put("/functions/{function_id}", response_model=FunctionRead)
def update_function(function_id: int, updated_function: FunctionCreate, db: Session = Depends(get_db)):
    function = db.query(Function).filter(Function.id == function_id).first()
    if not function:
        raise HTTPException(status_code=404, detail="Function not found")
    for key, value in updated_function.dict().items():
        setattr(function, key, value)
    db.commit()
    db.refresh(function)
    return function

# Delete a function by ID
@app.delete("/functions/{function_id}")
def delete_function(function_id: int, db: Session = Depends(get_db)):
    function = db.query(Function).filter(Function.id == function_id).first()
    if not function:
        raise HTTPException(status_code=404, detail="Function not found")
    db.delete(function)
    db.commit()
    return {"detail": "Function deleted"}

@app.post("/execute/{function_id}")
def execute_function(function_id: int, db: Session = Depends(get_db)):
    function = db.query(Function).filter(Function.id == function_id).first()
    if function is None:
        raise HTTPException(status_code=404, detail="Function not found")

    function_code = function.code
    extension = function.language  # Assuming the database stores 'python' or 'javascript'

    unique_id = str(uuid.uuid4())
    function_filename = f"/tmp/{unique_id}.{extension}"

    with open(function_filename, "w") as f:
        f.write(function_code)

    timeout = 5  # Max execution time in seconds

    if extension == "python":
        command = f"timeout {timeout} python /sandbox/function.py"
        image = "function-exec-python"
    elif extension == "javascript":
        command = f"timeout {timeout} node /sandbox/function.js"
        image = "function-exec-node"
    else:
        raise HTTPException(status_code=400, detail="Unsupported language")

    try:
        container = client.containers.run(
            image,
            command,
            volumes={function_filename: {'bind': f"/sandbox/function.{extension}", 'mode': 'ro'}},
            remove=True
        )
        return {"output": container}
    except docker.errors.ContainerError as e:
        raise HTTPException(status_code=500, detail=f"Execution error: {e}")