# checker.py
'''
Analizador semántico para el lenguaje B-Minor.

Implementa:
  - Tabla de símbolos con alcance léxico (ChainMap)
  - Patrón Visitor usando multimethod
  - Chequeo de tipos fuertemente tipado
  - Reporte acumulado de errores semánticos
  - Anotación de nodos del AST con su tipo resultante
'''

from collections import ChainMap
from multimethod import multimeta
from model import *


# ─────────────────────────────────────────────────────────────────────────────
# Representación interna de tipos
# ─────────────────────────────────────────────────────────────────────────────

class Type:
    '''Tipo base del sistema de tipos de B-Minor.'''
    pass

class IntType(Type):
    def __repr__(self): return 'integer'
    def __eq__(self, other): return isinstance(other, IntType)
    def __hash__(self): return hash('integer')

class FloatType(Type):
    def __repr__(self): return 'float'
    def __eq__(self, other): return isinstance(other, FloatType)
    def __hash__(self): return hash('float')

class BoolType(Type):
    def __repr__(self): return 'boolean'
    def __eq__(self, other): return isinstance(other, BoolType)
    def __hash__(self): return hash('boolean')

class CharType(Type):
    def __repr__(self): return 'char'
    def __eq__(self, other): return isinstance(other, CharType)
    def __hash__(self): return hash('char')

class StringType(Type):
    def __repr__(self): return 'string'
    def __eq__(self, other): return isinstance(other, StringType)
    def __hash__(self): return hash('string')

class VoidType(Type):
    def __repr__(self): return 'void'
    def __eq__(self, other): return isinstance(other, VoidType)
    def __hash__(self): return hash('void')

class ArrayTypeT(Type):
    def __init__(self, element_type):
        self.element_type = element_type
    def __repr__(self): return f'array[{self.element_type}]'
    def __eq__(self, other):
        return isinstance(other, ArrayTypeT) and self.element_type == other.element_type
    def __hash__(self): return hash(('array', self.element_type))

class FuncTypeT(Type):
    def __init__(self, return_type, param_types):
        self.return_type = return_type
        self.param_types = param_types
    def __repr__(self):
        params = ', '.join(str(t) for t in self.param_types)
        return f'function({params})->{self.return_type}'
    def __eq__(self, other):
        return (isinstance(other, FuncTypeT)
                and self.return_type == other.return_type
                and self.param_types == other.param_types)
    def __hash__(self): return hash(('func', self.return_type))

class UserTypeT(Type):
    def __init__(self, name):
        self.name = name
    def __repr__(self): return self.name
    def __eq__(self, other): return isinstance(other, UserTypeT) and self.name == other.name
    def __hash__(self): return hash(self.name)

# Singletons de tipos primitivos
INT    = IntType()
FLOAT  = FloatType()
BOOL   = BoolType()
CHAR   = CharType()
STRING = StringType()
VOID   = VoidType()
ERROR  = None   # Tipo de error — evita cascada de errores

# Mapeo desde nombres de tipos en el AST al sistema interno
BUILTIN_TYPES = {
    'integer': INT,
    'float':   FLOAT,
    'boolean': BOOL,
    'char':    CHAR,
    'string':  STRING,
    'void':    VOID,
}

# ─────────────────────────────────────────────────────────────────────────────
# Tabla de compatibilidad de operadores
# ─────────────────────────────────────────────────────────────────────────────

