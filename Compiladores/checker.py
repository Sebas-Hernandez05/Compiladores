# checker.py
'''
Analizador semántico para el lenguaje B++.

Recorre el AST con el patrón Visitor (multimethod) y verifica:
  1. Declaraciones y alcance léxico
  2. Redeclaraciones en el mismo alcance
  3. Uso de identificadores no definidos
  4. Chequeo de tipos en expresiones, asignaciones y operadores
  5. Reglas de funciones: parámetros, retorno, llamadas
  6. break/continue solo dentro de bucles
  7. Existencia de función main
'''

from multimethod import multimethod
from model import *


# ══════════════════════════════════════════════════════════════════════════════
# Representación interna de tipos
# ══════════════════════════════════════════════════════════════════════════════

class Type:
    '''Clase base para los tipos del sistema.'''
    def __eq__(self, other):
        return type(self) is type(other)
    def __repr__(self):
        return type(self).__name__

class IntType(Type):    pass
class FloatType(Type):  pass
class BoolType(Type):   pass
class CharType(Type):   pass
class StringType(Type): pass
class VoidType(Type):   pass
class ErrorType(Type):  pass   # centinela — evita cascada de errores

class ArrayTypeT(Type):
    def __init__(self, element_type, size=None):
        self.element_type = element_type
        self.size = size
    def __eq__(self, other):
        return isinstance(other, ArrayTypeT) and self.element_type == other.element_type
    def __repr__(self):
        return f'array[{self.element_type}]'

class FuncTypeT(Type):
    def __init__(self, return_type, param_types):
        self.return_type  = return_type
        self.param_types  = param_types   # lista de Type
    def __eq__(self, other):
        return (isinstance(other, FuncTypeT)
                and self.return_type == other.return_type
                and self.param_types == other.param_types)
    def __repr__(self):
        params = ', '.join(str(t) for t in self.param_types)
        return f'function({params}) -> {self.return_type}'


# Convierte SimpleType / ArrayType / FuncType del AST a Type interno
def ast_type_to_type(node):
    if node is None:
        return VoidType()
    if isinstance(node, SimpleType):
        return {
            'integer': IntType(),
            'float':   FloatType(),
            'boolean': BoolType(),
            'char':    CharType(),
            'string':  StringType(),
            'void':    VoidType(),
        }.get(node.name, ErrorType())
    if isinstance(node, ArrayType):
        return ArrayTypeT(ast_type_to_type(node.element_type), node.size)
    if isinstance(node, FuncType):
        ret    = ast_type_to_type(node.return_type)
        params = [ast_type_to_type(p.type) for p in node.params]
        return FuncTypeT(ret, params)
    return ErrorType()


# ══════════════════════════════════════════════════════════════════════════════
# Tabla de símbolos con alcance léxico
# ══════════════════════════════════════════════════════════════════════════════

class Symbol:
    def __init__(self, name, kind, type_, node=None):
        self.name   = name    # str
        self.kind   = kind    # 'variable' | 'const' | 'function' | 'param' | 'array'
        self.type_  = type_   # Type interno
        self.node   = node    # nodo AST

    def __repr__(self):
        return f'Symbol({self.name!r}, {self.kind}, {self.type_})'


class Symtab:
    class SymbolDefinedError(Exception):
        pass

    def __init__(self, parent=None, name='<scope>'):
        self.name    = name
        self.parent  = parent
        self.entries = {}           # str -> Symbol
        self._is_loop     = False
        self._func_return = None    # Type esperado de retorno (solo en scope de función)

    # ── Alcance de bucle ──────────────────────────────────────────────────────

    def mark_loop(self):
        self._is_loop = True

    def in_loop(self):
        if self._is_loop:
            return True
        if self.parent:
            return self.parent.in_loop()
        return False

    # ── Retorno de función ────────────────────────────────────────────────────

    def set_return_type(self, t):
        self._func_return = t

    def expected_return(self):
        if self._func_return is not None:
            return self._func_return
        if self.parent:
            return self.parent.expected_return()
        return None

    # ── Inserción y búsqueda ─────────────────────────────────────────────────

    def add(self, name, symbol):
        if name in self.entries:
            raise Symtab.SymbolDefinedError(name)
        self.entries[name] = symbol

    def get(self, name):
        if name in self.entries:
            return self.entries[name]
        if self.parent:
            return self.parent.get(name)
        return None

    def get_local(self, name):
        return self.entries.get(name, None)

    # ── Depuración ────────────────────────────────────────────────────────────

    def dump(self, indent=0):
        pad = '  ' * indent
        print(f'{pad}[{self.name}]')
        for name, sym in self.entries.items():
            print(f'{pad}  {name}: {sym}')


