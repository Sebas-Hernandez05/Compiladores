# ircode.py
'''
Generador de Código Intermedio (IRCode / SSA) para B-Minor.

Convierte el AST anotado semánticamente en una secuencia plana de
instrucciones de 3 direcciones (SSA), representadas como tuplas:

    (operación, operandos..., destino)

Ejemplo:
    a = 2 + 3 * 4 - 5
    →
    ('MOVI', 2,  'R1I')
    ('MOVI', 3,  'R2I')
    ('MOVI', 4,  'R3I')
    ('MULI', 'R2I', 'R3I', 'R4I')
    ('ADDI', 'R1I', 'R4I', 'R5I')
    ('MOVI', 5,  'R6I')
    ('SUBI', 'R5I', 'R6I', 'R7I')
    ('STOREI', 'R7I', 'a')

Mapeo de tipos B-Minor → sufijos de instrucción:
    integer / boolean  →  I  (boolean se representa como int 0/1)
    float              →  F
    char / string      →  B  (byte)
    array              →  según tipo elemento
'''

from multimethod import multimeta
from model import *
from checker import (
    IntType, FloatType, BoolType, CharType, StringType, VoidType,
    ArrayTypeT, FuncTypeT,
)


# ─────────────────────────────────────────────────────────────────────────────
# Base Visitor (multimeta para despacho por tipo)
# ─────────────────────────────────────────────────────────────────────────────

class Visitor(metaclass=multimeta):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Generador principal
# ─────────────────────────────────────────────────────────────────────────────

