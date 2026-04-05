# model.py
'''
Modelo de datos (AST) para el lenguaje definido por lexer.py.

El lenguaje soporta:
  - Tipos   : integer, float, char, string, boolean, void, array, clases de usuario
  - OOP     : class, this, super, herencia simple con ':'
  - Funciones: function <nombre>(...) : <tipo> { ... }
  - Flujo   : if/else, while, for, return, print
  - Operadores compuestos: +=  -=  *=  /=  %=  ++  --

Patrón Visitor implementado con `multimethod.multimeta`.
Cada visitor define métodos `visit(self, node: TipoConcreto)` con
sobrecarga por tipo; los nodos delegan con `node.accept(visitor)`.
'''

from dataclasses import dataclass, field
from typing import List, Any, Optional
from multimethod import multimeta


# ──────────────────────────────────────────────────────────────────────────────
# Infraestructura base: Visitor (multimeta) + Node
# ──────────────────────────────────────────────────────────────────────────────

class Visitor(metaclass=multimeta):
    '''
    Clase base para visitors del AST.

    Usa `multimethod.multimeta` como metaclase, lo que permite definir
    múltiples métodos `visit` con distintas anotaciones de tipo en la
    misma clase:

        class MiVisitor(Visitor):
            def visit(self, node: Program):        ...
            def visit(self, node: VarDeclaration): ...
            def visit(self, node: BinaryExpr):     ...

    El despacho es automático en función del tipo del argumento.
    '''


