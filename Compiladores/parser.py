# mcparser.py
'''
Parser para el lenguaje B-minor definido por lexer.py.

Sintaxis B-minor real:
  var_decl   → ID ':' type_spec ';'
             | ID ':' type_spec '=' expression ';'
  func_decl  → ID ':' FUNCTION type_spec '(' params_opt ')' '=' compound_stmt
  type_spec  → INTEGER | FLOAT | CHAR | STRING | BOOLEAN | VOID
             | ARRAY '[' expression ']' type_spec      ← tamaño entre corchetes
             | ID
  array_lit  → '{' args_opt '}'                        ← llaves, NO corchetes
'''

import sly
from lexer import Lexer
from model import (
    Program,
    SimpleType, ArrayType, UserType,
    VarDeclaration, Parameter, FuncDeclaration, FuncPrototype, ClassDeclaration,
    CompoundStatement, ExprStatement,
    IfStatement, WhileStatement, ForStatement,
    ReturnStatement, PrintStatement,
    AssignExpr, BinaryExpr, UnaryExpr, PostfixExpr,
    CallExpr, IndexExpr, MemberExpr, GroupExpr,
    IntLiteral, FloatLiteral, CharLiteral, StringLiteral,
    BoolLiteral, ArrayLiteral,
    Identifier, ThisExpr, SuperExpr,
)