# (operador, tipo_izquierdo, tipo_derecho) -> tipo_resultado
BINARY_RULES = {
    # Aritméticos enteros
    ('+',  INT,   INT):   INT,
    ('-',  INT,   INT):   INT,
    ('*',  INT,   INT):   INT,
    ('/',  INT,   INT):   INT,
    ('%',  INT,   INT):   INT,
    # Aritméticos float
    ('+',  FLOAT, FLOAT): FLOAT,
    ('-',  FLOAT, FLOAT): FLOAT,
    ('*',  FLOAT, FLOAT): FLOAT,
    ('/',  FLOAT, FLOAT): FLOAT,
    # Mixto int/float
    ('+',  INT,   FLOAT): FLOAT,
    ('+',  FLOAT, INT):   FLOAT,
    ('-',  INT,   FLOAT): FLOAT,
    ('-',  FLOAT, INT):   FLOAT,
    ('*',  INT,   FLOAT): FLOAT,
    ('*',  FLOAT, INT):   FLOAT,
    ('/',  INT,   FLOAT): FLOAT,
    ('/',  FLOAT, INT):   FLOAT,
    # Relacionales numéricos
    ('<',  INT,   INT):   BOOL,
    ('<=', INT,   INT):   BOOL,
    ('>',  INT,   INT):   BOOL,
    ('>=', INT,   INT):   BOOL,
    ('<',  FLOAT, FLOAT): BOOL,
    ('<=', FLOAT, FLOAT): BOOL,
    ('>',  FLOAT, FLOAT): BOOL,
    ('>=', FLOAT, FLOAT): BOOL,
    ('<',  INT,   FLOAT): BOOL,
    ('<=', INT,   FLOAT): BOOL,
    ('>',  INT,   FLOAT): BOOL,
    ('>=', INT,   FLOAT): BOOL,
    ('<',  FLOAT, INT):   BOOL,
    ('<=', FLOAT, INT):   BOOL,
    ('>',  FLOAT, INT):   BOOL,
    ('>=', FLOAT, INT):   BOOL,
    # Igualdad — tipos compatibles
    ('==', INT,     INT):     BOOL,
    ('!=', INT,     INT):     BOOL,
    ('==', FLOAT,   FLOAT):   BOOL,
    ('!=', FLOAT,   FLOAT):   BOOL,
    ('==', BOOL,    BOOL):    BOOL,
    ('!=', BOOL,    BOOL):    BOOL,
    ('==', CHAR,    CHAR):    BOOL,
    ('!=', CHAR,    CHAR):    BOOL,
    ('==', STRING,  STRING):  BOOL,
    ('!=', STRING,  STRING):  BOOL,
    # Lógicos
    ('&&', BOOL, BOOL): BOOL,
    ('||', BOOL, BOOL): BOOL,
    # Concatenación de strings con +
    ('+',  STRING, STRING): STRING,
}

# Operadores unarios
UNARY_RULES = {
    ('-',  INT):   INT,
    ('-',  FLOAT): FLOAT,
    ('!',  BOOL):  BOOL,
    ('++', INT):   INT,
    ('--', INT):   INT,
}


# ─────────────────────────────────────────────────────────────────────────────
# Símbolo de la tabla de símbolos
# ─────────────────────────────────────────────────────────────────────────────

class Symbol:
    def __init__(self, name, kind, type_, node=None):
        self.name  = name   # str
        self.kind  = kind   # 'variable' | 'function' | 'parameter' | 'class'
        self.type_ = type_  # instancia de Type
        self.node  = node   # nodo AST asociado

    def __repr__(self):
        return f'Symbol({self.name!r}, kind={self.kind!r}, type={self.type_})'


# ─────────────────────────────────────────────────────────────────────────────
# Visitor con multimeta
# ─────────────────────────────────────────────────────────────────────────────

class Visitor(metaclass=multimeta):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Checker principal
# ─────────────────────────────────────────────────────────────────────────────

