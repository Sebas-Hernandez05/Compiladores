from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from rich import print

from model import *
from checker import (
    INT, FLOAT, BOOL, CHAR, STRING, VOID,
    IntType, FloatType, BoolType, CharType, StringType, VoidType,
    ArrayTypeT, FuncTypeT,
    Type,
    BUILTIN_TYPES,
)

# ===================================================
# IR model
# ===================================================

Instruction = tuple


@dataclass
class Storage:
    """
    Describe dónde vive un símbolo durante la generación de IR.
    """
    name: str
    ty: Type
    is_global: bool = False
    is_param: bool = False
    is_const: bool = False


@dataclass
class IRFunction:
    name: str
    params: list[tuple[str, Type]]
    return_type: Type
    instructions: list[Instruction] = field(default_factory=list)


@dataclass
class IRProgram:
    globals: list[Instruction] = field(default_factory=list)
    functions: list[IRFunction] = field(default_factory=list)

    def format(self) -> str:
        out: list[str] = []
        if self.globals:
            out.append("# Globals")
            for inst in self.globals:
                out.append(format_instruction(inst))
            out.append("")

        for fn in self.functions:
            params = ", ".join(f"{name}:{ty}" for name, ty in fn.params)
            out.append(f"function {fn.name}({params}) -> {fn.return_type}")
            for inst in fn.instructions:
                out.append(f"  {format_instruction(inst)}")
            out.append("")
        return "\n".join(out).rstrip()


# ===================================================
# Pretty printing
# ===================================================


def format_instruction(inst: Instruction) -> str:
    op = inst[0]
    if len(inst) == 1:
        return op
    args = ", ".join(
        repr(x) if isinstance(x, str) and (x.startswith("L") or x.startswith("str")) else str(x)
        for x in inst[1:]
    )
    return f"{op} {args}"


# ===================================================
# Generator
# ===================================================