class Parser(sly.Parser):
    # debugfile = 'parser.out'

    tokens = Lexer.tokens

    # ── Programa ──────────────────────────────────────────────────────────
    @_('declaration_list')
    def program(self, p):
        return Program(p.declaration_list)

    @_('')
    def declaration_list(self, p):
        return []

    @_('declaration_list declaration')
    def declaration_list(self, p):
        return p.declaration_list + [p.declaration]

    @_('var_decl', 'func_decl', 'class_decl')
    def declaration(self, p):
        return p[0]

    # ── Tipos ──────────────────────────────────────────────────────────────
    @_('INTEGER', 'FLOAT', 'CHAR', 'STRING', 'BOOLEAN', 'VOID')
    def type_spec(self, p):
        return SimpleType(p[0].lower())

    # Sintaxis B-minor real:  array [tamaño] tipo_elemento
    @_("ARRAY '[' LITERAL_INTEGER ']' type_spec")
    def type_spec(self, p):
        return ArrayType(IntLiteral(p.LITERAL_INTEGER), p.type_spec)

    @_("ARRAY '[' ID ']' type_spec")
    def type_spec(self, p):
        return ArrayType(Identifier(p.ID), p.type_spec)

    # array [] tipo  ← parámetros sin tamaño fija
    @_("ARRAY '[' ']' type_spec")
    def type_spec(self, p):
        return ArrayType(None, p.type_spec)

    @_('ID')
    def type_spec(self, p):
        return UserType(p.ID)

    # ── Declaraciones B-minor ─────────────────────────────────────────────
    @_("ID ':' type_spec ';'")
    def var_decl(self, p):
        return VarDeclaration(p.type_spec, p.ID, lineno=p.lineno)

    @_("ID ':' type_spec '=' expression ';'")
    def var_decl(self, p):
        return VarDeclaration(p.type_spec, p.ID, init=p.expression, lineno=p.lineno)

    @_("ID ':' type_spec '=' '{' args_opt '}' ';'")
    def var_decl(self, p):
        lit = ArrayLiteral(p.args_opt, lineno=p.lineno)
        return VarDeclaration(p.type_spec, p.ID, init=lit, lineno=p.lineno)

    @_("ID ':' FUNCTION type_spec '(' params_opt ')' '=' compound_stmt")
    def func_decl(self, p):
        return FuncDeclaration(
            name=p.ID,
            params=p.params_opt,
            return_type=p.type_spec,
            body=p.compound_stmt.stmts,
            lineno=p.lineno,
        )

    # Prototipo:  nombre : function tipo ( params ) ;
    @_("ID ':' FUNCTION type_spec '(' params_opt ')' ';'")
    def func_decl(self, p):
        return FuncPrototype(
            name=p.ID,
            params=p.params_opt,
            return_type=p.type_spec,
            lineno=p.lineno,
        )

    # ── Clases ────────────────────────────────────────────────────────────
    @_("CLASS ID '{' member_list '}'")
    def class_decl(self, p):
        return ClassDeclaration(name=p.ID, superclass=None,
                                members=p.member_list, lineno=p.lineno)

    @_("CLASS ID ':' ID '{' member_list '}'")
    def class_decl(self, p):
        return ClassDeclaration(name=p.ID0, superclass=p.ID1,
                                members=p.member_list, lineno=p.lineno)

    @_('')
    def member_list(self, p):
        return []

    @_('member_list member')
    def member_list(self, p):
        return p.member_list + [p.member]

    @_('var_decl', 'func_decl')
    def member(self, p):
        return p[0]

    # ── Parámetros ────────────────────────────────────────────────────────
    @_('')
    def params_opt(self, p):
        return []

    @_('param_list')
    def params_opt(self, p):
        return p.param_list

    @_('param')
    def param_list(self, p):
        return [p.param]

    @_("param_list ',' param")
    def param_list(self, p):
        return p.param_list + [p.param]

    @_("ID ':' type_spec")
    def param(self, p):
        return Parameter(p.type_spec, p.ID, p.lineno)

    # ── Bloque ────────────────────────────────────────────────────────────
    @_("'{' stmt_list '}'")
    def compound_stmt(self, p):
        return CompoundStatement(p.stmt_list)

    @_('')
    def stmt_list(self, p):
        return []

    @_('stmt_list stmt')
    def stmt_list(self, p):
        return p.stmt_list + [p.stmt]

    # ── Sentencias ────────────────────────────────────────────────────────
    @_('var_decl', 'if_stmt', 'while_stmt', 'for_stmt',
       'return_stmt', 'print_stmt', 'compound_stmt', 'expr_stmt')
    def stmt(self, p):
        return p[0]

    @_("IF '(' expression ')' stmt ELSE stmt")
    def if_stmt(self, p):
        return IfStatement(p.expression, p.stmt0, p.stmt1, lineno=p.lineno)

    @_("IF '(' expression ')' stmt")
    def if_stmt(self, p):
        return IfStatement(p.expression, p.stmt, lineno=p.lineno)

    @_("WHILE '(' expression ')' stmt")
    def while_stmt(self, p):
        return WhileStatement(p.expression, p.stmt, lineno=p.lineno)

    @_("FOR '(' for_init expr_opt ';' expr_opt ')' stmt")
    def for_stmt(self, p):
        return ForStatement(p.for_init, p.expr_opt0, p.expr_opt1, p.stmt, lineno=p.lineno)

    @_('var_decl')
    def for_init(self, p):
        return p.var_decl

    @_('expr_stmt')
    def for_init(self, p):
        return p.expr_stmt

    @_("';'")
    def for_init(self, p):
        return None

    @_('')
    def expr_opt(self, p):
        return None

    @_('expression')
    def expr_opt(self, p):
        return p.expression

    @_("RETURN ';'")
    def return_stmt(self, p):
        return ReturnStatement(lineno=p.lineno)

    @_("RETURN expression ';'")
    def return_stmt(self, p):
        return ReturnStatement(p.expression, lineno=p.lineno)

    @_("RETURN '{' args_opt '}' ';'")
    def return_stmt(self, p):
        return ReturnStatement(ArrayLiteral(p.args_opt, lineno=p.lineno), lineno=p.lineno)

    # B-minor real: print expr, expr, ... ;  (sin paréntesis)
    @_("PRINT print_args ';'")
    def print_stmt(self, p):
        return PrintStatement(p.print_args, lineno=p.lineno)

    @_('expression')
    def print_args(self, p):
        return [p.expression]

    @_("print_args ',' expression")
    def print_args(self, p):
        return p.print_args + [p.expression]

    @_("expression ';'")
    def expr_stmt(self, p):
        return ExprStatement(p.expression, lineno=p.lineno)

    # ── Expresiones ───────────────────────────────────────────────────────
    @_('assign_expr', 'logical_or')
    def expression(self, p):
        return p[0]

    @_("postfix_expr '='    expression",
       "postfix_expr ADDEQ expression",
       "postfix_expr SUBEQ expression",
       "postfix_expr MULEQ expression",
       "postfix_expr DIVEQ expression",
       "postfix_expr MODEQ expression")
    def assign_expr(self, p):
        return AssignExpr(p.postfix_expr, p[1], p.expression, lineno=p.lineno)

    @_('logical_and')
    def logical_or(self, p):
        return p.logical_and

    @_('logical_or LOR logical_and')
    def logical_or(self, p):
        return BinaryExpr(p.logical_or, '||', p.logical_and, lineno=p.lineno)

    @_('equality')
    def logical_and(self, p):
        return p.equality

    @_('logical_and LAND equality')
    def logical_and(self, p):
        return BinaryExpr(p.logical_and, '&&', p.equality, lineno=p.lineno)

    @_('relational')
    def equality(self, p):
        return p.relational

    @_('equality EQ relational', 'equality NE relational')
    def equality(self, p):
        return BinaryExpr(p.equality, p[1], p.relational, lineno=p.lineno)

    @_('additive')
    def relational(self, p):
        return p.additive

    @_('relational LT additive', 'relational LE additive',
       'relational GT additive', 'relational GE additive')
    def relational(self, p):
        return BinaryExpr(p.relational, p[1], p.additive, lineno=p.lineno)

    @_('mult')
    def additive(self, p):
        return p.mult

    @_("additive '+' mult", "additive '-' mult")
    def additive(self, p):
        return BinaryExpr(p.additive, p[1], p.mult, lineno=p.lineno)

    @_('unary')
    def mult(self, p):
        return p.unary

    @_("mult '*' unary", "mult '/' unary", "mult '%' unary")
    def mult(self, p):
        return BinaryExpr(p.mult, p[1], p.unary, lineno=p.lineno)

    @_('postfix_expr')
    def unary(self, p):
        return p.postfix_expr

    @_("'-' unary %prec UMINUS")
    def unary(self, p):
        return UnaryExpr('-', p.unary, lineno=p.lineno)

    @_("'!' unary %prec UNOT")
    def unary(self, p):
        return UnaryExpr('!', p.unary, lineno=p.lineno)

    @_("INC unary %prec PREINC")
    def unary(self, p):
        return UnaryExpr('++', p.unary, lineno=p.lineno)

    @_("DEC unary %prec PREDEC")
    def unary(self, p):
        return UnaryExpr('--', p.unary, lineno=p.lineno)

    @_('primary')
    def postfix_expr(self, p):
        return p.primary

    @_("postfix_expr '[' expression ']'")
    def postfix_expr(self, p):
        return IndexExpr(p.postfix_expr, p.expression, lineno=p.lineno)

    @_("postfix_expr '(' args_opt ')'")
    def postfix_expr(self, p):
        return CallExpr(p.postfix_expr, p.args_opt, lineno=p.lineno)

    @_("postfix_expr '.' ID")
    def postfix_expr(self, p):
        return MemberExpr(p.postfix_expr, p.ID, lineno=p.lineno)

    @_("postfix_expr INC")
    def postfix_expr(self, p):
        return PostfixExpr(p.postfix_expr, '++', lineno=p.lineno)

    @_("postfix_expr DEC")
    def postfix_expr(self, p):
        return PostfixExpr(p.postfix_expr, '--', lineno=p.lineno)

    @_('')
    def args_opt(self, p):
        return []

    @_('arg_list')
    def args_opt(self, p):
        return p.arg_list

    @_('expression')
    def arg_list(self, p):
        return [p.expression]

    @_("arg_list ',' expression")
    def arg_list(self, p):
        return p.arg_list + [p.expression]

    # ── Primarios ─────────────────────────────────────────────────────────
    @_('ID')
    def primary(self, p):
        return Identifier(p.ID, lineno=p.lineno)

    @_('LITERAL_INTEGER')
    def primary(self, p):
        return IntLiteral(p.LITERAL_INTEGER, lineno=p.lineno)

    @_('LITERAL_FLOAT')
    def primary(self, p):
        return FloatLiteral(p.LITERAL_FLOAT, lineno=p.lineno)

    @_('LITERAL_CHAR')
    def primary(self, p):
        return CharLiteral(p.LITERAL_CHAR, lineno=p.lineno)

    @_('LITERAL_STRING')
    def primary(self, p):
        return StringLiteral(p.LITERAL_STRING, lineno=p.lineno)

    @_('TRUE')
    def primary(self, p):
        return BoolLiteral(True, lineno=p.lineno)

    @_('FALSE')
    def primary(self, p):
        return BoolLiteral(False, lineno=p.lineno)

    @_('THIS')
    def primary(self, p):
        return ThisExpr(lineno=p.lineno)

    @_('SUPER')
    def primary(self, p):
        return SuperExpr(lineno=p.lineno)

    @_("'(' expression ')'")
    def primary(self, p):
        return GroupExpr(p.expression)

    def error(self, p):
        if p:
            print(f"Error de sintaxis en línea {p.lineno}: token inesperado {p.value!r}")
            self.errok()   # intenta recuperarse y seguir parseando
        else:
            print("Error de sintaxis: fin de archivo inesperado")

    precedence = (
        ('right', 'ELSE'),
        ('right', '=', 'ADDEQ', 'SUBEQ', 'MULEQ', 'DIVEQ', 'MODEQ'),
        ('left',  'LOR'),
        ('left',  'LAND'),
        ('left',  'EQ', 'NE'),
        ('left',  'LT', 'LE', 'GT', 'GE'),
        ('left',  '+', '-'),
        ('left',  '*', '/', '%'),
        ('right', 'UMINUS', 'UNOT', 'PREINC', 'PREDEC'),
        ('left',  'INC', 'DEC', '[', '(', '.'),
    )


if __name__ == '__main__':
    import sys
    from rich import print

    if len(sys.argv) != 2:
        print(f'Uso: python parser.py <archivo>')
        sys.exit(1)

    source = open(sys.argv[1], encoding='utf-8').read()
    lexer  = Lexer()
    parser = Parser()

    try:
        ast = parser.parse(lexer.tokenize(source))
    except SyntaxError:
        sys.exit(1)   # el mensaje ya fue impreso dentro de error()

    from ast_printer import RichASTPrinter
    printer = RichASTPrinter()
    tree = printer.build(ast)
    print(tree)