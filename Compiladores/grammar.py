import os
import sys
from railroad import Diagram, Sequence, Choice, Terminal, NonTerminal, Optional, ZeroOrMore, OneOrMore, Comment, Skip

# Configuración de estilo CSS para que se vean bien en fondo claro u oscuro
CSS_STYLE = """
    path {
        stroke-width: 2;
        stroke: black;
        fill: rgba(0,0,0,0);
    }
    text {
        font: bold 14px monospace;
        text-anchor: middle;
        fill: black;
    }
    text.comment {
        font: italic 12px monospace;
    }
    rect {
        stroke-width: 2;
        stroke: black;
        fill: #f0f0f0;
    }
    rect.group-box {
        stroke: gray;
        stroke-dasharray: 10 5;
        fill: none;
    }
"""

def T(label): return Terminal(label)
def N(label): return NonTerminal(label)

# Función para guardar SVG y asegurar directorios
def save_svg(diagram, filename, title):
    # Crear directorio si no existe
    output_dir = os.path.join("out", "svg")
    os.makedirs(output_dir, exist_ok=True)
    
    filepath = os.path.join(output_dir, f"{filename}.svg")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f'\n')
        diagram.writeSvg(f.write)
    
    print(f"Generado: {filepath}")
    return filename, title

# ==========================================
# 1. CLASS DEFINITIONS (B-Minor+)
# ==========================================

# Regla: class_decl
d_class_decl = Diagram(
    Sequence(
        T("CLASS"),
        T("ID"),
        T("{"),
        ZeroOrMore(
            Sequence(
                N("class_member"),
                Comment("Field/Method")
            )
        ),
        T("}")
    ), type="complex"
)

# Regla: class_member
d_class_member = Diagram(
    Choice(0,
        Sequence(N("decl"), Comment("Field")),
        Sequence(N("func_decl"), Comment("Method"))
    )
)

# ==========================================
# 2. STATEMENTS (While Loop Extension)
# ==========================================

# Regla: while_stmt_closed (Evita dangling else)
d_while_closed = Diagram(
    Sequence(
        T("WHILE"),
        T("("),
        N("expr"),
        T(")"),
        N("closed_stmt")
    )
)

# Regla: while_stmt_open
d_while_open = Diagram(
    Sequence(
        T("WHILE"),
        T("("),
        N("expr"),
        T(")"),
        N("open_stmt")
    )
)

# ==========================================
# 3. EXPRESSIONS (Operators & Precedence)
# ==========================================

# A. Compound Assignment (Prioridad más baja)
# expr1 ::= lval ( = | += | -= ... ) expr1
d_expr_assign = Diagram(
    Sequence(
        N("lval"),
        Choice(0,
            T("="),
            T("+="),
            T("-="),
            T("*="),
            T("/="),
            T("%=")
        ),
        N("expr1")
    )
)

# B. Ternary Operator (?:)
# Se inserta encima de Logical OR y debajo de Asignación
d_expr_ternary = Diagram(
    Sequence(
        N("expr_lor"),
        Optional(
            Sequence(
                T("?"),
                N("expr"),
                T(":"),
                N("expr_ternary")
            )
        )
    )
)

# C. Postfix / Member Access (Prioridad más alta)
# Maneja: a++, a--, a.b, a[x], f()
d_expr_postfix = Diagram(
    Sequence(
        Choice(0,
            N("ID"),
            Sequence(T("("), N("expr"), T(")")),
            Sequence(T("NEW"), N("type"), T("("), Optional(N("args")), T(")"))
        ),
        ZeroOrMore(
            Choice(0,
                Sequence(T("["), N("expr"), T("]"), Comment("Index")),
                Sequence(T("."), N("ID"), Comment("Member Access")),
                Sequence(T("("), Optional(N("args")), T(")"), Comment("Call")),
                Sequence(T("++"), Comment("Post-Inc")),
                Sequence(T("--"), Comment("Post-Dec"))
            )
        )
    )
)

# ==========================================
# GENERACIÓN DE ARCHIVOS
# ==========================================

if __name__ == "__main__":
    diagrams_info = []

    # Generar SVGs
    diagrams_info.append(save_svg(d_class_decl, "class_decl", "Declaración de Clases"))
    diagrams_info.append(save_svg(d_class_member, "class_member", "Miembros de Clase"))
    diagrams_info.append(save_svg(d_while_closed, "while_closed", "While (Cerrado)"))
    diagrams_info.append(save_svg(d_while_open, "while_open", "While (Abierto)"))
    diagrams_info.append(save_svg(d_expr_assign, "expr_assignment", "Asignación Compuesta"))
    diagrams_info.append(save_svg(d_expr_ternary, "expr_ternary", "Operador Ternario"))
    diagrams_info.append(save_svg(d_expr_postfix, "expr_postfix", "Postfix y Acceso a Miembros"))

    # Generar index.md para Obsidian
    index_path = os.path.join("out", "index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# Atlas de Gramática B-Minor+\n\n")
        f.write("Este documento contiene los diagramas de sintaxis generados automáticamente para la extensión del lenguaje.\n\n")
        f.write("---\n")
        
        current_section = ""
        
        # Agrupar lógica simple para el reporte
        sections = {
            "Clases": ["class_decl", "class_member"],
            "Sentencias de Control": ["while_closed", "while_open"],
            "Expresiones y Operadores": ["expr_assignment", "expr_ternary", "expr_postfix"]
        }

        for section_name, files in sections.items():
            f.write(f"## {section_name}\n\n")
            for filename in files:
                # Buscar el título legible
                title = next((t for f, t in diagrams_info if f == filename), filename)
                
                f.write(f"### {title}\n")
                # Sintaxis compatible con Obsidian y Markdown estándar
                f.write(f"![{title}](svg/{filename}.svg)\n\n")
        
    print(f"\n¡Éxito! Archivo índice creado en: {index_path}")