class GenerateCode(Visitor):

    def __init__(self):
        self.code          = []        # Lista de tuplas de instrucciones
        self._temp_count   = 0         # Contador de registros SSA
        self._label_count  = 0         # Contador de etiquetas
        self._in_function  = False     # ¿Estamos dentro de una función?

    # ── Helpers ──────────────────────────────────────────────────────────

    def new_temp(self, suf: str = 'I') -> str:
        '''Genera un nuevo registro SSA único: R1I, R2F, R3B, …'''
        self._temp_count += 1
        return f'R{self._temp_count}{suf}'

    def new_label(self) -> str:
        '''Genera una nueva etiqueta única: L1, L2, …'''
        self._label_count += 1
        return f'L{self._label_count}'

    def emit(self, *instr) -> None:
        '''Agrega una instrucción (tupla) a la lista de código.'''
        self.code.append(instr)

    def type_suffix(self, t) -> str:
        '''
        Convierte un objeto Type del checker al sufijo de instrucción.
            integer | boolean  →  'I'
            float              →  'F'
            char | string      →  'B'
            array              →  sufijo del tipo elemento
            void / None        →  'I'  (fallback)
        '''
        if isinstance(t, FloatType):
            return 'F'
        if isinstance(t, (CharType, StringType)):
            return 'B'
        if isinstance(t, ArrayTypeT):
            return self.type_suffix(t.element_type)
        # integer, boolean, void, None → tratar como int
        return 'I'

    def node_suffix(self, node) -> str:
        '''Obtiene el sufijo a partir del campo .type de un nodo anotado.'''
        t = getattr(node, 'type', None)
        return self.type_suffix(t)

    # ── Programa ──────────────────────────────────────────────────────────

    def visit(self, node: Program):
        for decl in node.declarations:
            self.visit(decl)

    # ── Declaraciones ─────────────────────────────────────────────────────

    def visit(self, node: VarDeclaration):
        t = getattr(node, 'type', None)
        suf = self.type_suffix(t)

        # Arrays: solo declaramos el nombre, los elementos se inicializan aparte
        if isinstance(t, ArrayTypeT):
            # Usamos VARI/ALLOCI como "puntero" al array (simplificado)
            decl_op = f'ALLOC{suf}' if self._in_function else f'VAR{suf}'
            self.emit(decl_op, node.name)
            if node.init is not None:
                init_reg = self.visit(node.init)
                self.emit(f'STORE{suf}', init_reg, node.name)
            return

        # Variables simples
        decl_op = f'ALLOC{suf}' if self._in_function else f'VAR{suf}'
        self.emit(decl_op, node.name)

        if node.init is not None:
            init_reg = self.visit(node.init)
            # Promoción implícita int → float
            if isinstance(t, FloatType) and not isinstance(getattr(node.init, 'type', None), FloatType):
                promoted = self.new_temp('F')
                self.emit('ITOF', init_reg, promoted)
                init_reg = promoted
            self.emit(f'STORE{suf}', init_reg, node.name)

    def visit(self, node: FuncDeclaration):
        prev_in_function = self._in_function
        self._in_function = True

        self.emit('LABEL', node.name)

        # Allocate parameters on the stack
        for p in node.params:
            pt = getattr(p, 'type', None)
            suf = self.type_suffix(pt)
            self.emit(f'ALLOC{suf}', p.name)

        for stmt in node.body:
            self.visit(stmt)

        self._in_function = prev_in_function

    def visit(self, node: FuncPrototype):
        # Solo un prototipo: no genera código
        pass

    def visit(self, node: ClassDeclaration):
        for member in node.members:
            self.visit(member)

    # ── Sentencias ────────────────────────────────────────────────────────

    def visit(self, node: CompoundStatement):
        for stmt in node.stmts:
            self.visit(stmt)

    def visit(self, node: ExprStatement):
        self.visit(node.expr)

    def visit(self, node: IfStatement):
        '''
        if (cond) then_branch [else else_branch]

        IR generado:
            <evaluar cond>
            CBRANCH cond, L_then, L_else
            LABEL   L_then
            <then_branch>
            BRANCH  L_end
            LABEL   L_else       ← siempre (aunque no haya else)
            [<else_branch>]
            LABEL   L_end
        '''
        cond_reg  = self.visit(node.cond)
        l_then    = self.new_label()
        l_else    = self.new_label()
        l_end     = self.new_label()

        self.emit('CBRANCH', cond_reg, l_then, l_else)

        self.emit('LABEL', l_then)
        self.visit(node.then_branch)
        self.emit('BRANCH', l_end)

        self.emit('LABEL', l_else)
        if node.else_branch:
            self.visit(node.else_branch)

        self.emit('LABEL', l_end)

    def visit(self, node: WhileStatement):
        '''
        while (cond) body

        IR generado:
            LABEL  L_test
            <evaluar cond>
            CBRANCH cond, L_body, L_end
            LABEL  L_body
            <body>
            BRANCH L_test
            LABEL  L_end
        '''
        l_test = self.new_label()
        l_body = self.new_label()
        l_end  = self.new_label()

        self.emit('LABEL', l_test)
        cond_reg = self.visit(node.cond)
        self.emit('CBRANCH', cond_reg, l_body, l_end)

        self.emit('LABEL', l_body)
        self.visit(node.body)
        self.emit('BRANCH', l_test)

        self.emit('LABEL', l_end)

    def visit(self, node: ForStatement):
        '''
        for (init; cond; post) body

        IR generado:
            <init>
            LABEL  L_test
            <cond> / CBRANCH
            LABEL  L_body
            <body>
            <post>
            BRANCH L_test
            LABEL  L_end
        '''
        l_test = self.new_label()
        l_body = self.new_label()
        l_end  = self.new_label()

        if node.init:
            self.visit(node.init)

        self.emit('LABEL', l_test)

        if node.cond:
            cond_reg = self.visit(node.cond)
            self.emit('CBRANCH', cond_reg, l_body, l_end)
        # Si no hay condición → loop infinito (solo BRANCH al body)
        else:
            self.emit('BRANCH', l_body)

        self.emit('LABEL', l_body)
        self.visit(node.body)

        if node.post:
            self.visit(node.post)

        self.emit('BRANCH', l_test)
        self.emit('LABEL', l_end)

    def visit(self, node: ReturnStatement):
        if node.expr is not None:
            result = self.visit(node.expr)
            self.emit('RET', result)
        else:
            self.emit('RET')

    def visit(self, node: PrintStatement):
        for expr in node.exprs:
            reg = self.visit(expr)
            suf = self.node_suffix(expr)
            self.emit(f'PRINT{suf}', reg)

    # ── Expresiones ───────────────────────────────────────────────────────

    def visit(self, node: AssignExpr) -> str:
        '''
        Asignación simple (=) y compuesta (+=, -=, *=, /=, %=).
        Devuelve el registro con el valor asignado.
        '''
        suf = self.node_suffix(node.target)

        value_reg = self.visit(node.value)

        # Promoción int → float si el destino es float
        if suf == 'F' and self.node_suffix(node.value) == 'I':
            promoted = self.new_temp('F')
            self.emit('ITOF', value_reg, promoted)
            value_reg = promoted

        if node.op == '=':
            self._store_target(node.target, value_reg, suf)
            return value_reg

        # Operadores compuestos: cargar valor actual, operar, guardar
        current_reg = self._load_target(node.target, suf)
        arith = {'+=': 'ADD', '-=': 'SUB', '*=': 'MUL', '/=': 'DIV', '%=': 'MOD'}
        op_name = arith[node.op]
        result = self.new_temp(suf)
        self.emit(f'{op_name}{suf}', current_reg, value_reg, result)
        self._store_target(node.target, result, suf)
        return result

    def _load_target(self, node, suf: str) -> str:
        '''Genera LOAD* para un lvalue (Identifier o IndexExpr).'''
        if isinstance(node, Identifier):
            reg = self.new_temp(suf)
            self.emit(f'LOAD{suf}', node.name, reg)
            return reg
        if isinstance(node, IndexExpr):
            arr_reg = self.visit(node.expr)
            idx_reg = self.visit(node.index)
            reg = self.new_temp(suf)
            self.emit(f'LOAD{suf}', arr_reg, idx_reg, reg)
            return reg
        # fallback: visitar como expresión
        return self.visit(node)

    def _store_target(self, node, value_reg: str, suf: str) -> None:
        '''Genera STORE* para un lvalue (Identifier o IndexExpr).'''
        if isinstance(node, Identifier):
            self.emit(f'STORE{suf}', value_reg, node.name)
        elif isinstance(node, IndexExpr):
            arr_reg = self.visit(node.expr)
            idx_reg = self.visit(node.index)
            self.emit(f'STORE{suf}', value_reg, arr_reg, idx_reg)

    def visit(self, node: BinaryExpr) -> str:
        '''
        Operaciones binarias: aritméticas, relacionales, lógicas.

        Operadores de comparación → CMPI / CMPF / CMPB → resultado en reg I.
        Operadores lógicos (&& ||) → AND / OR (sin sufijo, operandos enteros).
        '''
        left_reg  = self.visit(node.left)
        right_reg = self.visit(node.right)

        left_suf  = self.node_suffix(node.left)
        right_suf = self.node_suffix(node.right)
        result_suf = self.node_suffix(node)

        # Promoción int → float si un lado es float
        if left_suf == 'F' and right_suf == 'I':
            promoted = self.new_temp('F')
            self.emit('ITOF', right_reg, promoted)
            right_reg = promoted
            right_suf = 'F'
        elif right_suf == 'F' and left_suf == 'I':
            promoted = self.new_temp('F')
            self.emit('ITOF', left_reg, promoted)
            left_reg = promoted
            left_suf = 'F'

        # El sufijo operacional se basa en los operandos
        op_suf = left_suf  # ambos deberían ser iguales ya

        CMP_OPS = {'<', '<=', '>', '>=', '==', '!='}
        LOG_OPS = {'&&': 'AND', '||': 'OR'}

        if node.op in CMP_OPS:
            target = self.new_temp('I')   # comparación siempre devuelve int/bool
            self.emit(f'CMP{op_suf}', node.op, left_reg, right_reg, target)
            return target

        if node.op in LOG_OPS:
            target = self.new_temp('I')
            self.emit(LOG_OPS[node.op], left_reg, right_reg, target)
            return target

        ARITH = {'+': 'ADD', '-': 'SUB', '*': 'MUL', '/': 'DIV', '%': 'MOD'}
        op_name = ARITH.get(node.op, node.op)
        target = self.new_temp(result_suf)
        self.emit(f'{op_name}{op_suf}', left_reg, right_reg, target)
        return target

    def visit(self, node: UnaryExpr) -> str:
        '''
        Operadores unarios prefijos: -, !, ++, --

        - Negación aritmética: 0 - expr
        - Negación lógica:    1 - expr  (asume expr es 0 o 1)
        - Pre-incremento/decremento: suma/resta 1 y guarda de vuelta
        '''
        suf = self.node_suffix(node)
        expr_reg = self.visit(node.expr)

        if node.op == '-':
            zero = self.new_temp(suf)
            zero_val = 0.0 if suf == 'F' else 0
            self.emit(f'MOV{suf}', zero_val, zero)
            target = self.new_temp(suf)
            self.emit(f'SUB{suf}', zero, expr_reg, target)
            return target

        if node.op == '!':
            one = self.new_temp('I')
            self.emit('MOVI', 1, one)
            target = self.new_temp('I')
            self.emit('SUBI', one, expr_reg, target)
            return target

        if node.op in ('++', '--'):
            one = self.new_temp(suf)
            self.emit(f'MOV{suf}', 1, one)
            target = self.new_temp(suf)
            arith = 'ADD' if node.op == '++' else 'SUB'
            self.emit(f'{arith}{suf}', expr_reg, one, target)
            # Guardar el nuevo valor en la variable original
            if isinstance(node.expr, Identifier):
                self.emit(f'STORE{suf}', target, node.expr.name)
            elif isinstance(node.expr, IndexExpr):
                arr_reg = self.visit(node.expr.expr)
                idx_reg = self.visit(node.expr.index)
                self.emit(f'STORE{suf}', target, arr_reg, idx_reg)
            return target

        # Fallback
        return expr_reg

    def visit(self, node: PostfixExpr) -> str:
        '''
        Operadores postfijos: expr++ / expr--

        Devuelve el valor ORIGINAL (antes de incrementar/decrementar),
        pero guarda el nuevo valor en la variable.
        '''
        suf = self.node_suffix(node)
        original_reg = self._load_target(node.expr, suf)  # valor original

        one = self.new_temp(suf)
        self.emit(f'MOV{suf}', 1, one)
        new_val = self.new_temp(suf)
        arith = 'ADD' if node.op == '++' else 'SUB'
        self.emit(f'{arith}{suf}', original_reg, one, new_val)

        # Guardar el nuevo valor
        if isinstance(node.expr, Identifier):
            self.emit(f'STORE{suf}', new_val, node.expr.name)
        elif isinstance(node.expr, IndexExpr):
            arr_reg = self.visit(node.expr.expr)
            idx_reg = self.visit(node.expr.index)
            self.emit(f'STORE{suf}', new_val, arr_reg, idx_reg)

        return original_reg   # ← postfix devuelve el valor ANTES del cambio

    def visit(self, node: CallExpr) -> str:
        '''
        Llamada a función: evalúa argumentos y emite CALL.
        '''
        arg_regs = [self.visit(a) for a in node.args]
        suf = self.node_suffix(node)
        target = self.new_temp(suf)
        name = node.callee.name if isinstance(node.callee, Identifier) else '?'
        self.emit('CALL', name, *arg_regs, target)
        return target

    def visit(self, node: IndexExpr) -> str:
        '''Acceso a array: arr[i] → LOAD* arr, idx, target'''
        arr_reg = self.visit(node.expr)
        idx_reg = self.visit(node.index)
        suf = self.node_suffix(node)
        target = self.new_temp(suf)
        self.emit(f'LOAD{suf}', arr_reg, idx_reg, target)
        return target

    def visit(self, node: MemberExpr) -> str:
        '''Acceso a miembro de objeto: obj.name (extensión OOP)'''
        obj_reg = self.visit(node.obj)
        target = self.new_temp('I')
        self.emit('GETATTR', obj_reg, node.member, target)
        return target

    def visit(self, node: GroupExpr) -> str:
        return self.visit(node.expr)

    # ── Literales ─────────────────────────────────────────────────────────

    def visit(self, node: IntLiteral) -> str:
        target = self.new_temp('I')
        self.emit('MOVI', node.value, target)
        return target

    def visit(self, node: FloatLiteral) -> str:
        target = self.new_temp('F')
        self.emit('MOVF', node.value, target)
        return target

    def visit(self, node: CharLiteral) -> str:
        target = self.new_temp('B')
        self.emit('MOVB', node.value, target)
        return target

    def visit(self, node: StringLiteral) -> str:
        target = self.new_temp('B')
        self.emit('MOVB', node.value, target)
        return target

    def visit(self, node: BoolLiteral) -> str:
        # Booleano se representa como entero: true=1, false=0
        target = self.new_temp('I')
        self.emit('MOVI', 1 if node.value else 0, target)
        return target

    def visit(self, node: ArrayLiteral) -> str:
        '''
        Literal de array {e1, e2, ...}.
        Emite cada elemento y genera una instrucción ARRAY pseudo-op.
        '''
        elem_regs = [self.visit(e) for e in node.elements]
        target = self.new_temp('I')
        self.emit('ARRAY', *elem_regs, target)
        return target

    def visit(self, node: Identifier) -> str:
        '''
        Referencia a variable → LOAD* name, target
        '''
        suf = self.node_suffix(node)
        target = self.new_temp(suf)
        self.emit(f'LOAD{suf}', node.name, target)
        return target

    def visit(self, node: ThisExpr) -> str:
        target = self.new_temp('I')
        self.emit('LOADI', 'this', target)
        return target

    def visit(self, node: SuperExpr) -> str:
        target = self.new_temp('I')
        self.emit('LOADI', 'super', target)
        return target


