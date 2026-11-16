from pydantic import BaseModel,Field,model_validator,field_validator
from typing import Literal,Optional
from datetime import date
from src.services.expression import parse
class Login(BaseModel):email:str;password:str
class MetricInput(BaseModel):
 code:str=Field(pattern=r'^[a-z][a-z0-9_]{1,39}$')
 version:int=Field(ge=1,le=10000)
 name:str=Field(min_length=2,max_length=100)
 numerator:str=Field(min_length=1,max_length=200)
 denominator:str=Field(min_length=1,max_length=200)
 numerator_mode:Literal['全部','线上','线下']='全部'
 denominator_mode:Literal['全部','线上','线下']='全部'
 note:str=Field(default='',max_length=2000)
 @field_validator('numerator','denominator')
 @classmethod
 def valid_expression(cls,v):parse(v);return v
class FactInput(BaseModel):
 class_code:str=Field(min_length=1,max_length=50)
 day:date
 mode:Literal['线上','线下']
 enrolled:int=Field(ge=0,le=1000000)
 attended:int=Field(ge=0,le=1000000)
 completed:int=Field(ge=0,le=1000000)
 refunds:int=Field(ge=0,le=1000000)
 note:str=Field(default='',max_length=1000)
 @model_validator(mode='after')
 def valid_counts(self):
  if self.attended>self.enrolled or self.completed>self.attended or self.refunds>self.enrolled:raise ValueError('需满足结课≤实到≤报名，退款≤报名；各值非负')
  return self
class RunInput(BaseModel):
 metric_id:int=Field(gt=0)
 baseline_id:Optional[int]=Field(default=None,gt=0)
 date_from:date
 date_to:date
 @model_validator(mode='after')
 def window(self):
  if self.date_from>self.date_to:raise ValueError('开始日不得晚于结束日')
  return self
class NoteInput(BaseModel):note:str=Field(min_length=8,max_length=2000)