@dataclass
class Node:
    '''Nodo raíz del AST.'''
    def accept(self, visitor: Visitor, *args, **kwargs):
        '''Delega en visitor.visit(self).  Despacho gestionado por multimeta.'''
        return visitor.visit(self, *args, **kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# Nodos abstractos intermedios
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Statement(Node):
    pass


@dataclass
class Expression(Node):
    '''
    Base de todas las expresiones.

    El campo `type` se usa para anotar el tipo semántico resultante
    durante el análisis semántico (checker).  Su valor por defecto
    es None antes de ser visitado.
    '''
    type: Any = field(default=None, init=False, repr=False, compare=False)


@dataclass
class Declaration(Statement):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Raíz del programa
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Program(Node):
    '''Lista de declaraciones de nivel superior.'''
    declarations: List[Declaration] = field(default_factory=list)

    def __repr__(self):
        body = '\n  '.join(repr(d) for d in self.declarations)
        return f'Program(\n  {body}\n)'


# ──────────────────────────────────────────────────────────────────────────────
# Tipos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SimpleType(Node):
    '''Tipo primitivo: integer, float, char, string, boolean, void.'''
    name: str           # 'integer' | 'float' | 'char' | 'string' | 'boolean' | 'void'


@dataclass
class ArrayType(Node):
    '''Tipo array[size] element_type  (sintaxis B-minor real).'''
    size        : Node  # expresión de tamaño, p.ej. IntLiteral o Identifier
    element_type: Node  # SimpleType, ArrayType o UserType


@dataclass
class UserType(Node):
    '''Tipo definido por el usuario (nombre de clase).'''
    name: str


# ──────────────────────────────────────────────────────────────────────────────
# Declaraciones
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class VarDeclaration(Declaration):
    '''
    Declaración de variable:
        integer x;
        float y = 3.14;
        array<integer> nums;
    '''
    type_spec : Node               # SimpleType | ArrayType | UserType
    name      : str
    init      : Optional[Expression] = None
    lineno    : int = 0


@dataclass
class Parameter(Node):
    '''Parámetro formal de una función.'''
    type_spec: Node
    name     : str
    lineno   : int = 0


@dataclass
class FuncDeclaration(Declaration):
    '''
    Declaración de función:
        function nombre(params) : tipo_retorno { cuerpo }
        function nombre(params) { cuerpo }   ← retorno implícito void
    '''
    name       : str
    params     : List[Parameter]       = field(default_factory=list)
    return_type: Optional[Node]        = None   # None → void implícito
    body       : List[Statement]       = field(default_factory=list)
    lineno     : int = 0


@dataclass
class FuncPrototype(Declaration):
    '''
    Prototipo de función (sin cuerpo):
        nombre : function tipo ( params ) ;
    '''
    name       : str
    params     : List[Parameter]  = field(default_factory=list)
    return_type: Optional[Node]   = None
    lineno     : int = 0


@dataclass
class ClassDeclaration(Declaration):
    '''
    Declaración de clase:
        class Nombre { ... }
        class Nombre : Padre { ... }
    '''
    name      : str
    superclass: Optional[str]          = None
    members   : List[Declaration]      = field(default_factory=list)
    lineno    : int = 0


# ──────────────────────────────────────────────────────────────────────────────
# Sentencias
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CompoundStatement(Statement):
    '''Bloque { sentencias... }.'''
    stmts: List[Statement] = field(default_factory=list)


@dataclass
class ExprStatement(Statement):
    '''Sentencia de expresión: expr ;'''
    expr  : Expression
    lineno: int = 0


@dataclass
class IfStatement(Statement):
    '''if (cond) then_branch [else else_branch]'''
    cond       : Expression
    then_branch: Statement
    else_branch: Optional[Statement] = None
    lineno     : int = 0


@dataclass
class WhileStatement(Statement):
    '''while (cond) body'''
    cond  : Expression
    body  : Statement
    lineno: int = 0


@dataclass
class ForStatement(Statement):
    '''
    for (init ; cond ; post) body

    - init : ExprStatement | VarDeclaration | None
    - cond : Expression | None
    - post : Expression | None
    '''
    init  : Optional[Statement]
    cond  : Optional[Expression]
    post  : Optional[Expression]
    body  : Statement
    lineno: int = 0


@dataclass
class ReturnStatement(Statement):
    '''return [expr] ;'''
    expr  : Optional[Expression] = None
    lineno: int = 0


@dataclass
class PrintStatement(Statement):
    '''print expr, expr, ... ;  (B-minor: sin paréntesis, múltiples args)'''
    exprs : List[Expression] = field(default_factory=list)
    lineno: int = 0


# ──────────────────────────────────────────────────────────────────────────────
# Expresiones
# Nota: todos los nodos Expression heredan el campo `type` (Any, default None)
# definido en la base Expression.  El checker lo anotará durante el análisis.
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AssignExpr(Expression):
    '''
    Asignación y compuesta:
        x = expr
        x += expr   x -= expr   x *= expr   x /= expr   x %= expr
    El operador op es '=', '+=', '-=', '*=', '/=', '%='.
    target puede ser un ID, acceso a array, acceso a atributo.
    '''
    target: Expression
    op    : str
    value : Expression
    lineno: int = 0


@dataclass
class BinaryExpr(Expression):
    '''Expresión binaria: left op right'''
    left  : Expression
    op    : str
    right : Expression
    lineno: int = 0


@dataclass
class UnaryExpr(Expression):
    '''Expresión unaria prefija: op expr  (-, !, ++, --)'''
    op    : str
    expr  : Expression
    lineno: int = 0


@dataclass
class PostfixExpr(Expression):
    '''Expresión unaria posfija: expr op  (++, --)'''
    expr  : Expression
    op    : str          # '++' | '--'
    lineno: int = 0


@dataclass
class CallExpr(Expression):
    '''Llamada a función/método: callee(args)'''
    callee: Expression
    args  : List[Expression] = field(default_factory=list)
    lineno: int = 0


@dataclass
class IndexExpr(Expression):
    '''Acceso a array: expr[index]'''
    expr  : Expression
    index : Expression
    lineno: int = 0


@dataclass
class MemberExpr(Expression):
    '''Acceso a atributo/método: obj.name'''
    obj   : Expression
    member: str
    lineno: int = 0


@dataclass
class GroupExpr(Expression):
    '''Expresión entre paréntesis: (expr)'''
    expr: Expression


# ──────────────────────────────────────────────────────────────────────────────
# Literales y átomos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IntLiteral(Expression):
    value : int
    lineno: int = 0


@dataclass
class FloatLiteral(Expression):
    value : float
    lineno: int = 0


@dataclass
class CharLiteral(Expression):
    value : str
    lineno: int = 0


@dataclass
class StringLiteral(Expression):
    value : str
    lineno: int = 0


@dataclass
class BoolLiteral(Expression):
    value : bool            # True / False
    lineno: int = 0


@dataclass
class ArrayLiteral(Expression):
    '''Literal de array B-minor: {e1, e2, ...}'''
    elements: List[Expression] = field(default_factory=list)
    lineno  : int = 0


@dataclass
class Identifier(Expression):
    '''Referencia a variable o función por nombre.'''
    name  : str
    lineno: int = 0


@dataclass
class ThisExpr(Expression):
    '''Referencia a la instancia actual: this'''
    lineno: int = 0


@dataclass
class SuperExpr(Expression):
    '''Referencia a la clase padre: super'''
    lineno: int = 0