# ─────────────────────────────────────────────────────────────────────────────
# Funciones de utilidad
# ─────────────────────────────────────────────────────────────────────────────

def generate_ircode(ast) -> list:
    '''Punto de entrada: recorre el AST y retorna la lista de instrucciones.'''
    gen = GenerateCode()
    gen.visit(ast)
    return gen.code


def print_ircode(code: list, indent: int = 2) -> None:
    '''Imprime el IRCode de forma legible.'''
    pad = ' ' * indent
    for instr in code:
        op, *args = instr
        # Las etiquetas van sin sangría
        if op == 'LABEL':
            print(f'\n{args[0]}:')
        else:
            args_str = ',  '.join(str(a) for a in args)
            print(f'{pad}{op:<10}  {args_str}')


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    from lexer    import Lexer
    from parser   import Parser
    from checker  import Checker

    if len(sys.argv) < 2:
        print('Uso: python ircode.py <archivo.bminor> [--tuples]')
        sys.exit(1)

    source   = open(sys.argv[1], encoding='utf-8').read()
    lexer    = Lexer()
    parser   = Parser()
    ast      = parser.parse(lexer.tokenize(source))

    if ast is None:
        print('Error: el parser no produjo un AST.')
        sys.exit(1)

    checker = Checker()
    ok = checker.check(ast)
    if not ok:
        print('Errores semánticos detectados:')
        for err in checker.errors:
            print(' ', err)
        sys.exit(1)

    code = generate_ircode(ast)

    if '--tuples' in sys.argv:
        # Modo depuración: imprime las tuplas crudas
        for instr in code:
            print(instr)
    else:
        print_ircode(code)