class Checker(Visitor):

    def __init__(self):
        self.errors       = []          # lista de mensajes de error
        self.symtab       = ChainMap()  # tabla de símbolos con alcance léxico
        self.current_func = None        # FuncDeclaration actual (para return)

    # ── Utilidades ────────────────────────────────────────────────────────

    def error(self, msg, lineno=0):
        prefix = f'línea {lineno}: ' if lineno else ''
        self.errors.append(f'error: {prefix}{msg}')

    def enter_scope(self):
        self.symtab = self.symtab.new_child()

    def exit_scope(self):
        self.symtab = self.symtab.parents

    def define(self, name, symbol, lineno=0):
        '''Registra un símbolo en el alcance actual. Detecta redeclaraciones.'''
        if name in self.symtab.maps[0]:
            self.error(f"'{name}' ya fue declarado en este alcance", lineno)
        else:
            self.symtab[name] = symbol

    def lookup(self, name, lineno=0):
        '''Busca un símbolo en toda la cadena de alcances.'''
        sym = self.symtab.get(name)
        if sym is None:
            self.error(f"símbolo '{name}' no definido", lineno)
        return sym

    def resolve_type(self, type_node):
        '''Convierte un nodo de tipo del AST en un objeto Type interno.'''
        if isinstance(type_node, SimpleType):
            return BUILTIN_TYPES.get(type_node.name, ERROR)
        if isinstance(type_node, ArrayType):
            elem = self.resolve_type(type_node.element_type)
            return ArrayTypeT(elem)
        if isinstance(type_node, UserType):
            sym = self.symtab.get(type_node.name)
            if sym is None:
                return UserTypeT(type_node.name)
            return sym.type_
        return ERROR

    # ── Programa ──────────────────────────────────────────────────────────

    def visit(self, node: Program):
        for decl in node.declarations:
            self.visit(decl)

    # ── Declaraciones ─────────────────────────────────────────────────────

    def visit(self, node: VarDeclaration):
        var_type = self.resolve_type(node.type_spec)

        if node.init is not None:
            init_type = self.visit(node.init)
            if var_type is not ERROR and init_type is not ERROR:
                if not self._types_compatible(var_type, init_type):
                    self.error(
                        f"no se puede inicializar '{node.name}' de tipo "
                        f"{var_type} con un valor de tipo {init_type}",
                        node.lineno
                    )

        sym = Symbol(node.name, 'variable', var_type, node)
        self.define(node.name, sym, node.lineno)
        node.type = var_type

    def visit(self, node: FuncDeclaration):
        return_type  = self.resolve_type(node.return_type) if node.return_type else VOID
        param_types  = []

        # Primero registramos la función en el alcance actual (permite recursión)
        for p in node.params:
            param_types.append(self.resolve_type(p.type_spec))

        func_type = FuncTypeT(return_type, param_types)
        sym = Symbol(node.name, 'function', func_type, node)
        self.define(node.name, sym, node.lineno)
        node.type = func_type

        # Nuevo alcance para parámetros y cuerpo
        self.enter_scope()
        for p, pt in zip(node.params, param_types):
            psym = Symbol(p.name, 'parameter', pt, p)
            self.define(p.name, psym, p.lineno)
            p.type = pt

        prev_func     = self.current_func
        self.current_func = node

        for stmt in node.body:
            self.visit(stmt)

        self.current_func = prev_func
        self.exit_scope()

    def visit(self, node: FuncPrototype):
        return_type = self.resolve_type(node.return_type) if node.return_type else VOID
        param_types = [self.resolve_type(p.type_spec) for p in node.params]
        func_type   = FuncTypeT(return_type, param_types)
        sym = Symbol(node.name, 'function', func_type, node)
        self.define(node.name, sym, node.lineno)
        node.type = func_type

    def visit(self, node: ClassDeclaration):
        sym = Symbol(node.name, 'class', UserTypeT(node.name), node)
        self.define(node.name, sym, node.lineno)

        self.enter_scope()
        for member in node.members:
            self.visit(member)
        self.exit_scope()

    # ── Sentencias ────────────────────────────────────────────────────────

    def visit(self, node: CompoundStatement):
        self.enter_scope()
        for stmt in node.stmts:
            self.visit(stmt)
        self.exit_scope()

    def visit(self, node: ExprStatement):
        self.visit(node.expr)

    def visit(self, node: IfStatement):
        cond_type = self.visit(node.cond)
        if cond_type is not ERROR and cond_type != BOOL:
            self.error(
                f"la condición del if debe ser boolean y se recibió {cond_type}",
                node.lineno
            )
        self.visit(node.then_branch)
        if node.else_branch:
            self.visit(node.else_branch)

    def visit(self, node: WhileStatement):
        cond_type = self.visit(node.cond)
        if cond_type is not ERROR and cond_type != BOOL:
            self.error(
                f"la condición del while debe ser boolean y se recibió {cond_type}",
                node.lineno
            )
        self.visit(node.body)

    def visit(self, node: ForStatement):
        self.enter_scope()
        if node.init:
            self.visit(node.init)
        if node.cond:
            cond_type = self.visit(node.cond)
            if cond_type is not ERROR and cond_type != BOOL:
                self.error(
                    f"la condición del for debe ser boolean y se recibió {cond_type}",
                    node.lineno
                )
        if node.post:
            self.visit(node.post)
        self.visit(node.body)
        self.exit_scope()

    def visit(self, node: ReturnStatement):
        expected = VOID
        if self.current_func and self.current_func.return_type:
            expected = self.resolve_type(self.current_func.return_type)

        if node.expr is None:
            if expected != VOID and expected is not ERROR:
                self.error(
                    f"la función '{self.current_func.name}' debe retornar "
                    f"{expected} pero no retorna nada",
                    node.lineno
                )
        else:
            ret_type = self.visit(node.expr)
            if ret_type is not ERROR and expected is not ERROR:
                if not self._types_compatible(expected, ret_type):
                    fname = self.current_func.name if self.current_func else '?'
                    self.error(
                        f"la función '{fname}' debe retornar {expected} "
                        f"pero se encontró {ret_type}",
                        node.lineno
                    )

    def visit(self, node: PrintStatement):
        for expr in node.exprs:
            self.visit(expr)

    # ── Expresiones ───────────────────────────────────────────────────────

    def visit(self, node: AssignExpr) -> Type:
        target_type = self.visit(node.target)
        value_type  = self.visit(node.value)

        if target_type is ERROR or value_type is ERROR:
            node.type = ERROR
            return ERROR

        # Para operadores compuestos como +=, verificamos que la operación base sea válida
        if node.op != '=':
            base_op = node.op[:-1]   # '+=' → '+'
            result = BINARY_RULES.get((base_op, target_type, value_type))
            if result is None:
                self.error(
                    f"operador '{node.op}' no aplica a los tipos "
                    f"{target_type} y {value_type}",
                    node.lineno
                )
                node.type = ERROR
                return ERROR
        else:
            if not self._types_compatible(target_type, value_type):
                self.error(
                    f"no se puede asignar un valor de tipo {value_type} "
                    f"a una variable de tipo {target_type}",
                    node.lineno
                )
                node.type = ERROR
                return ERROR

        node.type = target_type
        return target_type

    def visit(self, node: BinaryExpr) -> Type:
        left_type  = self.visit(node.left)
        right_type = self.visit(node.right)

        if left_type is ERROR or right_type is ERROR:
            node.type = ERROR
            return ERROR

        result = BINARY_RULES.get((node.op, left_type, right_type))
        if result is None:
            self.error(
                f"operador '{node.op}' no puede aplicarse a los tipos "
                f"{left_type} y {right_type}",
                node.lineno
            )
            node.type = ERROR
            return ERROR

        node.type = result
        return result

    def visit(self, node: UnaryExpr) -> Type:
        expr_type = self.visit(node.expr)

        if expr_type is ERROR:
            node.type = ERROR
            return ERROR

        result = UNARY_RULES.get((node.op, expr_type))
        if result is None:
            self.error(
                f"operador unario '{node.op}' no puede aplicarse al tipo {expr_type}",
                node.lineno
            )
            node.type = ERROR
            return ERROR

        node.type = result
        return result

    def visit(self, node: PostfixExpr) -> Type:
        expr_type = self.visit(node.expr)

        if expr_type is ERROR:
            node.type = ERROR
            return ERROR

        if expr_type != INT:
            self.error(
                f"operador postfijo '{node.op}' requiere un operando integer, "
                f"se recibió {expr_type}",
                node.lineno
            )
            node.type = ERROR
            return ERROR

        node.type = INT
        return INT

    def visit(self, node: CallExpr) -> Type:
        callee_type = self.visit(node.callee)

        if callee_type is ERROR:
            node.type = ERROR
            return ERROR

        if not isinstance(callee_type, FuncTypeT):
            name = node.callee.name if isinstance(node.callee, Identifier) else '?'
            self.error(
                f"'{name}' no es una función y no puede ser llamada",
                node.lineno
            )
            node.type = ERROR
            return ERROR

        # Verificar número de argumentos
        expected_n = len(callee_type.param_types)
        received_n = len(node.args)
        if expected_n != received_n:
            name = node.callee.name if isinstance(node.callee, Identifier) else '?'
            self.error(
                f"la función '{name}' espera {expected_n} argumento(s) "
                f"pero recibió {received_n}",
                node.lineno
            )

        # Verificar tipos de argumentos
        arg_types = [self.visit(a) for a in node.args]
        for i, (expected_t, got_t) in enumerate(
            zip(callee_type.param_types, arg_types)
        ):
            if got_t is ERROR:
                continue
            if not self._types_compatible(expected_t, got_t):
                name = node.callee.name if isinstance(node.callee, Identifier) else '?'
                self.error(
                    f"la función '{name}': el argumento {i+1} debe ser "
                    f"{expected_t} pero se recibió {got_t}",
                    node.lineno
                )

        node.type = callee_type.return_type
        return callee_type.return_type

    def visit(self, node: IndexExpr) -> Type:
        expr_type  = self.visit(node.expr)
        index_type = self.visit(node.index)

        if expr_type is ERROR:
            node.type = ERROR
            return ERROR

        if not isinstance(expr_type, ArrayTypeT):
            self.error(
                f"el acceso con índice '[...]' requiere un arreglo, "
                f"se recibió {expr_type}",
                node.lineno
            )
            node.type = ERROR
            return ERROR

        if index_type is not ERROR and index_type != INT:
            self.error(
                f"el índice del arreglo debe ser integer, se recibió {index_type}",
                node.lineno
            )

        node.type = expr_type.element_type
        return expr_type.element_type

    def visit(self, node: MemberExpr) -> Type:
        # Chequeo básico: verificamos que el objeto exista
        obj_type = self.visit(node.obj)
        node.type = ERROR   # No podemos verificar miembros sin tabla de clases completa
        return ERROR

    def visit(self, node: GroupExpr) -> Type:
        t = self.visit(node.expr)
        node.type = t
        return t

    # ── Literales ─────────────────────────────────────────────────────────

    def visit(self, node: IntLiteral) -> Type:
        node.type = INT
        return INT

    def visit(self, node: FloatLiteral) -> Type:
        node.type = FLOAT
        return FLOAT

    def visit(self, node: CharLiteral) -> Type:
        node.type = CHAR
        return CHAR

    def visit(self, node: StringLiteral) -> Type:
        node.type = STRING
        return STRING

    def visit(self, node: BoolLiteral) -> Type:
        node.type = BOOL
        return BOOL

    def visit(self, node: ArrayLiteral) -> Type:
        if not node.elements:
            node.type = ArrayTypeT(ERROR)
            return node.type

        elem_types = [self.visit(e) for e in node.elements]
        base = elem_types[0]

        for i, t in enumerate(elem_types[1:], start=2):
            if t is not ERROR and base is not ERROR and t != base:
                self.error(
                    f"el arreglo literal tiene elementos de tipos mezclados: "
                    f"{base} y {t} (elemento {i})",
                    node.lineno
                )
                node.type = ArrayTypeT(ERROR)
                return node.type

        node.type = ArrayTypeT(base)
        return node.type

    def visit(self, node: Identifier) -> Type:
        sym = self.lookup(node.name, node.lineno)
        if sym is None:
            node.type = ERROR
            return ERROR
        node.type = sym.type_
        return sym.type_

    def visit(self, node: ThisExpr) -> Type:
        node.type = ERROR   # Requiere contexto de clase
        return ERROR

    def visit(self, node: SuperExpr) -> Type:
        node.type = ERROR   # Requiere contexto de clase
        return ERROR

    # ── Compatibilidad de tipos ───────────────────────────────────────────

    def _types_compatible(self, expected: Type, got: Type) -> bool:
        '''
        Verifica si `got` es compatible con `expected`.
        En B-Minor fuertemente tipado, los tipos deben coincidir exactamente,
        salvo la excepción int/float numérica.
        '''
        if expected == got:
            return True
        # Permitir asignación int -> float implícita
        if isinstance(expected, FloatType) and isinstance(got, IntType):
            return True
        return False

    # ── Resultado final ───────────────────────────────────────────────────

    def check(self, ast) -> bool:
        '''
        Punto de entrada principal.
        Retorna True si no hubo errores, False en caso contrario.
        '''
        self.visit(ast)
        return len(self.errors) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Interfaz de línea de comandos
# ─────────────────────────────────────────────────────────────────────────────

def run_checker(source_path: str) -> bool:
    '''
    Ejecuta el pipeline completo: lexer → parser → checker.
    Imprime errores y resultado final.
    Retorna True si el programa es semánticamente correcto.
    '''
    from lexer   import Lexer
    from parser  import Parser

    source = open(source_path, encoding='utf-8').read()
    lexer  = Lexer()
    parser = Parser()
    ast    = parser.parse(lexer.tokenize(source))

    if ast is None:
        print('semantic check: failed  (el parser no produjo un AST)')
        return False

    checker = Checker()
    ok      = checker.check(ast)

    for msg in checker.errors:
        print(msg)

    if ok:
        print('semantic check: success')
    else:
        print('semantic check: failed')

    return ok


if __name__ == '__main__':
    import sys

    if len(sys.argv) != 2:
        print('Uso: python checker.py <archivo.bminor>')
        sys.exit(1)

    success = run_checker(sys.argv[1])
    sys.exit(0 if success else 1)
