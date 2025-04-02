from pydantic import BaseModel

class FunctionBase(BaseModel):
    name: str
    route: str
    language: str
    timeout: int

class FunctionCreate(FunctionBase):
    # Inherits all fields for creating a function
    pass

class FunctionRead(FunctionBase):
    id: int

    model_config = {
        "from": True  # Enable ORM mode for compatibility with SQLAlchemy models
    }

class FunctionExecute(BaseModel):
    input_data: str