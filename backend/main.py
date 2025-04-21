import os
import uuid
import tempfile
import shutil
import logging
import io
import tarfile

import docker
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from prometheus_client import Counter, Histogram, Gauge, make_asgi_app
from database import engine, SessionLocal
from models import Base, Function
from schemas import FunctionCreate, FunctionRead
from pydantic import BaseModel

Base.metadata.create_all(bind=engine)
class ExecutionResult(BaseModel):
    output: str
    error: str = None
    container_name: str

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI(title="Serverless Function API")
client = docker.from_env()
container_pools = {}
container_indexes = {}

# Prometheus metrics
function_requests = Counter('function_requests_total', 'Total function invocations', ['function_id', 'function_name', 'language', 'tech'])
function_errors = Counter('function_errors_total', 'Total execution errors', ['function_id', 'function_name', 'language', 'tech'])
function_duration = Histogram('function_execution_duration_seconds', 'Latency', ['function_id', 'function_name', 'language', 'tech'], buckets=[0.005,0.01,0.025,0.05,0.1,0.25,0.5,1,2.5,5,10])
container_cpu_usage = Gauge('container_cpu_usage', 'CPU usage', ['container_name'])
container_memory_usage = Gauge('container_memory_usage', 'Memory usage', ['container_name'])

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

def create_container_pool(language: str, count: int, runtime: str = None):
    pool = []
    image = 'function-exec-python' if language == 'python' else 'function-exec-node'
    pool_key = f"{runtime or 'docker'}_{language}"
    for i in range(count):
        name = f"{language}_{runtime or 'docker'}_pool_{i}"
        try:
            container = client.containers.run(
                image=image,
                name=name,
                command=["sleep", "infinity"],
                detach=True,
                tty=True,
                auto_remove=False,
                runtime=runtime
            )
        except docker.errors.APIError:
            logging.warning(f"Reusing existing container {name}")
            container = client.containers.get(name)
        pool.append(container)
    container_pools[pool_key] = pool
    container_indexes[pool_key] = 0

@app.on_event("startup")
def startup_event():
    global container_pools, container_indexes
    container_pools = {}
    container_indexes = {}

    # Supported configurations
    configs = [
        ("docker_python", "function-exec-python", 2, None),
        ("docker_javascript", "function-exec-node", 2, None),
        ("gvisor_python", "function-exec-python", 2, "runsc"),
        ("gvisor_javascript", "function-exec-node", 2, "runsc"),
    ]

    for key, image, count, runtime in configs:
        pool = []
        for i in range(count):
            container_name = f"{key}_pool_{i}"
            try:
                container = client.containers.get(container_name)
                logging.info(f"Reusing existing container: {container_name}")
            except docker.errors.NotFound:
                try:
                    container = client.containers.run(
                        image=image,
                        name=container_name,
                        command=["sleep", "infinity"],
                        detach=True,
                        tty=True,
                        auto_remove=False,
                        runtime=runtime
                    )
                    logging.info(f"Created container: {container_name}")
                except Exception as e:
                    logging.error(f"Failed to create container {container_name}: {e}")
                    continue
            pool.append(container)
        container_pools[key] = pool
        container_indexes[key] = 0  # initialize round-robin index


@app.post("/functions/", response_model=FunctionRead)
def create_function(function: FunctionCreate, db: Session = Depends(get_db)):
    if db.query(Function).filter(Function.name == function.name).first():
        raise HTTPException(400, "Function already exists")
    f = Function(**function.dict())
    db.add(f)
    db.commit()
    db.refresh(f)
    return f

@app.get("/functions/", response_model=list[FunctionRead])
def read_functions(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return db.query(Function).offset(skip).limit(limit).all()

@app.get("/functions/{function_id}", response_model=FunctionRead)
def read_function(function_id: int, db: Session = Depends(get_db)):
    f = db.query(Function).get(function_id)
    if not f:
        raise HTTPException(404, "Function not found")
    return f

@app.put("/functions/{function_id}", response_model=FunctionRead)
def update_function(function_id: int, fn: FunctionCreate, db: Session = Depends(get_db)):
    f = db.query(Function).get(function_id)
    if not f:
        raise HTTPException(404, "Function not found")
    for k, v in fn.dict().items(): setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return f

@app.delete("/functions/{function_id}")
def delete_function(function_id: int, db: Session = Depends(get_db)):
    f = db.query(Function).get(function_id)
    if not f:
        raise HTTPException(404, "Function not found")
    db.delete(f)
    db.commit()
    return {"detail": "Function deleted"}

@app.post("/execute/{function_id}", response_model=ExecutionResult)
def execute_function(
    function_id: int,
    tech: str = Query("docker", description="docker or gvisor"),
    db: Session = Depends(get_db)
):
    f = db.query(Function).get(function_id)
    
    if not f:
        raise HTTPException(404, "Function not found")

    labels = {
        'function_id': str(f.id),
        'function_name': f.name,
        'language': f.language,
        'tech': tech.lower()
    }

    function_requests.labels(**labels).inc()

    ext = {'python': 'py', 'javascript': 'js'}.get(f.language)
    if not ext:
        raise HTTPException(400, "Unsupported language")
    tempd = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
    os.makedirs(tempd, exist_ok=True)
    filename = f"function.{ext}"
    subdir = f"{f.id}"
    arcname = os.path.join(subdir, filename)
    host_file = os.path.join(tempd, filename)

    with open(host_file, "w") as wf:
        wf.write(f.code)

    pool_key = f"{tech}_{f.language}"
    pool = container_pools.get(pool_key)
    if not pool:
        shutil.rmtree(tempd)
        raise HTTPException(500, f"No pool found for {pool_key}")

    idx = container_indexes[pool_key]
    container = pool[idx % len(pool)]
    container_indexes[pool_key] = (idx + 1) % len(pool)

    container.reload()
    if container.status != 'running':
        container.start()

    try:
        container.exec_run(["bash", "-c", f"rm -rf /sandbox/{f.id} && mkdir -p /sandbox/{f.id}"])
    except Exception as e:
        shutil.rmtree(tempd)
        raise HTTPException(500, f"Failed to clean subdir: {e}")

    import io, tarfile
    tarstream = io.BytesIO()
    with tarfile.open(fileobj=tarstream, mode='w') as tar:
        tar.add(host_file, arcname=arcname)
    tarstream.seek(0)
    container.put_archive("/sandbox", tarstream.read())

    cmd = ['python', f'/sandbox/{f.id}/{filename}'] if f.language == 'python' else ['node', f'/sandbox/{f.id}/{filename}']

    try:
        with function_duration.labels(**labels).time():
            res = container.exec_run(cmd, demux=True)
        stdout, stderr = res.output
        output = stdout.decode() if stdout else ''
        error = stderr.decode() if stderr else ''
        if res.exit_code != 0:
            function_errors.labels(**labels).inc()
    except Exception as e:
        function_errors.labels(**labels).inc()
        shutil.rmtree(tempd)
        raise HTTPException(500, f"Execution failed: {e}")

    stats = container.stats(stream=False)
    container_cpu_usage.labels(container_name=container.name).set(
        stats['cpu_stats']['cpu_usage']['total_usage']
    )
    container_memory_usage.labels(container_name=container.name).set(
        stats['memory_stats']['usage']
    )

    shutil.rmtree(tempd, ignore_errors=True)

    return ExecutionResult(output=output, error=error, container_name=container.name)
