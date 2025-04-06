from pydantic import BaseModel

class FunctionBase(BaseModel):
    name: str
    route: str
    language: str
    timeout: int
    code: str

class FunctionCreate(FunctionBase):
   
    pass

class FunctionRead(FunctionBase):
    id: int

    model_config = {
        "from": True  
    }

class FunctionExecute(BaseModel):
    input_data: str