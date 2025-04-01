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

    class Config:
        orm_mode = True  # Tells Pydantic to read data even if it's not a dict
