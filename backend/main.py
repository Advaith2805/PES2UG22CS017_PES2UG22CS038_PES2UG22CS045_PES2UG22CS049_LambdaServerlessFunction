from fastapi import FastAPI, Depends, HTTPException, Query # type: ignore
from sqlalchemy.orm import Session # type: ignore
from models import Base, Function  # Ensure Base is defined in your models.py
from database import engine, SessionLocal
from schemas import FunctionRead, FunctionCreate  # Your Pydantic schemas
from pydantic import BaseModel # type: ignore
from typing import Optional
import uuid
import os
import tempfile
import docker # type: ignore
import shutil
import io
import tarfile
import logging

# Prometheus client for metrics
from prometheus_client import Summary, Gauge, make_asgi_app # type: ignore

# Set up basic logging
logging.basicConfig(level=logging.INFO)

# Define Prometheus metrics:
execution_time = Summary('function_execution_seconds', 'Time spent executing functions', ['tech', 'language'])
container_cpu_usage = Gauge('container_cpu_usage', 'CPU usage of container', ['container_name'])
container_memory_usage = Gauge('container_memory_usage', 'Memory usage of container', ['container_name'])

# Mount Prometheus metrics endpoint on /metrics
metrics_app = make_asgi_app()

# Create the database tables if not already created
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Serverless Function API")
app.mount("/metrics", metrics_app)  # Prometheus will scrape metrics from /metrics

# Initialize Docker client
client = docker.from_env()

# Global container pool dictionary.
# Keys: "docker_python", "docker_javascript", "gvisor_python", "gvisor_javascript"
container_pools = {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Response model for execution result, including container name.
class ExecutionResult(BaseModel):
    output: str
    error: Optional[str] = None
    container_name: Optional[str] = None

# --- Helper Functions ---

def create_container_pool(language: str, count: int, runtime: Optional[str] = None):
    """
    Creates a pool of pre-warmed containers for the specified language.
    If 'runtime' is provided (e.g., "runsc" for gVisor), it is used.
    """
    pool = []
    if language == "python":
        image = "function-exec-python"
    elif language == "javascript":
        image = "function-exec-node"
    else:
        raise HTTPException(status_code=400, detail="Unsupported language for pool creation.")
    
    pool_type = runtime if runtime else "docker"
    
    for i in range(count):
        container_name = f"{language}_{pool_type}_pool_{i}"
        try:
            container = client.containers.run(
                image=image,
                name=container_name,
                command="tail -f /dev/null",  # Keeps container alive
                detach=True,
                tty=True,
                auto_remove=False,
                runtime=runtime  # If runtime is None, Docker uses default (runc)
            )
        except docker.errors.APIError as e:
            # If container exists, retrieve it.
            try:
                container = client.containers.get(container_name)
            except docker.errors.NotFound:
                raise HTTPException(status_code=500, detail=f"Container {container_name} could not be created: {str(e)}")
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
    # Create 2 containers per pool (adjust as needed)
    container_pools["docker_python"] = create_container_pool("python", 2)
    container_pools["docker_javascript"] = create_container_pool("javascript", 2)
    try:
        container_pools["gvisor_python"] = create_container_pool("python", 2, runtime="runsc")
        container_pools["gvisor_javascript"] = create_container_pool("javascript", 2, runtime="runsc")
    except HTTPException as e:
        logging.warning(f"Warning: {e.detail}. gVisor pools not created.")

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

# --- Execution Endpoint with Metrics and Runtime Selection ---
@app.post("/execute/{function_id}", response_model=ExecutionResult)
def execute_function(
    function_id: int,
    tech: str = Query("docker", description="Virtualization technology: 'docker' (default) or 'gvisor'"),
    db: Session = Depends(get_db)
):
    # Fetch function metadata and code from the database.
    function = db.query(Function).filter(Function.id == function_id).first()
    if function is None:
        raise HTTPException(status_code=404, detail="Function not found")
    
    # Map language to file extension.
    ext_map = {"python": "py", "javascript": "js"}
    file_ext = ext_map.get(function.language)
    if not file_ext:
        raise HTTPException(status_code=400, detail="Unsupported language")
    
    # Create a temporary directory for packaging the function code.
    unique_id = str(uuid.uuid4())
    temp_dir = os.path.join(tempfile.gettempdir(), unique_id)
    os.makedirs(temp_dir, exist_ok=True)
    
    filename = f"function.{file_ext}"
    host_file_path = os.path.join(temp_dir, filename)
    
    # Write the function code (from the database) into a file.
    with open(host_file_path, "w") as f:
        f.write(function.code)
    
    # Determine which container pool to use.
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
    
    # Select the first container from the pool.
    container = pool[0]
    logging.info(f"Routing execution to container: {container.name}")
    
    # Package the file into a tar archive for copying.
    archive_data = create_tar_for_file(host_file_path, filename)
    
    try:
        # Copy the tar archive into the container's /sandbox directory.
        container.put_archive("/sandbox", archive_data)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to copy code into container: {str(e)}")
    
    # Determine the command to run inside the container based on language.
    if function.language == "python":
        exec_cmd = ["python", f"/sandbox/{filename}"]
    elif function.language == "javascript":
        exec_cmd = ["node", f"/sandbox/{filename}"]
    
    try:
        # Measure execution time using the Prometheus Summary.
        with execution_time.labels(tech=tech.lower(), language=function.language).time():
            exec_result = container.exec_run(exec_cmd, demux=True)
        
        stdout, stderr = exec_result.output
        output = stdout.decode() if stdout else ""
        error = stderr.decode() if stderr else ""
        
        # Retrieve container stats for CPU and memory usage.
        try:
            stats = container.stats(stream=False)
            cpu_usage = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
            mem_usage = stats.get("memory_stats", {}).get("usage", 0)
            container_cpu_usage.labels(container_name=container.name).set(cpu_usage)
            container_memory_usage.labels(container_name=container.name).set(mem_usage)
            logging.info(f"Container {container.name} stats - CPU: {cpu_usage}, Memory: {mem_usage}")
        except Exception as stats_error:
            logging.warning(f"Could not retrieve stats for container {container.name}: {stats_error}")
        
        return ExecutionResult(output=output, error=error, container_name=container.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")
    finally:
        # Clean up the temporary directory.
        shutil.rmtree(temp_dir, ignore_errors=True)