class IRCodeGen(Visitor):
    """
    Generador de código IR para el lenguaje B-Minor.

    Toma el AST producido por parser.py (tipos de model.py) y genera un
    IRProgram compuesto de instrucciones SSA en forma de tuplas, compatible
    con el intérprete irinterp.py.

    Soporta:
    - Variables globales y locales (int, float, char/byte, bool, string)
    - Funciones con parámetros y retorno
    - Expresiones aritméticas, relacionales y lógicas
    - Asignaciones simples y compuestas (+=, -=, *=, /=)
    - Operadores unarios prefijos (-x, !x, ++x, --x)
    - Operadores postfijos (x++, x--)
    - Sentencias if/else, while, for
    - Llamadas a función
    - print con múltiples expresiones
    - Strings (vía DATAS + ADDR + PRINTS)
    - Acceso básico a arreglos (LOAD_ARR / STORE_ARR; el intérprete no las soporta
      de forma nativa, pero quedan en el IR para extensión futura)
    """

    def __init__(self):
        self.program = IRProgram()
        self.current_function: Optional[IRFunction] = None
        self.current_return_type: Type = VOID
        self.temp_count = 0
        self.label_count = 0
        self.string_count = 0
        self.scopes: list[dict[str, Storage]] = []

    @classmethod
    def generate(cls, node: Program) -> IRProgram:
        gen = cls()
        gen.visit(node)
        return gen.program

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------

    def new_temp(self) -> str:
        self.temp_count += 1
        return f"R{self.temp_count}"

    def new_label(self, prefix: str = "L") -> str:
        self.label_count += 1
        return f"{prefix}{self.label_count}"

    def new_string_label(self) -> str:
        self.string_count += 1
        return f"str{self.string_count}"

    def emit(self, *inst) -> None:
        inst = tuple(inst)
        if self.current_function is None:
            self.program.globals.append(inst)
        else:
            self.current_function.instructions.append(inst)

    def push_scope(self) -> None:
        self.scopes.append({})

    def pop_scope(self) -> None:
        if self.scopes:
            self.scopes.pop()

    def bind(self, storage: Storage) -> None:
        if not self.scopes:
            self.push_scope()
        self.scopes[-1][storage.name] = storage

    def lookup(self, name: str) -> Optional[Storage]:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    # -------------------------------------------------
    # Type resolution
    # -------------------------------------------------

    def resolve_type(self, type_node) -> Type:
        """Convierte un nodo de tipo del AST en un objeto Type interno."""
        if isinstance(type_node, SimpleType):
            return BUILTIN_TYPES.get(type_node.name, INT)
        if isinstance(type_node, ArrayType):
            elem = self.resolve_type(type_node.element_type)
            return ArrayTypeT(elem)
        if isinstance(type_node, UserType):
            return INT  # fallback conservador
        return INT

    def infer_type(self, node: Optional[Node]) -> Type:
        """
        Infiere el tipo de un nodo de expresión.
        Primero consulta el campo .type anotado por el checker;
        si no existe, hace inferencia básica por tipo de nodo.
        """
        if node is None:
            return VOID
        ty = getattr(node, "type", None)
        if isinstance(ty, Type):
            return ty
        # Inferencia por clase de nodo
        if isinstance(node, IntLiteral):
            return INT
        if isinstance(node, FloatLiteral):
            return FLOAT
        if isinstance(node, BoolLiteral):
            return BOOL
        if isinstance(node, CharLiteral):
            return CHAR
        if isinstance(node, StringLiteral):
            return STRING
        if isinstance(node, Identifier):
            storage = self.lookup(node.name)
            if storage:
                return storage.ty
        return INT  # conservador

    # -------------------------------------------------
    # Opcode selectors
    # -------------------------------------------------

    def type_suffix(self, ty: Type) -> str:
        """
        Sufijo de tipo para construir opcodes:
          IntType / BoolType  -> 'I'
          FloatType           -> 'F'
          CharType            -> 'B'  (byte)
          StringType          -> 'S'
        """
        if isinstance(ty, (IntType, BoolType)):
            return "I"
        if isinstance(ty, FloatType):
            return "F"
        if isinstance(ty, CharType):
            return "B"
        if isinstance(ty, StringType):
            return "S"
        # ArrayType, FuncType, UserType -> fallback entero
        return "I"

    def move_opcode(self, ty: Type) -> str:
        return f"MOV{self.type_suffix(ty)}"

    def load_opcode(self, ty: Type) -> str:
        return f"LOAD{self.type_suffix(ty)}"

    def store_opcode(self, ty: Type) -> str:
        return f"STORE{self.type_suffix(ty)}"

    def alloc_opcode(self, ty: Type) -> str:
        return f"ALLOC{self.type_suffix(ty)}"

    def var_opcode(self, ty: Type) -> str:
        return f"VAR{self.type_suffix(ty)}"

    def print_opcode(self, ty: Type) -> str:
        return f"PRINT{self.type_suffix(ty)}"

    def cmp_opcode(self, ty: Type) -> str:
        return f"CMP{self.type_suffix(ty)}"

    def arith_opcode(self, oper: str, ty: Type) -> str:
        suffix = self.type_suffix(ty)
        table = {
            "+": f"ADD{suffix}",
            "-": f"SUB{suffix}",
            "*": f"MUL{suffix}",
            "/": f"DIV{suffix}",
        }
        if oper not in table:
            raise NotImplementedError(f"Aritmética no soportada: {oper!r}")
        return table[oper]

    # -------------------------------------------------
    # Program
    # -------------------------------------------------

    def visit(self, node: Program):
        self.push_scope()

        # Primera pasada: registrar todos los nombres globales.
        for decl in node.declarations:
            if isinstance(decl, VarDeclaration):
                ty = self.resolve_type(decl.type_spec)
                self.bind(Storage(decl.name, ty, is_global=True))
            elif isinstance(decl, (FuncDeclaration, FuncPrototype)):
                ret_ty = self.resolve_type(decl.return_type) if decl.return_type else VOID
                param_types = [self.resolve_type(p.type_spec) for p in decl.params]
                self.bind(Storage(decl.name, FuncTypeT(ret_ty, param_types), is_global=True))

        # Segunda pasada: emitir IR.
        for decl in node.declarations:
            self.visit(decl)

        self.pop_scope()
        return self.program

    # -------------------------------------------------
    # Declarations
    # -------------------------------------------------

    def visit(self, node: VarDeclaration):
        ty = self.resolve_type(node.type_spec)

        if isinstance(ty, ArrayTypeT):
            # Arrays: declarar, inicializar elemento a elemento si hay literal.
            self.bind(Storage(node.name, ty, is_global=(self.current_function is None)))
            if self.current_function is None:
                self.emit("VARI", node.name)   # placeholder global
            else:
                self.emit("ALLOCI", node.name)  # placeholder local
            if node.init is not None and isinstance(node.init, ArrayLiteral):
                for idx, elem in enumerate(node.init.elements):
                    val_reg = self.visit(elem)
                    idx_reg = self.new_temp()
                    self.emit("MOVI", idx, idx_reg)
                    self.emit("STORE_ARR", val_reg, node.name, idx_reg)
            return

        if self.current_function is None:
            # Variable global
            self.emit(self.var_opcode(ty), node.name)
            if node.init is not None:
                src = self.visit(node.init)
                self.emit(self.store_opcode(ty), src, node.name)
        else:
            # Variable local
            self.bind(Storage(node.name, ty))
            self.emit(self.alloc_opcode(ty), node.name)
            if node.init is not None:
                src = self.visit(node.init)
                self.emit(self.store_opcode(ty), src, node.name)

    def visit(self, node: FuncPrototype):
        # Los prototipos no generan IR, solo se registran en el scope global
        # (ya se hizo en la primera pasada de visit(Program)).
        pass

    def visit(self, node: FuncDeclaration):
        prev_fn = self.current_function
        prev_ret = self.current_return_type

        ret_ty = self.resolve_type(node.return_type) if node.return_type else VOID
        param_list = [(p.name, self.resolve_type(p.type_spec)) for p in node.params]

        fn = IRFunction(name=node.name, params=param_list, return_type=ret_ty)
        self.program.functions.append(fn)
        self.current_function = fn
        self.current_return_type = ret_ty

        self.push_scope()

        # Registrar y alojar parámetros (setdefault en el intérprete
        # evita sobrescribir los valores ya pasados).
        for p, (pname, pty) in zip(node.params, param_list):
            self.bind(Storage(pname, pty, is_param=True))
            if not isinstance(pty, (VoidType,)):
                self.emit(self.alloc_opcode(pty), pname)

        # Cuerpo de la función.
        for stmt in node.body:
            self.visit(stmt)

        # Retorno implícito void.
        if isinstance(ret_ty, VoidType):
            if not fn.instructions or fn.instructions[-1][0] != "RET":
                self.emit("RET")

        self.pop_scope()
        self.current_function = prev_fn
        self.current_return_type = prev_ret

    def visit(self, node: ClassDeclaration):
        # Las clases no están soportadas en este generador.
        pass

    # -------------------------------------------------
    # Statements
    # -------------------------------------------------

    def visit(self, node: CompoundStatement):
        self.push_scope()
        for stmt in node.stmts:
            self.visit(stmt)
        self.pop_scope()

    def visit(self, node: ExprStatement):
        self.visit(node.expr)

    def visit(self, node: PrintStatement):
        """
        Emite PRINTI / PRINTF / PRINTB / PRINTS por cada expresión de la lista.
        """
        for expr in node.exprs:
            reg = self.visit(expr)
            if reg is None:
                continue
            ty = self.infer_type(expr)
            self.emit(self.print_opcode(ty), reg)

    def visit(self, node: IfStatement):
        """
        if (cond) then_branch [else else_branch]

        Genera:
            CBRANCH cond_reg, THEN, ELSE_or_END
          THEN:
            ...
            BRANCH END
          ELSE:          ; solo si hay else_branch
            ...
            BRANCH END
          END:
        """
        then_label = self.new_label("IF_THEN")
        else_label = self.new_label("IF_ELSE")
        end_label  = self.new_label("IF_END")

        cond_reg = self.visit(node.cond)
        if node.else_branch:
            self.emit("CBRANCH", cond_reg, then_label, else_label)
        else:
            self.emit("CBRANCH", cond_reg, then_label, end_label)

        self.emit("LABEL", then_label)
        self.visit(node.then_branch)
        self.emit("BRANCH", end_label)

        if node.else_branch:
            self.emit("LABEL", else_label)
            self.visit(node.else_branch)
            self.emit("BRANCH", end_label)

        self.emit("LABEL", end_label)

    def visit(self, node: WhileStatement):
        """
        while (cond) body

        Genera:
          TEST:
            CBRANCH cond_reg, BODY, END
          BODY:
            ...
            BRANCH TEST
          END:
        """
        test_label = self.new_label("WHILE_TEST")
        body_label = self.new_label("WHILE_BODY")
        end_label  = self.new_label("WHILE_END")

        self.emit("LABEL", test_label)
        cond_reg = self.visit(node.cond)
        self.emit("CBRANCH", cond_reg, body_label, end_label)

        self.emit("LABEL", body_label)
        self.visit(node.body)
        self.emit("BRANCH", test_label)

        self.emit("LABEL", end_label)

    def visit(self, node: ForStatement):
        """
        for (init ; cond ; post) body

        Genera:
            init
          TEST:
            [CBRANCH cond_reg, BODY, END]
          BODY:
            body
            post
            BRANCH TEST
          END:
        """
        test_label = self.new_label("FOR_TEST")
        body_label = self.new_label("FOR_BODY")
        end_label  = self.new_label("FOR_END")

        self.push_scope()

        if node.init is not None:
            self.visit(node.init)

        self.emit("LABEL", test_label)

        if node.cond is not None:
            cond_reg = self.visit(node.cond)
            self.emit("CBRANCH", cond_reg, body_label, end_label)
        else:
            self.emit("BRANCH", body_label)

        self.emit("LABEL", body_label)
        self.visit(node.body)

        if node.post is not None:
            self.visit(node.post)

        self.emit("BRANCH", test_label)
        self.emit("LABEL", end_label)

        self.pop_scope()

    def visit(self, node: ReturnStatement):
        if node.expr is None:
            self.emit("RET")
        else:
            reg = self.visit(node.expr)
            self.emit("RET", reg)

    # -------------------------------------------------
    # Expressions
    # -------------------------------------------------

    def visit(self, node: AssignExpr):
        """
        Soporta:
          - x = expr            (asignación simple)
          - x += expr  etc.     (asignación compuesta)
          - arr[i] = expr       (asignación a arreglo)
        """
        # --- asignación a variable ---
        if isinstance(node.target, Identifier):
            storage = self.lookup(node.target.name)
            if storage is None:
                return self.visit(node.value)

            if node.op == "=":
                src = self.visit(node.value)
                self.emit(self.store_opcode(storage.ty), src, storage.name)
                return src

            # Operadores compuestos: +=, -=, *=, /=
            base_op = node.op[:-1]          # '+=' -> '+'
            old_reg = self.new_temp()
            self.emit(self.load_opcode(storage.ty), storage.name, old_reg)
            val_reg = self.visit(node.value)
            out = self.new_temp()
            self.emit(self.arith_opcode(base_op, storage.ty), old_reg, val_reg, out)
            self.emit(self.store_opcode(storage.ty), out, storage.name)
            return out

        # --- asignación a arreglo arr[i] = expr ---
        if isinstance(node.target, IndexExpr) and isinstance(node.target.expr, Identifier):
            arr_name = node.target.expr.name
            idx_reg  = self.visit(node.target.index)
            val_reg  = self.visit(node.value)
            self.emit("STORE_ARR", val_reg, arr_name, idx_reg)
            return val_reg

        # Fallback
        return self.visit(node.value)

    def visit(self, node: BinaryExpr):
        left_reg  = self.visit(node.left)
        right_reg = self.visit(node.right)
        left_ty   = self.infer_type(node.left)
        out = self.new_temp()

        # Aritmética básica
        if node.op in {"+", "-", "*", "/"}:
            self.emit(self.arith_opcode(node.op, left_ty), left_reg, right_reg, out)
            return out

        # Módulo: a % b  ->  a - (a / b) * b
        if node.op == "%":
            tmp_div = self.new_temp()
            tmp_mul = self.new_temp()
            suf = self.type_suffix(left_ty)
            self.emit(f"DIV{suf}", left_reg, right_reg, tmp_div)
            self.emit(f"MUL{suf}", tmp_div, right_reg, tmp_mul)
            self.emit(f"SUB{suf}", left_reg, tmp_mul, out)
            return out

        # Comparaciones  <  <=  >  >=  ==  !=
        if node.op in {"<", "<=", ">", ">=", "==", "!="}:
            self.emit(self.cmp_opcode(left_ty), node.op, left_reg, right_reg, out)
            return out

        # Lógicos  &&  ||
        if node.op == "&&":
            self.emit("AND", left_reg, right_reg, out)
            return out
        if node.op == "||":
            self.emit("OR",  left_reg, right_reg, out)
            return out

        raise NotImplementedError(f"BinaryExpr operador no soportado: {node.op!r}")

    def visit(self, node: UnaryExpr):
        """
        Prefijos: -x  !x  ++x  --x
        Para ++ y -- también almacena el nuevo valor en la variable fuente.
        """
        ty = self.infer_type(node.expr)
        suf = self.type_suffix(ty)

        if node.op == "-":
            expr_reg = self.visit(node.expr)
            zero = self.new_temp()
            out  = self.new_temp()
            self.emit(self.move_opcode(ty), 0, zero)
            self.emit(f"SUB{suf}", zero, expr_reg, out)
            return out

        if node.op == "!":
            expr_reg = self.visit(node.expr)
            one = self.new_temp()
            out = self.new_temp()
            self.emit("MOVI", 1, one)
            self.emit("XOR", expr_reg, one, out)
            return out

        if node.op in {"++", "--"}:
            expr_reg = self.visit(node.expr)
            one = self.new_temp()
            out = self.new_temp()
            self.emit(self.move_opcode(ty), 1, one)
            if node.op == "++":
                self.emit(f"ADD{suf}", expr_reg, one, out)
            else:
                self.emit(f"SUB{suf}", expr_reg, one, out)
            # Escribir de vuelta si es una variable
            if isinstance(node.expr, Identifier):
                storage = self.lookup(node.expr.name)
                if storage:
                    self.emit(self.store_opcode(storage.ty), out, storage.name)
            return out

        raise NotImplementedError(f"UnaryExpr operador no soportado: {node.op!r}")

    def visit(self, node: PostfixExpr):
        """
        Postfijos: x++  x--
        Retorna el valor ANTES del incremento/decremento (semántica C estándar).
        """
        ty  = self.infer_type(node.expr)
        suf = self.type_suffix(ty)

        old_val = self.visit(node.expr)   # carga valor actual
        one = self.new_temp()
        new_val = self.new_temp()
        self.emit(self.move_opcode(ty), 1, one)

        if node.op == "++":
            self.emit(f"ADD{suf}", old_val, one, new_val)
        else:
            self.emit(f"SUB{suf}", old_val, one, new_val)

        # Guardar nuevo valor en la variable
        if isinstance(node.expr, Identifier):
            storage = self.lookup(node.expr.name)
            if storage:
                self.emit(self.store_opcode(storage.ty), new_val, storage.name)

        return old_val   # el postfijo devuelve el valor VIEJO

    def visit(self, node: CallExpr):
        """
        Llama a una función: callee(arg0, ..., argN)
        Formato de instrucción CALL esperado por irinterp.py:
            CALL fname, R_arg0, ..., R_argN [, R_target]
        El intérprete determina cuántos son args por el len(params) de la función.
        """
        if not isinstance(node.callee, Identifier):
            raise NotImplementedError("CallExpr: solo se soportan llamadas por nombre")

        fname = node.callee.name
        arg_regs = [self.visit(arg) for arg in node.args]

        # Determinar tipo de retorno
        storage = self.lookup(fname)
        if storage and isinstance(storage.ty, FuncTypeT):
            ret_ty = storage.ty.return_type
        else:
            ret_ty = VOID

        if isinstance(ret_ty, VoidType):
            self.emit("CALL", fname, *arg_regs)
            return None
        else:
            out = self.new_temp()
            self.emit("CALL", fname, *arg_regs, out)
            return out

    def visit(self, node: IndexExpr):
        """
        Acceso a arreglo: arr[idx]
        Emite LOAD_ARR (extensión del IR base).
        """
        idx_reg = self.visit(node.index)

        if isinstance(node.expr, Identifier):
            arr_name = node.expr.name
            storage  = self.lookup(arr_name)
            elem_ty  = storage.ty.element_type if (storage and isinstance(storage.ty, ArrayTypeT)) else INT
            out = self.new_temp()
            self.emit("LOAD_ARR", arr_name, idx_reg, out)
            return out

        # Fallback genérico
        out = self.new_temp()
        self.emit("MOVI", 0, out)
        return out

    def visit(self, node: GroupExpr):
        return self.visit(node.expr)

    def visit(self, node: MemberExpr):
        # Acceso a miembro de clase: no implementado
        tmp = self.new_temp()
        self.emit("MOVI", 0, tmp)
        return tmp

    # -------------------------------------------------
    # Literals
    # -------------------------------------------------

    def visit(self, node: IntLiteral):
        tmp = self.new_temp()
        self.emit("MOVI", int(node.value), tmp)
        return tmp

    def visit(self, node: FloatLiteral):
        tmp = self.new_temp()
        self.emit("MOVF", float(node.value), tmp)
        return tmp

    def visit(self, node: BoolLiteral):
        tmp = self.new_temp()
        self.emit("MOVI", 1 if node.value else 0, tmp)
        return tmp

    def visit(self, node: CharLiteral):
        """
        Los chars se representan como bytes (MOVB).
        Soporta escapes simples: \\n, \\t, \\r, \\\\, \\', \\".
        """
        tmp = self.new_temp()
        val = node.value
        if isinstance(val, str):
            escape_map = {
                "\\n": 10, "\\t": 9, "\\r": 13,
                "\\\\": 92, "\\'": 39, '\\"': 34, "\\0": 0,
            }
            if val in escape_map:
                byte_val = escape_map[val]
            elif len(val) == 1:
                byte_val = ord(val)
            else:
                byte_val = ord(val[0])
        else:
            byte_val = int(val)
        self.emit("MOVB", byte_val, tmp)
        return tmp

    def visit(self, node: StringLiteral):
        """
        Los strings se almacenan en el segmento de datos como arreglos de bytes
        terminados en cero (convención C).

        Emite en globals:
            DATAS  str_label  b0 b1 ... bN 0

        Luego, en la función actual:
            ADDR   str_label  R_tmp
        """
        raw = node.value
        # Quitar comillas envolventes si las hay
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]

        # Procesar secuencias de escape de Python (coincide con B-minor)
        try:
            processed = bytes(raw, "utf-8").decode("unicode_escape")
        except Exception:
            processed = raw

        byte_vals = [ord(c) for c in processed] + [0]  # null-terminated

        # Crear etiqueta global única
        label = self.new_string_label()
        self.program.globals.append(("DATAS", label, *byte_vals))

        # Cargar dirección del string en un temporal
        tmp = self.new_temp()
        self.emit("ADDR", label, tmp)
        return tmp

    def visit(self, node: Identifier):
        """
        Carga el valor de una variable en un nuevo temporal.
        Si el identificador no está en el scope (p.ej. nombre de función usado
        solo como callee), devuelve un temporal con 0 como fallback.
        """
        storage = self.lookup(node.name)
        if storage is None:
            tmp = self.new_temp()
            self.emit("MOVI", 0, tmp)
            return tmp

        # Los arreglos no se cargan con LOADI; devolver el nombre directamente
        if isinstance(storage.ty, ArrayTypeT):
            return storage.name

        tmp = self.new_temp()
        self.emit(self.load_opcode(storage.ty), storage.name, tmp)
        return tmp

    def visit(self, node: ArrayLiteral):
        """
        Literal de arreglo {e1, e2, ...}.
        Devuelve la lista de registros de cada elemento
        (el contexto de la llamada decide cómo usarlos).
        """
        return [self.visit(e) for e in node.elements]

    def visit(self, node: ThisExpr):
        tmp = self.new_temp()
        self.emit("MOVI", 0, tmp)
        return tmp

    def visit(self, node: SuperExpr):
        tmp = self.new_temp()
        self.emit("MOVI", 0, tmp)
        return tmp


