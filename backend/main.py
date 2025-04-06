from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from models import Base, Function  # Ensure Base is defined in models
from database import engine, SessionLocal
from schemas import FunctionRead, FunctionCreate  # Your Pydantic schemas
from pydantic import BaseModel
from typing import Optional
import uuid
import os
import tempfile
import docker
import shutil
import io
import tarfile

# Create DB tables if not already created
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Serverless Function API")

# Initialize Docker client
client = docker.from_env()

# Global container pool dictionary.
# Keys: "docker_python", "docker_javascript", "gvisor_python", "gvisor_javascript"
container_pools = {}

# Dependency to get a DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Response model for execution result
class ExecutionResult(BaseModel):
    output: str
    error: Optional[str] = None

# --- Helper Functions ---

def create_container_pool(language: str, count: int, runtime: Optional[str] = None):
    """
    Creates a pool of pre-warmed containers for the specified language.
    Optionally, a runtime can be specified (e.g., "runsc" for gVisor).
    """
    pool = []
    if language == "python":
        image = "function-exec-python"
    elif language == "javascript":
        image = "function-exec-node"
    else:
        raise Exception("Unsupported language for pool creation.")
    
    # Use runtime value in container name to differentiate pools.
    pool_type = runtime if runtime else "docker"
    
    for i in range(count):
        container_name = f"{language}_{pool_type}_pool_{i}"
        try:
            container = client.containers.run(
                image=image,
                name=container_name,
                command="tail -f /dev/null",  # Keeps container running
                detach=True,
                tty=True,
                auto_remove=False,
                runtime=runtime  # If runtime is None, Docker uses default (runc)
            )
        except docker.errors.APIError:
            container = client.containers.get(container_name)
        pool.append(container)
    return pool

def create_tar_for_file(file_path: str, arcname: str) -> bytes:
    """
    Packages the given file into a tar archive for Docker's put_archive().
    """
    tarstream = io.BytesIO()
    with tarfile.open(fileobj=tarstream, mode='w') as tar:
        tar.add(file_path, arcname=arcname)
    tarstream.seek(0)
    return tarstream.read()

# --- Startup Event: Create Pre-warmed Container Pools ---
@app.on_event("startup")
def startup_event():
    global container_pools
    # Create 2 containers per pool (adjust count as needed)
    container_pools["docker_python"] = create_container_pool("python", 2)
    container_pools["docker_javascript"] = create_container_pool("javascript", 2)
    container_pools["gvisor_python"] = create_container_pool("python", 2, runtime="runsc")
    container_pools["gvisor_javascript"] = create_container_pool("javascript", 2, runtime="runsc")

# --- CRUD Endpoints ---

@app.get("/")
async def root():
    return {"message": "Serverless Function API Running!"}

@app.post("/functions/", response_model=FunctionRead)
def create_function(function: FunctionCreate, db: Session = Depends(get_db)):
    db_function = db.query(Function).filter(Function.name == function.name).first()
    if db_function:
        raise HTTPException(status_code=400, detail="Function already exists")
    new_function = Function(**function.dict())
    db.add(new_function)
    db.commit()
    db.refresh(new_function)
    return new_function

@app.get("/functions/", response_model=list[FunctionRead])
def read_functions(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    functions = db.query(Function).offset(skip).limit(limit).all()
    return functions

@app.get("/functions/{function_id}", response_model=FunctionRead)
def read_function(function_id: int, db: Session = Depends(get_db)):
    function = db.query(Function).filter(Function.id == function_id).first()
    if function is None:
        raise HTTPException(status_code=404, detail="Function not found")
    return function

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

@app.delete("/functions/{function_id}")
def delete_function(function_id: int, db: Session = Depends(get_db)):
    function = db.query(Function).filter(Function.id == function_id).first()
    if not function:
        raise HTTPException(status_code=404, detail="Function not found")
    db.delete(function)
    db.commit()
    return {"detail": "Function deleted"}

# --- Execution Endpoint with Second Virtualization Support ---
@app.post("/execute/{function_id}", response_model=ExecutionResult)
def execute_function(
    function_id: int,
    tech: str = Query("docker", description="Virtualization technology: 'docker' (default) or 'gvisor'"),
    db: Session = Depends(get_db)
):
    # Fetch function metadata and code from the database
    function = db.query(Function).filter(Function.id == function_id).first()
    if function is None:
        raise HTTPException(status_code=404, detail="Function not found")
    
    # Map language to file extension
    ext_map = {
        "python": "py",
        "javascript": "js"
    }
    file_ext = ext_map.get(function.language)
    if not file_ext:
        raise HTTPException(status_code=400, detail="Unsupported language")
    
    # Create a temporary directory for packaging the function code
    unique_id = str(uuid.uuid4())
    temp_dir = os.path.join(tempfile.gettempdir(), unique_id)
    os.makedirs(temp_dir, exist_ok=True)
    
    filename = f"function.{file_ext}"
    host_file_path = os.path.join(temp_dir, filename)
    
    # Write the function code (from the database) into a file
    with open(host_file_path, "w") as f:
        f.write(function.code)
    
    # Select the correct pre-warmed container pool based on language and tech
    pool_key = None
    if function.language == "python":
        pool_key = "gvisor_python" if tech.lower() == "gvisor" else "docker_python"
    elif function.language == "javascript":
        pool_key = "gvisor_javascript" if tech.lower() == "gvisor" else "docker_javascript"
    else:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Unsupported language")
    
    pool = container_pools.get(pool_key)
    if not pool or len(pool) == 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="No available container in pool")
    
    # For simplicity, select the first container in the pool (can implement round-robin later)
    container = pool[0]
    
    # Package the file into a tar archive for copying
    archive_data = create_tar_for_file(host_file_path, filename)
    
    try:
        # Copy the tar archive into the container's /sandbox directory
        container.put_archive("/sandbox", archive_data)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to copy code into container: {str(e)}")
    
    # Determine the command to run inside the container based on language
    if function.language == "python":
        exec_cmd = ["python", f"/sandbox/{filename}"]
    elif function.language == "javascript":
        exec_cmd = ["node", f"/sandbox/{filename}"]
    
    try:
        # Execute the command inside the pre-warmed container
        exec_result = container.exec_run(exec_cmd, demux=True)
        stdout, stderr = exec_result.output
        output = stdout.decode() if stdout else ""
        error = stderr.decode() if stderr else ""
        return ExecutionResult(output=output, error=error)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")
    finally:
        # Clean up the temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)
