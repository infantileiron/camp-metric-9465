from fastapi import HTTPException
from src.models.entities import Metric,Snapshot
def metric(s,i):
 x=s.get(Metric,i)
 if not x:raise HTTPException(404,'口径版本不存在')
 return x
def snapshot(s,i):
 x=s.get(Snapshot,i)
 if not x:raise HTTPException(404,'试算快照不存在')
 return x