# ===================================================
# CLI demo
# ===================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        # Demo embebida: compila un programa pequeño de prueba.
        from model import (
            Program, FuncDeclaration, Parameter, SimpleType,
            VarDeclaration, ReturnStatement, PrintStatement,
            BinaryExpr, IntLiteral, Identifier, BoolLiteral,
        )
        from checker import INT, VOID, BOOL

        # Programa de ejemplo:
        #   main: function integer() = {
        #       x: integer = 2 + 3 * 4;
        #       print x;
        #       return 0;
        #   }
        ast = Program([
            FuncDeclaration(
                name="main",
                params=[],
                return_type=SimpleType("integer"),
                body=[
                    VarDeclaration(
                        type_spec=SimpleType("integer"),
                        name="x",
                        init=BinaryExpr(
                            left=IntLiteral(2),
                            op="+",
                            right=BinaryExpr(
                                left=IntLiteral(3),
                                op="*",
                                right=IntLiteral(4),
                            ),
                        ),
                    ),
                    PrintStatement(exprs=[Identifier(name="x")]),
                    ReturnStatement(expr=IntLiteral(0)),
                ],
            )
        ])

        # Anotar tipos manualmente (normalmente lo hace el checker)
        ast.declarations[0].body[0].init.type = INT
        ast.declarations[0].body[0].init.right.type = INT
        ast.declarations[0].body[0].type = INT
        ast.declarations[0].body[1].exprs[0].type = INT

        ir = IRCodeGen.generate(ast)
        print(ir.format())
        sys.exit(0)

    # Modo normal: leer desde archivo .bminor
    from lexer   import Lexer
    from parser  import Parser
    from checker import Checker

    source_path = sys.argv[1]
    source = open(source_path, encoding="utf-8").read()

    lexer  = Lexer()
    parser = Parser()
    ast    = parser.parse(lexer.tokenize(source))

    if ast is None:
        print("[red]El parser no produjo un AST[/red]")
        sys.exit(1)

    checker = Checker()
    ok = checker.check(ast)
    for msg in checker.errors:
        print(f"[yellow]{msg}[/yellow]")

    if not ok:
        print("[red]El checker reportó errores; generando IR de todos modos...[/red]")

    ir = IRCodeGen.generate(ast)
    print(ir.format())