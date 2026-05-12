from __future__ import annotations

import sys
from typing import Any, Optional

from ircode import IRCodeGen, IRFunction, IRProgram, Instruction


ARITH_OPS = {"ADDI", "SUBI", "MULI", "DIVI", "ADDF", "SUBF", "MULF", "DIVF"}
INT_ARITH_OPS = {"ADDI", "SUBI", "MULI", "DIVI"}
FLOAT_ARITH_OPS = {"ADDF", "SUBF", "MULF", "DIVF"}
LOGIC_OPS = {"AND", "OR", "XOR"}
CMP_OPS = {"CMPI", "CMPF", "CMPB", "CMPS"}
TERMINATORS = {"BRANCH", "CBRANCH", "RET"}
BLOCK_TERMINATORS = {"BRANCH", "CBRANCH", "RET"}


def is_temp(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("R")


def parse_opt_level(value: str) -> int:
    text = str(value).strip()

    if text.startswith("-O"):
        text = text[2:]
    elif text.startswith("O"):
        text = text[1:]

    if not text.isdigit():
        raise ValueError(f"Nivel de optimización inválido: {value!r}")

    level = int(text)
    if level < 0 or level > 4:
        raise ValueError("El nivel de optimización debe estar entre 0 y 4")

    return level


class IROptimizer:
    def __init__(self, level: int = 0):
        self.level = level

    @classmethod
    def optimize(cls, program: IRProgram, level: int = 0) -> IRProgram:
        return cls(level).visit_program(program)

    def visit_program(self, program: IRProgram) -> IRProgram:
        if self.level <= 0:
            return program

        new_functions: list[IRFunction] = []
        for fn in program.functions:
            new_insts = self.optimize_instruction_list(fn.instructions)
            new_functions.append(
                IRFunction(
                    name=fn.name,
                    params=list(fn.params),
                    return_type=fn.return_type,
                    instructions=new_insts,
                )
            )

        return IRProgram(globals=list(program.globals), functions=new_functions)

    def optimize_instruction_list(self, instructions: list[Instruction]) -> list[Instruction]:
        insts = list(instructions)

        if self.level >= 1:
            insts = self.constant_fold_and_simplify(insts)
            insts = self.remove_unreachable(insts)
            insts = self.remove_branch_to_next_label(insts)

        if self.level >= 2:
            insts = self.remove_unused_temp_definitions(insts)

        return insts

    # -------------------------------------------------
    # Nivel O1
    # -------------------------------------------------

    def constant_fold_and_simplify(self, instructions: list[Instruction]) -> list[Instruction]:
        const: dict[str, Any] = {}
        out: list[Instruction] = []

        for inst in instructions:
            op = inst[0]

            if op == "LABEL":
                const.clear()
                out.append(inst)
                continue

            if op in {"MOVI", "MOVF", "MOVB"} and len(inst) == 3:
                value, dst = inst[1], inst[2]
                if is_temp(dst):
                    const[dst] = value
                out.append(inst)
                continue

            if op in ARITH_OPS and len(inst) == 4:
                optimized = self.fold_arithmetic(inst, const)
                out.append(optimized)
                continue

            if op in LOGIC_OPS and len(inst) == 4:
                optimized = self.fold_logic(inst, const)
                out.append(optimized)
                continue

            if op in CMP_OPS and len(inst) == 5:
                cmp_oper, a, b, dst = inst[1], inst[2], inst[3], inst[4]
                has_a, val_a = self.constant_value(a, const)
                has_b, val_b = self.constant_value(b, const)

                if has_a and has_b:
                    value = 1 if self.eval_cmp(cmp_oper, val_a, val_b) else 0
                    const[dst] = value
                    out.append(("MOVI", value, dst))
                    continue

                const.pop(dst, None)
                out.append(inst)
                continue

            if op == "CBRANCH" and len(inst) == 4:
                test, true_label, false_label = inst[1], inst[2], inst[3]
                has_test, value = self.constant_value(test, const)

                if has_test:
                    out.append(("BRANCH", true_label if value != 0 else false_label))
                    continue

                out.append(inst)
                continue

            dst = self.defined_temp(inst)
            if dst is not None:
                const.pop(dst, None)

            if op in {"BRANCH", "CBRANCH", "RET", "CALL"}:
                const.clear()

            out.append(inst)

        return out

    def fold_arithmetic(self, inst: Instruction, const: dict[str, Any]) -> Instruction:
        op, a, b, dst = inst
        has_a, val_a = self.constant_value(a, const)
        has_b, val_b = self.constant_value(b, const)
        move_op = "MOVF" if op in FLOAT_ARITH_OPS else "MOVI"

        if has_a and has_b:
            if op.startswith("DIV") and val_b == 0:
                const.pop(dst, None)
                return inst

            value = self.eval_arithmetic(op, val_a, val_b)
            const[dst] = value
            return (move_op, value, dst)

        algebraic = self.simplify_algebraic(op, has_a, val_a, has_b, val_b)
        if algebraic is not None:
            const[dst] = algebraic
            return (move_op, algebraic, dst)

        const.pop(dst, None)
        return inst

    def fold_logic(self, inst: Instruction, const: dict[str, Any]) -> Instruction:
        op, a, b, dst = inst
        has_a, val_a = self.constant_value(a, const)
        has_b, val_b = self.constant_value(b, const)

        if has_a and has_b:
            value = self.eval_logic(op, val_a, val_b)
            const[dst] = value
            return ("MOVI", value, dst)

        const.pop(dst, None)
        return inst

    def simplify_algebraic(
        self,
        op: str,
        has_a: bool,
        val_a: Any,
        has_b: bool,
        val_b: Any,
    ) -> Optional[Any]:
        zero = 0.0 if op in FLOAT_ARITH_OPS else 0
        one = 1.0 if op in FLOAT_ARITH_OPS else 1

        if op.startswith("ADD"):
            if has_b and val_b == zero and has_a:
                return val_a
            if has_a and val_a == zero and has_b:
                return val_b

        if op.startswith("SUB"):
            if has_b and val_b == zero and has_a:
                return val_a

        if op.startswith("MUL"):
            if (has_a and val_a == zero) or (has_b and val_b == zero):
                return zero
            if has_b and val_b == one and has_a:
                return val_a
            if has_a and val_a == one and has_b:
                return val_b

        if op.startswith("DIV"):
            if has_b and val_b == one and has_a:
                return val_a

        return None

    def remove_unreachable(self, instructions: list[Instruction]) -> list[Instruction]:
        out: list[Instruction] = []
        unreachable = False

        for inst in instructions:
            op = inst[0]

            if op == "LABEL":
                unreachable = False
                out.append(inst)
                continue

            if unreachable:
                continue

            out.append(inst)

            if op in TERMINATORS:
                unreachable = True

        return out

    def remove_branch_to_next_label(self, instructions: list[Instruction]) -> list[Instruction]:
        out: list[Instruction] = []
        i = 0

        while i < len(instructions):
            inst = instructions[i]

            if (
                inst[0] == "BRANCH"
                and len(inst) == 2
                and i + 1 < len(instructions)
                and instructions[i + 1][0] == "LABEL"
                and instructions[i + 1][1] == inst[1]
            ):
                i += 1
                continue

            out.append(inst)
            i += 1

        return out

    # -------------------------------------------------
    # Nivel O2
    # -------------------------------------------------

    def remove_unused_temp_definitions(self, instructions: list[Instruction]) -> list[Instruction]:
        blocks = self.split_basic_blocks(instructions)
        block_uses = [self.used_temps_in_block(block) for block in blocks]
        optimized_blocks: list[list[Instruction]] = []

        for index, block in enumerate(blocks):
            used_outside = set().union(
                *(uses for i, uses in enumerate(block_uses) if i != index)
            )
            optimized_blocks.append(self.remove_unused_temp_definitions_in_block(block, used_outside))

        return [inst for block in optimized_blocks for inst in block]

    def remove_unused_temp_definitions_in_block(
        self,
        instructions: list[Instruction],
        initial_used: set[str],
    ) -> list[Instruction]:
        used = set(initial_used)
        result_reversed: list[Instruction] = []

        for inst in reversed(instructions):
            dst = self.defined_temp(inst)
            args = self.used_temps(inst)

            if dst is not None and dst not in used and self.is_pure_definition(inst):
                continue

            if dst is not None:
                used.discard(dst)

            used.update(args)
            result_reversed.append(inst)

        return list(reversed(result_reversed))

    def split_basic_blocks(self, instructions: list[Instruction]) -> list[list[Instruction]]:
        blocks: list[list[Instruction]] = []
        current: list[Instruction] = []

        for inst in instructions:
            if inst[0] == "LABEL" and current:
                blocks.append(current)
                current = []

            current.append(inst)

            if inst[0] in BLOCK_TERMINATORS:
                blocks.append(current)
                current = []

        if current:
            blocks.append(current)

        return blocks

    def used_temps_in_block(self, instructions: list[Instruction]) -> set[str]:
        used: set[str] = set()
        for inst in instructions:
            used.update(self.used_temps(inst))
        return used

    def defined_temp(self, inst: Instruction) -> Optional[str]:
        op = inst[0]

        if op in {"MOVI", "MOVF", "MOVB", "MOVS", "ADDR"} and len(inst) == 3:
            return inst[2] if is_temp(inst[2]) else None

        if op in ARITH_OPS | LOGIC_OPS and len(inst) == 4:
            return inst[3] if is_temp(inst[3]) else None

        if op in CMP_OPS and len(inst) == 5:
            return inst[4] if is_temp(inst[4]) else None

        if op in {"ITOF", "FTOI", "BTOI", "ITOB"} and len(inst) == 3:
            return inst[2] if is_temp(inst[2]) else None

        if op == "PHI" and len(inst) >= 2:
            return inst[-1] if is_temp(inst[-1]) else None

        if op.startswith("LOAD") and len(inst) >= 3:
            return inst[-1] if is_temp(inst[-1]) else None

        return None

    def used_temps(self, inst: Instruction) -> set[str]:
        op = inst[0]

        if op in {"MOVI", "MOVF", "MOVB", "MOVS", "LABEL", "BRANCH", "DATAS", "ADDR"}:
            return set()

        if op.startswith("STORE"):
            return self.temps_in(inst[1:])

        if op.startswith("PRINT"):
            return self.temps_in(inst[1:])

        if op == "CBRANCH":
            return self.temps_in(inst[1:2])

        if op == "RET":
            return self.temps_in(inst[1:])

        if op in ARITH_OPS | LOGIC_OPS:
            return self.temps_in(inst[1:3])

        if op in CMP_OPS:
            return self.temps_in(inst[2:4])

        if op in {"ITOF", "FTOI", "BTOI", "ITOB"}:
            return self.temps_in(inst[1:2])

        if op == "PHI":
            return self.temps_in(inst[1:-1])

        if op.startswith("LOAD"):
            return self.temps_in(inst[1:-1])

        return self.temps_in(inst[1:])

    def temps_in(self, values) -> set[str]:
        return {x for x in values if is_temp(x)}

    def is_pure_definition(self, inst: Instruction) -> bool:
        op = inst[0]
        return (
            op in {
                "MOVI", "MOVF", "MOVB", "MOVS", "ADDR",
                "ADDI", "SUBI", "MULI", "DIVI",
                "ADDF", "SUBF", "MULF", "DIVF",
                "AND", "OR", "XOR",
                "CMPI", "CMPF", "CMPB", "CMPS",
                "PHI",
                "ITOF", "FTOI", "BTOI", "ITOB",
            }
            or op.startswith("LOAD")
        )

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------

    def constant_value(self, operand: Any, const: dict[str, Any]) -> tuple[bool, Any]:
        if is_temp(operand):
            if operand in const:
                return True, const[operand]
            return False, None

        if isinstance(operand, (int, float, bool)):
            return True, operand

        return False, None

    def eval_arithmetic(self, op: str, a: Any, b: Any) -> Any:
        if op.startswith("ADD"):
            return a + b
        if op.startswith("SUB"):
            return a - b
        if op.startswith("MUL"):
            return a * b
        if op.startswith("DIV"):
            return int(a / b) if op in INT_ARITH_OPS else a / b
        raise NotImplementedError(f"Operación aritmética no soportada: {op}")

    def eval_logic(self, op: str, a: Any, b: Any) -> int:
        left = int(a)
        right = int(b)
        if op == "AND":
            return left & right
        if op == "OR":
            return left | right
        if op == "XOR":
            return left ^ right
        raise NotImplementedError(f"Operación lógica no soportada: {op}")

    def eval_cmp(self, oper: str, a: Any, b: Any) -> bool:
        if oper == "==":
            return a == b
        if oper == "!=":
            return a != b
        if oper == "<":
            return a < b
        if oper == "<=":
            return a <= b
        if oper == ">":
            return a > b
        if oper == ">=":
            return a >= b
        raise NotImplementedError(f"Comparador no soportado: {oper}")


def compile_source(source_path: str) -> IRProgram:
    from checker import Checker
    from lexer import Lexer
    from parser import Parser

    source = open(source_path, encoding="utf-8").read()
    lexer = Lexer()
    parser = Parser()
    ast = parser.parse(lexer.tokenize(source))

    if ast is None:
        raise SystemExit("El parser no produjo un AST")

    checker = Checker()
    ok = checker.check(ast)
    for msg in checker.errors:
        print(msg, file=sys.stderr)

    if not ok:
        print("El checker reportó errores; generando IR de todos modos...", file=sys.stderr)

    return IRCodeGen.generate(ast)


def parse_cli(argv: list[str]) -> tuple[str, int, bool]:
    if not argv or "--help" in argv or "-h" in argv:
        raise SystemExit(
            "Uso: python iroptimizer.py archivo.bminor [-O0|-O1|-O2]\n"
            "     python iroptimizer.py archivo.bminor -O 2\n"
            "     python iroptimizer.py archivo.bminor 2\n"
            "     python iroptimizer.py archivo.bminor --compare"
        )

    source_path = argv[0]
    level = 0
    compare = False
    i = 1

    while i < len(argv):
        arg = argv[i]

        if arg == "--compare":
            compare = True
            i += 1
            continue

        if arg == "-O":
            if i + 1 >= len(argv):
                raise SystemExit("Falta el nivel después de -O")
            level = parse_opt_level(argv[i + 1])
            i += 2
            continue

        if arg.startswith("-O") or arg.startswith("O") or arg.isdigit():
            level = parse_opt_level(arg)
            i += 1
            continue

        raise SystemExit(f"Argumento no reconocido: {arg}")

    return source_path, level, compare


def print_comparison(program: IRProgram) -> None:
    sections = [
        ("IR original (-O0)", program),
        ("IR optimizada (-O1)", IROptimizer.optimize(program, level=1)),
        ("IR optimizada (-O2)", IROptimizer.optimize(program, level=2)),
    ]

    for title, ir in sections:
        print(f"=== {title} ===")
        print(ir.format())
        print()


def main(argv: Optional[list[str]] = None) -> int:
    source_path, level, compare = parse_cli(list(sys.argv[1:] if argv is None else argv))
    program = compile_source(source_path)

    if compare:
        print_comparison(program)
        return 0

    optimized = IROptimizer.optimize(program, level=level)
    print(optimized.format())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