# ══════════════════════════════════════════════════════════════════════════════
# Tablas de compatibilidad de operadores
# ══════════════════════════════════════════════════════════════════════════════

# op -> lista de (tipo_izq, tipo_der) -> tipo_resultado
BINARY_RULES = {
    # Aritméticos
    '+':  [((IntType,   IntType),   IntType()),
           ((FloatType, FloatType), FloatType()),
           ((IntType,   FloatType), FloatType()),
           ((FloatType, IntType),   FloatType()),
           ((StringType,StringType),StringType())],  # concatenación
    '-':  [((IntType,   IntType),   IntType()),
           ((FloatType, FloatType), FloatType()),
           ((IntType,   FloatType), FloatType()),
           ((FloatType, IntType),   FloatType())],
    '*':  [((IntType,   IntType),   IntType()),
           ((FloatType, FloatType), FloatType()),
           ((IntType,   FloatType), FloatType()),
           ((FloatType, IntType),   FloatType())],
    '/':  [((IntType,   IntType),   IntType()),
           ((FloatType, FloatType), FloatType()),
           ((IntType,   FloatType), FloatType()),
           ((FloatType, IntType),   FloatType())],
    '%':  [((IntType,   IntType),   IntType())],
    '^':  [((IntType,   IntType),   IntType()),
           ((FloatType, FloatType), FloatType())],
    # Relacionales → boolean
    '<':  [((IntType,   IntType),   BoolType()),
           ((FloatType, FloatType), BoolType()),
           ((IntType,   FloatType), BoolType()),
           ((FloatType, IntType),   BoolType()),
           ((CharType,  CharType),  BoolType())],
    '<=': [((IntType,   IntType),   BoolType()),
           ((FloatType, FloatType), BoolType()),
           ((IntType,   FloatType), BoolType()),
           ((FloatType, IntType),   BoolType()),
           ((CharType,  CharType),  BoolType())],
    '>':  [((IntType,   IntType),   BoolType()),
           ((FloatType, FloatType), BoolType()),
           ((IntType,   FloatType), BoolType()),
           ((FloatType, IntType),   BoolType()),
           ((CharType,  CharType),  BoolType())],
    '>=': [((IntType,   IntType),   BoolType()),
           ((FloatType, FloatType), BoolType()),
           ((IntType,   FloatType), BoolType()),
           ((FloatType, IntType),   BoolType()),
           ((CharType,  CharType),  BoolType())],
    # Igualdad — acepta mismos tipos (chequeo especial en visit)
    '==': None,
    '!=': None,
    # Lógicos
    '&&': [((BoolType, BoolType), BoolType())],
    '||': [((BoolType, BoolType), BoolType())],
}

UNARY_RULES = {
    '-':  [(IntType,   IntType()),
           (FloatType, FloatType())],
    '!':  [(BoolType,  BoolType())],
    '++': [(IntType,   IntType()),
           (FloatType, FloatType())],
    '--': [(IntType,   IntType()),
           (FloatType, FloatType())],
}


def resolve_binary(op, lt, rt):
    '''Retorna el tipo resultado o None si la combinación no es válida.'''
    if op in ('==', '!='):
        if type(lt) is type(rt) and not isinstance(lt, (VoidType, ErrorType)):
            return BoolType()
        return None
    rules = BINARY_RULES.get(op, [])
    for (l_cls, r_cls), result in rules:
        if isinstance(lt, l_cls) and isinstance(rt, r_cls):
            return result
    return None


