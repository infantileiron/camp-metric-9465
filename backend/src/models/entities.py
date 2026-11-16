from sqlalchemy import Column,Integer,String,Float,JSON,Text,Boolean,ForeignKey,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Metric(Base):
 __tablename__='metrics';__table_args__=(UniqueConstraint('code','version'),)
 id=Column(Integer,primary_key=True);code=Column(String(40),nullable=False);version=Column(Integer,nullable=False);name=Column(String(100));numerator=Column(String(200));denominator=Column(String(200));numerator_mode=Column(String(20));denominator_mode=Column(String(20));note=Column(Text,default='');locked=Column(Boolean,default=False)
class Fact(Base):
 __tablename__='facts';__table_args__=(UniqueConstraint('class_code','day'),)
 id=Column(Integer,primary_key=True);class_code=Column(String(50),nullable=False);day=Column(String(10),nullable=False);mode=Column(String(20));enrolled=Column(Integer);attended=Column(Integer);completed=Column(Integer);refunds=Column(Integer);note=Column(Text,default='')
class Snapshot(Base):
 __tablename__='snapshots'
 id=Column(Integer,primary_key=True);metric_id=Column(Integer,ForeignKey('metrics.id'));baseline_id=Column(Integer,ForeignKey('snapshots.id'),nullable=True);date_from=Column(String(10));date_to=Column(String(10));state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='');note=Column(Text,default='');approval=Column(String(20),default='draft');approved_by=Column(String(100),default='')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
