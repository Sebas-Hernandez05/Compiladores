from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from rich import print

from model import *

# ===================================================
# IR model
# ===================================================

Instruction = tuple


@dataclass
class Storage:
    """
    Describe dónde vive un símbolo durante la generación de IR.

    El objetivo es que el estudiante tenga una estructura simple para
    consultar tipo y categoría del símbolo (global, parámetro, constante).
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
        repr(x) if isinstance(x, str) and x.startswith("L") else str(x)
        for x in inst[1:]
    )
    return f"{op} {args}"


# ===================================================
# Generator
# ===================================================


class IRCodeGen(Visitor):
    """
    Plantilla base para el proyecto de IRCode.

    Esta versión deja aproximadamente la mitad del trabajo resuelto:

    Ya implementado:
    - estructura del programa IR
    - manejo de temporales y labels
    - scopes y lookup de símbolos
    - declaración de variables y constantes
    - carga de literales enteros, booleanos y chars
    - lectura de variables (VarLoc)
    - impresión simple
    - retorno simple
    - parte de la selección de opcodes

    Pendiente para estudiantes:
    - completar BinOp
    - completar UnaryOp
    - completar Assignment compuesto
    - completar IfStmt / WhileStmt / ForStmt
    - completar FuncCall
    - arreglos y strings
    - conversiones adicionales y mejoras del IR

    Sugerencia pedagógica:
    1. Hacer primero expresiones aritméticas.
    2. Luego comparaciones.
    3. Después control de flujo.
    4. Finalmente llamadas, arreglos y extensiones.
    """

    def __init__(self):
        self.program = IRProgram()
        self.current_function: Optional[IRFunction] = None
        self.current_return_type: Type = VOID
        self.temp_count = 0
        self.label_count = 0
        self.scopes: list[dict[str, Storage]] = []

    @classmethod
    def generate(cls, node: Program) -> IRProgram:
        gen = cls()
        gen.visit(node)
        return gen.program

    # -------------------------------------------------
    # helpers básicos
    # -------------------------------------------------

    def new_temp(self) -> str:
        self.temp_count += 1
        return f"R{self.temp_count}"

    def new_label(self, prefix: str = "L") -> str:
        self.label_count += 1
        return f"{prefix}{self.label_count}"

    def emit(self, *inst) -> None:
        inst = tuple(inst)
        if self.current_function is None:
            self.program.globals.append(inst)
        else:
            self.current_function.instructions.append(inst)

    def push_scope(self) -> None:
        self.scopes.append({})

    def pop_scope(self) -> None:
        self.scopes.pop()

    def bind(self, storage: Storage) -> None:
        if not self.scopes:
            self.push_scope()
        self.scopes[-1][storage.name] = storage

    def lookup(self, name: str) -> Storage:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise NameError(f"Nombre no resuelto en IRCodeGen: {name}")

    def infer_type(self, node: Optional[Node]) -> Type:
        """
        Inferencia mínima para que el generador pueda escoger opcodes.

        Nota: aquí se asume que el checker semántico ya pasó antes.
        """
        if node is None:
            return VOID

        ty = getattr(node, "type", None)
        if isinstance(ty, Type):
            return ty

        if isinstance(node, IntegerLiteral):
            return INT
        if isinstance(node, BooleanLiteral):
            return BOOL
        if isinstance(node, CharLiteral):
            return CHAR
        if isinstance(node, StringLiteral):
            return STRING
        if isinstance(node, (VarDecl, ConstDecl, Param)):
            return node.type

        # Valor por defecto conservador para no bloquear pruebas tempranas.
        return INT

    def type_suffix(self, ty: Type) -> str:
        if isinstance(ty, (IntegerType, BooleanType)):
            return "I"
        if isinstance(ty, CharType):
            return "B"
        if isinstance(ty, VoidType):
            return "V"
        raise NotImplementedError(f"Tipo aún no soportado en esta plantilla: {ty}")

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

    # -------------------------------------------------
    # opcodes auxiliares
    # -------------------------------------------------

    def binary_arith_opcode(self, oper: str, ty: Type) -> str:
        suffix = self.type_suffix(ty)
        table = {
            "+": f"ADD{suffix}",
            "-": f"SUB{suffix}",
            "*": f"MUL{suffix}",
            "/": f"DIV{suffix}",
        }
        if oper not in table:
            raise NotImplementedError(f"Aritmética no soportada: {oper}")
        return table[oper]

    def binary_bit_opcode(self, oper: str, ty: Type) -> str:
        table = {
            "&": "AND",
            "|": "OR",
            "^": "XOR",
        }
        if oper not in table:
            raise NotImplementedError(f"Bitwise no soportado: {oper}")
        return table[oper]

    # -------------------------------------------------
    # programa y declaraciones
    # -------------------------------------------------

    def visit(self, node: Program):
        self.push_scope()

        # Primera pasada: registrar nombres globales.
        for decl in node.decls:
            if isinstance(decl, (VarDecl, ConstDecl)):
                self.bind(
                    Storage(
                        decl.name,
                        decl.type,
                        is_global=True,
                        is_const=isinstance(decl, ConstDecl),
                    )
                )
            elif isinstance(decl, FuncDecl):
                self.bind(Storage(decl.name, decl.type, is_global=True))

        # Segunda pasada: generar IR real.
        for decl in node.decls:
            self.visit(decl)

        self.pop_scope()
        return self.program

    def visit(self, node: VarDecl):
        if self.current_function is None:
            self.emit(self.var_opcode(node.type), node.name)
            if node.value is not None:
                src = self.visit(node.value)
                self.emit(self.store_opcode(node.type), src, node.name)
            return

        self.bind(Storage(node.name, node.type, is_const=not node.mutable))
        self.emit(self.alloc_opcode(node.type), node.name)
        if node.value is not None:
            src = self.visit(node.value)
            self.emit(self.store_opcode(node.type), src, node.name)

    def visit(self, node: ConstDecl):
        if self.current_function is None:
            self.emit(self.var_opcode(node.type), node.name)
            src = self.visit(node.value)
            self.emit(self.store_opcode(node.type), src, node.name)
            return

        self.bind(Storage(node.name, node.type, is_const=True))
        self.emit(self.alloc_opcode(node.type), node.name)
        src = self.visit(node.value)
        self.emit(self.store_opcode(node.type), src, node.name)

    def visit(self, node: FuncDecl):
        prev_fn = self.current_function
        prev_ret = self.current_return_type

        fn = IRFunction(
            name=node.name,
            params=[(p.name, p.type) for p in node.parms.params],
            return_type=node.type,
        )
        self.program.functions.append(fn)
        self.current_function = fn
        self.current_return_type = node.type

        self.push_scope()
        for p in node.parms.params:
            self.bind(Storage(p.name, p.type, is_param=True))
            self.emit(self.alloc_opcode(p.type), p.name)

        self.visit(node.body)

        # Soporte mínimo para funciones void.
        if isinstance(node.type, VoidType):
            if not fn.instructions or fn.instructions[-1][0] != "RET":
                self.emit("RET")

        self.pop_scope()
        self.current_function = prev_fn
        self.current_return_type = prev_ret

    def visit(self, node: Block):
        self.push_scope()
        for stmt in node.stmts:
            self.visit(stmt)
        self.pop_scope()

    def visit(self, node: ParamList):
        return None

    def visit(self, node: Param):
        return None

    # -------------------------------------------------
    # statements
    # -------------------------------------------------

    def visit(self, node: Assignment):
        """
        Implementación parcial.

        Ya resuelto:
        - asignación simple a variables: x = expr

        Ejercicio para estudiantes:
        - x += expr, x -= expr, ...
        - asignación a ArrayLoc
        - impedir escritura en constantes (si desean reforzarlo aquí)
        """
        if not isinstance(node.loc, VarLoc):
            raise NotImplementedError(
                "Starter: Assignment solo soporta VarLoc por ahora"
            )

        storage = self.lookup(node.loc.name)

        if node.oper == "=":
            src = self.visit(node.expr)
            self.emit(self.store_opcode(storage.ty), src, storage.name)
            return

        raise NotImplementedError(
            "TODO estudiante: implementar asignaciones compuestas (+=, -=, ... )"
        )

    def visit(self, node: PrintStmt):
        reg = self.visit(node.expr)
        ty = self.infer_type(node.expr)
        self.emit(self.print_opcode(ty), reg)

    def visit(self, node: IfStmt):
        raise NotImplementedError(
            "TODO estudiante: generar labels y branches para IfStmt"
        )

    def visit(self, node: WhileStmt):
        raise NotImplementedError(
            "TODO estudiante: generar labels y branches para WhileStmt"
        )

    def visit(self, node: ForStmt):
        raise NotImplementedError(
            "TODO estudiante: generar labels y branches para ForStmt"
        )

    def visit(self, node: ReturnStmt):
        if node.expr is None:
            self.emit("RET")
            return

        reg = self.visit(node.expr)
        self.emit("RET", reg)

    # -------------------------------------------------
    # expressions
    # -------------------------------------------------

    def visit(self, node: VarLoc):
        storage = self.lookup(node.name)
        tmp = self.new_temp()
        self.emit(self.load_opcode(storage.ty), storage.name, tmp)
        return tmp

    def visit(self, node: ArrayLoc):
        raise NotImplementedError(
            "TODO estudiante: implementar acceso a arreglos"
        )

    def visit(self, node: FuncCall):
        raise NotImplementedError(
            "TODO estudiante: implementar evaluación de argumentos y CALL"
        )

    def visit(self, node: BinOp):
        """
        Implementación al 50%.

        Ya resuelto:
        - esqueleto general
        - aritmética básica + - * /

        Pendiente:
        - comparaciones
        - booleanos lógicos
        - operaciones bit a bit
        - cortocircuito real para && y ||
        """
        left_reg = self.visit(node.left)
        right_reg = self.visit(node.right)
        left_ty = self.infer_type(node.left)
        out = self.new_temp()

        if node.oper in {"+", "-", "*", "/"}:
            opcode = self.binary_arith_opcode(node.oper, left_ty)
            self.emit(opcode, left_reg, right_reg, out)
            return out

        raise NotImplementedError(
            f"TODO estudiante: completar BinOp para operador {node.oper!r}"
        )

    def visit(self, node: UnaryOp):
        raise NotImplementedError(
            "TODO estudiante: implementar UnaryOp (+, -, !)"
        )

    def visit(self, node: IntegerLiteral):
        tmp = self.new_temp()
        self.emit("MOVI", int(node.value), tmp)
        return tmp

    def visit(self, node: BooleanLiteral):
        tmp = self.new_temp()
        self.emit("MOVI", 1 if node.value else 0, tmp)
        return tmp

    def visit(self, node: CharLiteral):
        tmp = self.new_temp()
        value = ord(node.value) if isinstance(node.value, str) else int(node.value)
        self.emit("MOVB", value, tmp)
        return tmp

    def visit(self, node: StringLiteral):
        raise NotImplementedError(
            "TODO estudiante: decidir representación IR para strings"
        )

    def visit(self, node: ExprList):
        return [self.visit(expr) for expr in node.exprs]


# ===================================================
# demo
# ===================================================

if __name__ == "__main__":
    # Demo pequeña para que los estudiantes prueben la plantilla.
    ast = Program([
        FuncDecl(
            name="main",
            parms=ParamList([]),
            type=VOID,
            body=Block([
                VarDecl(
                    name="x",
                    type=INT,
                    value=BinOp(
                        oper="+",
                        left=IntegerLiteral(2),
                        right=BinOp(
                            oper="*",
                            left=IntegerLiteral(3),
                            right=IntegerLiteral(4),
                            type=INT,
                        ),
                        type=INT,
                    ),
                ),
                PrintStmt(expr=VarLoc(name="x", type=INT)),
            ]),
        )
    ])

    ir = IRCodeGen.generate(ast)
    print(ir.format())
