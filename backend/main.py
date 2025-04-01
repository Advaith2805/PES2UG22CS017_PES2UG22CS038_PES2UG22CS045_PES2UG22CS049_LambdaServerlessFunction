from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from models import Base, Function
from schemas import FunctionCreate, FunctionRead
from database import engine, SessionLocal

# Create the database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Serverless Function API")

# Dependency to get a DB session for each request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Root endpoint
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