def resolve_unary(op, t):
    rules = UNARY_RULES.get(op, [])
    for t_cls, result in rules:
        if isinstance(t, t_cls):
            return result
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Checker — Visitor con multimethod
# ══════════════════════════════════════════════════════════════════════════════

class Checker:
    def __init__(self, show_symtab=False):
        self.errors      = []
        self.show_symtab = show_symtab

    # ── Reporte de errores ────────────────────────────────────────────────────

    def error(self, msg, lineno=0):
        loc = f' (línea {lineno})' if lineno else ''
        self.errors.append(f'error{loc}: {msg}')

    def _report(self):
        for e in self.errors:
            print(e)
        if self.errors:
            print(f'\nsemantic check: failed  ({len(self.errors)} error(s))')
        else:
            print('semantic check: success')

    # ── Punto de entrada ──────────────────────────────────────────────────────

    @classmethod
    def check(cls, ast, show_symtab=False):
        c = cls(show_symtab)
        global_env = Symtab(name='global')
        c.visit(ast, global_env)
        if show_symtab:
            print('\n── Tabla de símbolos global ──')
            global_env.dump()
        c._report()
        return c

    # ── Utilidades internas ───────────────────────────────────────────────────

    def _declare(self, name, symbol, env, lineno=0):
        try:
            env.add(name, symbol)
        except Symtab.SymbolDefinedError:
            self.error(f"símbolo '{name}' ya definido en este alcance", lineno)

    def _lookup(self, name, env, lineno=0):
        sym = env.get(name)
        if sym is None:
            self.error(f"símbolo '{name}' no definido", lineno)
            return None
        return sym

    def _check_bool_cond(self, t, construct, lineno=0):
        if not isinstance(t, (BoolType, ErrorType)):
            self.error(
                f"la condición del {construct} debe ser boolean, "
                f"se recibió {t}", lineno)

    # ══════════════════════════════════════════════════════════════════════════
    # VISITORS
    # ══════════════════════════════════════════════════════════════════════════

    # ── Programa ──────────────────────────────────────────────────────────────

    @multimethod
    def visit(self, node: Program, env: Symtab):
        for decl in node.declarations:
            self.visit(decl, env)
        if env.get('main') is None:
            self.error("no existe función 'main'")

    # ── Declaraciones ─────────────────────────────────────────────────────────

    @multimethod
    def visit(self, node: VarDeclaration, env: Symtab):
        t = ast_type_to_type(node.type)
        sym = Symbol(node.name, 'variable', t, node)
        self._declare(node.name, sym, env, node.lineno)
        node.type_ = t
        if node.expr is not None:
            et = self.visit(node.expr, env)
            if not isinstance(et, ErrorType) and not isinstance(t, ErrorType):
                if not self._compatible(t, et):
                    self.error(
                        f"no se puede asignar {et} a variable '{node.name}' "
                        f"de tipo {t}", node.lineno)

    @multimethod
    def visit(self, node: ConstDeclaration, env: Symtab):
        et = self.visit(node.expr, env) if node.expr is not None else ErrorType()
        sym = Symbol(node.name, 'const', et, node)
        self._declare(node.name, sym, env, node.lineno)
        node.type_ = et

    @multimethod
    def visit(self, node: ArrayInitDeclaration, env: Symtab):
        t = ast_type_to_type(node.type)
        sym = Symbol(node.name, 'array', t, node)
        self._declare(node.name, sym, env, node.lineno)
        node.type_ = t
        if isinstance(t, ArrayTypeT):
            for elem in node.elements:
                et = self.visit(elem, env)
                if not isinstance(et, ErrorType) and not self._compatible(t.element_type, et):
                    self.error(
                        f"elemento de tipo {et} no es compatible con array de {t.element_type}",
                        node.lineno)

    @multimethod
    def visit(self, node: FuncDeclaration, env: Symtab):
        ft = ast_type_to_type(node.type)   # FuncTypeT
        sym = Symbol(node.name, 'function', ft, node)
        self._declare(node.name, sym, env, node.lineno)
        node.type_ = ft

        if node.body is None:
            return   # declaración sin cuerpo

        # Nuevo alcance para el cuerpo de la función
        func_env = Symtab(env, name=node.name)
        ret_type = ft.return_type if isinstance(ft, FuncTypeT) else VoidType()
        func_env.set_return_type(ret_type)

        # Registrar parámetros
        if isinstance(node.type, FuncType):
            for param in node.type.params:
                pt = ast_type_to_type(param.type)
                psym = Symbol(param.name, 'param', pt, param)
                self._declare(param.name, psym, func_env, node.lineno)
                param.type_ = pt

        # Visitar cuerpo
        stmts = node.body if isinstance(node.body, list) else [node.body]
        has_return = False
        for stmt in stmts:
            self.visit(stmt, func_env)
            if isinstance(stmt, ReturnStmt):
                has_return = True

        # Advertir si función no-void no tiene return explícito en nivel superior
        if not isinstance(ret_type, VoidType) and not has_return:
            self.error(
                f"la función '{node.name}' debe retornar {ret_type} "
                f"pero no tiene return en el nivel superior", node.lineno)

        if self.show_symtab:
            print(f'\n── Alcance de función {node.name!r} ──')
            func_env.dump()

    # ── Statements ────────────────────────────────────────────────────────────

    @multimethod
    def visit(self, node: Block, env: Symtab):
        block_env = Symtab(env, name='block')
        for stmt in node.stmts:
            self.visit(stmt, block_env)

    @multimethod
    def visit(self, node: ExprStmt, env: Symtab):
        self.visit(node.expr, env)

    @multimethod
    def visit(self, node: IfStmt, env: Symtab):
        ct = self.visit(node.cond, env) if node.cond is not None else ErrorType()
        self._check_bool_cond(ct, 'if', node.lineno)
        if node.cons is not None:
            self.visit(node.cons, env)
        if node.altr is not None:
            self.visit(node.altr, env)

    @multimethod
    def visit(self, node: WhileStmt, env: Symtab):
        ct = self.visit(node.cond, env) if node.cond is not None else ErrorType()
        self._check_bool_cond(ct, 'while', node.lineno)
        loop_env = Symtab(env, name='while')
        loop_env.mark_loop()
        if node.body is not None:
            self.visit(node.body, loop_env)

    @multimethod
    def visit(self, node: ForStmt, env: Symtab):
        loop_env = Symtab(env, name='for')
        loop_env.mark_loop()
        if node.init is not None:
            self.visit(node.init, loop_env)
        if node.cond is not None:
            ct = self.visit(node.cond, loop_env)
            self._check_bool_cond(ct, 'for', node.lineno)
        if node.post is not None:
            self.visit(node.post, loop_env)
        if node.body is not None:
            self.visit(node.body, loop_env)

    @multimethod
    def visit(self, node: ReturnStmt, env: Symtab):
        expected = env.expected_return()
        if node.expr is not None:
            et = self.visit(node.expr, env)
            if expected is None:
                pass  # return en contexto global — ignorar
            elif isinstance(expected, VoidType):
                if not isinstance(et, (VoidType, ErrorType)):
                    self.error(
                        f"función void no debe retornar un valor", node.lineno)
            elif not isinstance(et, ErrorType) and not self._compatible(expected, et):
                self.error(
                    f"return de tipo {et}, se esperaba {expected}", node.lineno)
        else:
            if expected and not isinstance(expected, VoidType):
                self.error(
                    f"return vacío en función que debe retornar {expected}",
                    node.lineno)

    @multimethod
    def visit(self, node: BreakStmt, env: Symtab):
        if not env.in_loop():
            self.error("'break' fuera de un bucle for/while", node.lineno)

    @multimethod
    def visit(self, node: ContinueStmt, env: Symtab):
        if not env.in_loop():
            self.error("'continue' fuera de un bucle for/while", node.lineno)

    @multimethod
    def visit(self, node: PrintStmt, env: Symtab):
        for expr in node.exprs:
            self.visit(expr, env)

    # ── Expresiones — retornan Type ───────────────────────────────────────────

    @multimethod
    def visit(self, node: Assign, env: Symtab):
        # Resolver tipo del lvalue
        lt = self._lval_type(node.target, env, node.lineno)
        rt = self.visit(node.value, env)
        node.type_ = lt

        if isinstance(lt, ErrorType) or isinstance(rt, ErrorType):
            return ErrorType()

        # Operadores compuestos: solo tipos numéricos
        if node.op != '=':
            numeric = (IntType, FloatType)
            if not isinstance(lt, numeric):
                self.error(
                    f"operador '{node.op}' no aplica a tipo {lt}", node.lineno)
                return ErrorType()

        if not self._compatible(lt, rt):
            self.error(
                f"no se puede asignar {rt} a {lt} con '{node.op}'", node.lineno)
            return ErrorType()
        return lt

    @multimethod
    def visit(self, node: Binary, env: Symtab):
        lt = self.visit(node.left,  env)
        rt = self.visit(node.right, env)
        if isinstance(lt, ErrorType) or isinstance(rt, ErrorType):
            node.type_ = ErrorType()
            return ErrorType()
        result = resolve_binary(node.op, lt, rt)
        if result is None:
            self.error(
                f"operador '{node.op}' no aplica a tipos {lt} y {rt}", node.lineno)
            node.type_ = ErrorType()
            return ErrorType()
        node.type_ = result
        return result

    @multimethod
    def visit(self, node: Unary, env: Symtab):
        t = self.visit(node.expr, env)
        if isinstance(t, ErrorType):
            node.type_ = ErrorType()
            return ErrorType()
        result = resolve_unary(node.op, t)
        if result is None:
            self.error(
                f"operador unario '{node.op}' no aplica a tipo {t}", node.lineno)
            node.type_ = ErrorType()
            return ErrorType()
        node.type_ = result
        return result

    @multimethod
    def visit(self, node: PrefixOp, env: Symtab):
        t = self.visit(node.expr, env)
        result = resolve_unary(node.op, t)
        if result is None:
            self.error(
                f"operador '{node.op}' no aplica a tipo {t}", node.lineno)
            node.type_ = ErrorType()
            return ErrorType()
        node.type_ = result
        return result

    @multimethod
    def visit(self, node: PostfixOp, env: Symtab):
        t = self.visit(node.expr, env)
        result = resolve_unary(node.op, t)
        if result is None:
            self.error(
                f"operador '{node.op}' no aplica a tipo {t}", node.lineno)
            node.type_ = ErrorType()
            return ErrorType()
        node.type_ = result
        return result

    @multimethod
    def visit(self, node: Call, env: Symtab):
        sym = self._lookup(node.name, env, node.lineno)
        if sym is None:
            node.type_ = ErrorType()
            return ErrorType()

        if not isinstance(sym.type_, FuncTypeT):
            self.error(
                f"'{node.name}' no es una función", node.lineno)
            node.type_ = ErrorType()
            return ErrorType()

        ft = sym.type_
        arg_types = [self.visit(a, env) for a in node.args]

        # Verificar cantidad de argumentos
        if len(arg_types) != len(ft.param_types):
            self.error(
                f"'{node.name}' espera {len(ft.param_types)} argumento(s), "
                f"se recibieron {len(arg_types)}", node.lineno)
        else:
            # Verificar tipos de argumentos
            for i, (at, pt) in enumerate(zip(arg_types, ft.param_types)):
                if not isinstance(at, ErrorType) and not self._compatible(pt, at):
                    self.error(
                        f"argumento {i+1} de '{node.name}': "
                        f"se esperaba {pt}, se recibió {at}", node.lineno)

        node.type_ = ft.return_type
        return ft.return_type

    @multimethod
    def visit(self, node: ArrayIndex, env: Symtab):
        sym = self._lookup(node.name, env, node.lineno)
        if sym is None:
            node.type_ = ErrorType()
            return ErrorType()
        if not isinstance(sym.type_, ArrayTypeT):
            self.error(
                f"'{node.name}' no es un array", node.lineno)
            node.type_ = ErrorType()
            return ErrorType()
        it = self.visit(node.index, env)
        if not isinstance(it, (IntType, ErrorType)):
            self.error(
                f"el índice de array debe ser integer, se recibió {it}", node.lineno)
        node.type_ = sym.type_.element_type
        return sym.type_.element_type

    @multimethod
    def visit(self, node: Variable, env: Symtab):
        sym = self._lookup(node.name, env, node.lineno)
        if sym is None:
            node.type_ = ErrorType()
            return ErrorType()
        node.type_ = sym.type_
        return sym.type_

    # ── Literales ─────────────────────────────────────────────────────────────

    @multimethod
    def visit(self, node: IntLiteral, env: Symtab):
        node.type_ = IntType()
        return node.type_

    @multimethod
    def visit(self, node: FloatLiteral, env: Symtab):
        node.type_ = FloatType()
        return node.type_

    @multimethod
    def visit(self, node: CharLiteral, env: Symtab):
        node.type_ = CharType()
        return node.type_

    @multimethod
    def visit(self, node: StringLiteral, env: Symtab):
        node.type_ = StringType()
        return node.type_

    @multimethod
    def visit(self, node: BoolLiteral, env: Symtab):
        node.type_ = BoolType()
        return node.type_

    # ── Nodo genérico (fallback) ──────────────────────────────────────────────

    @multimethod
    def visit(self, node: Node, env: Symtab):
        # Visitar hijos si el nodo no tiene visitor específico
        for val in node.__dict__.values():
            if isinstance(val, Node):
                self.visit(val, env)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, Node):
                        self.visit(item, env)
        return ErrorType()

    # ══════════════════════════════════════════════════════════════════════════
    # Utilidades privadas
    # ══════════════════════════════════════════════════════════════════════════

    def _compatible(self, expected, got):
        '''Compatibilidad de tipos (estricta, con excepción int↔float).'''
        if type(expected) is type(got):
            return True
        # Promoción numérica: integer es compatible con float
        if isinstance(expected, FloatType) and isinstance(got, IntType):
            return True
        return False

    def _lval_type(self, lval, env, lineno=0):
        '''Resuelve el tipo de un lvalue (LvalID o LvalIndex).'''
        if isinstance(lval, LvalID):
            sym = self._lookup(lval.name, env, lineno)
            return sym.type_ if sym else ErrorType()
        if isinstance(lval, LvalIndex):
            sym = self._lookup(lval.name, env, lineno)
            if sym is None:
                return ErrorType()
            if not isinstance(sym.type_, ArrayTypeT):
                self.error(f"'{lval.name}' no es un array", lineno)
                return ErrorType()
            it = self.visit(lval.index, env)
            if not isinstance(it, (IntType, ErrorType)):
                self.error(f"índice de array debe ser integer, se recibió {it}", lineno)
            return sym.type_.element_type
        # Variable directa (desde expr)
        if isinstance(lval, Variable):
            sym = self._lookup(lval.name, env, lineno)
            return sym.type_ if sym else ErrorType()
        return ErrorType()


# ══════════════════════════════════════════════════════════════════════════════
# Punto de entrada
# ══════════════════════════════════════════════════════════════════════════════

def check(ast, show_symtab=False):
    return Checker.check(ast, show_symtab)


if __name__ == '__main__':
    import sys
    from parser import parse

    if len(sys.argv) < 2:
        raise SystemExit('Usage: python checker.py <archivo.bpp> [--symtab]')

    filename    = sys.argv[1]
    show_symtab = '--symtab' in sys.argv

    txt = open(filename, encoding='utf-8').read()
    ast = parse(txt)
    if ast is None:
        print('No se pudo parsear el archivo.')
        raise SystemExit(1)

    check(ast, show_symtab)

    asadasda