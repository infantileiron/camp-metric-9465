import ast,math
from src.constants.enums import FIELDS
OPERATORS={ast.Add:lambda a,b:a+b,ast.Sub:lambda a,b:a-b,ast.Mult:lambda a,b:a*b,ast.Div:lambda a,b:a/b}
def parse(expression):
 if len(expression)>200:raise ValueError('表达式最多200字符')
 try:tree=ast.parse(expression,mode='eval')
 except SyntaxError:raise ValueError('表达式语法不合法')
 if len(list(ast.walk(tree)))>60:raise ValueError('表达式过于复杂')
 def check(node):
  if isinstance(node,ast.Expression):check(node.body)
  elif isinstance(node,ast.Name):
   if node.id not in FIELDS:raise ValueError('只允许字段 enrolled/attended/completed/refunds')
  elif isinstance(node,ast.Constant):
   if type(node.value) not in (int,float) or not math.isfinite(node.value) or abs(node.value)>1000000:raise ValueError('只允许有限数值常量，绝对值不超过1000000')
  elif isinstance(node,ast.BinOp) and type(node.op) in OPERATORS:check(node.left);check(node.right)
  elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):check(node.operand)
  else:raise ValueError('仅允许字段、数值、括号、+ - * /；禁止函数、属性、索引或SQL')
 check(tree);return tree

def execute(tree,row):
 def walk(node):
  if isinstance(node,ast.Expression):return walk(node.body)
  if isinstance(node,ast.Constant):return node.value
  if isinstance(node,ast.Name):return row[node.id]
  if isinstance(node,ast.UnaryOp):return -walk(node.operand) if isinstance(node.op,ast.USub) else walk(node.operand)
  if isinstance(node,ast.BinOp):
   a,b=walk(node.left),walk(node.right)
   if isinstance(node.op,ast.Div) and b==0:raise ValueError('行级表达式除零，请修正口径；外层分母为零则单独标记undefined')
   return OPERATORS[type(node.op)](a,b)
  raise ValueError('不支持的表达式')
 value=float(walk(tree))
 if not math.isfinite(value) or abs(value)>1e15:raise ValueError('表达式结果超出允许范围')
 return value
