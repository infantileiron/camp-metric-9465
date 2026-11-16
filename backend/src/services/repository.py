from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from src.models.entities import Metric,Fact

def save_metric(s,data,i=None):
 r=s.get(Metric,i) if i else Metric()
 if not r:raise HTTPException(404,'口径版本不存在')
 if r.locked:raise HTTPException(409,'已签核口径不可覆盖，请建立新版本')
 for k,v in data.model_dump(mode='json').items():setattr(r,k,v)
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'相同指标代码和版本已存在')
 return r

def save_fact(s,data,i=None):
 r=s.get(Fact,i) if i else Fact()
 if not r:raise HTTPException(404,'班级日事实不存在')
 for k,v in data.model_dump(mode='json').items():setattr(r,k,v)
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'相同班级与日期已有事实，请修订原记录')
 return r
