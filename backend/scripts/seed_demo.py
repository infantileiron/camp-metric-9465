import random
from datetime import date,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import User,Metric,Fact
from src.utils.security import hash_password
def seed():
 Base.metadata.create_all(engine);rng=random.Random(3111)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for code,name,n,d in [('attendance','实到率','attended','enrolled'),('completion','结课达成率','completed','attended'),('refund','退款占比','refunds','enrolled')]:
   if not s.query(Metric).filter_by(code=code,version=1).first():s.add(Metric(code=code,version=1,name=name,numerator=n,denominator=d,numerator_mode='全部',denominator_mode='全部',note='启航训练营经营口径草案；待业务解释与负责人签核'))
  for i in range(30):
   day=(date(2026,10,17)+timedelta(days=i)).isoformat()
   for j in range(4):
    code=f'QH-{j+1:02}';enrolled=rng.randint(18,40);attended=rng.randint(12,enrolled);completed=rng.randint(8,attended);refunds=rng.randint(0,3)
    if not s.query(Fact).filter_by(class_code=code,day=day).first():s.add(Fact(class_code=code,day=day,mode='线上' if j<2 else '线下',enrolled=enrolled,attended=attended,completed=completed,refunds=refunds,note='班级日聚合，不可解释为唯一学员留存'))
  s.commit();print({'users':s.query(User).count(),'metrics':s.query(Metric).count(),'facts':s.query(Fact).count()})
if __name__=='__main__':seed()
