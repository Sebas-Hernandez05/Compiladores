# lexer.py
from rich import print
from rich.table import Table
from rich.console import Console
import sly

# Definición de tokens

class Lexer(sly.Lexer):
    tokens  = {
        # Palabras Reservadas
        ARRAY, BOOLEAN, CHAR, ELSE, FALSE, FLOAT, FOR, FUNCTION, IF,
        INTEGER, PRINT, RETURN, STRING, TRUE, VOID, WHILE,
        CLASS, THIS, SUPER, 

        # Operadores de Relación
        LT, LE, GT, GE, EQ, NE, LAND, LOR,

        # Operadores de Assignación
        ADDEQ, SUBEQ, MULEQ, DIVEQ, MODEQ, INC, DEC,

        # Identificador y Literales
        ID,
        LITERAL_INTEGER, LITERAL_FLOAT, LITERAL_CHAR, LITERAL_STRING,
    }
    
    literals = '+-*/%^=;,.:()[]{}?'

    # simbolos a ignorar
    ignore = ' \t\r'

    # Expresiones regulares para los tokens
    ID = r'[a-zA-Z_][a-zA-Z0-9_]*'

    # Operadores
    LE   = r'<='
    LT   = r'<'
    GE   = r'>='
    GT   = r'>'
    EQ   = r'=='
    NE   = r'!='
    LAND = r'&&'
    LOR  = r'\|\|'
    ADDEQ = r'\+='
    SUBEQ = r'-='
    MULEQ = r'\*='
    DIVEQ = r'/='
    MODEQ = r'%='
    INC   = r'\+\+'
    DEC   = r'--'

    # Mapeo completo de Palabras Reservadas
    ID['array'] = ARRAY
    ID['boolean'] = BOOLEAN
    ID['char'] = CHAR
    ID['else'] = ELSE
    ID['false'] = FALSE
    ID['float'] = FLOAT
    ID['for'] = FOR
    ID['function'] = FUNCTION
    ID['if'] = IF
    ID['integer'] = INTEGER
    ID['print'] = PRINT
    ID['return'] = RETURN
    ID['string'] = STRING
    ID['true'] = TRUE
    ID['void'] = VOID
    ID['while'] = WHILE
    ID['class'] = CLASS
    ID['this'] = THIS
    ID['super'] = SUPER

    # Literales de texto y caracter
    LITERAL_STRING = r'"(?:[^"\\]|\\.)*"'  # soporta escapes: \n \t \\ \"
    LITERAL_CHAR   = r"'(?:[^'\\]|\\(?:[nrt\\'\"0]|0x[0-9a-fA-F]{1,2}))'"

    # Literales NUmericos (con conversion de tipo)
    @_(r'\d+\.\d*|\.\d+')
    def LITERAL_FLOAT(self, t):
        t.value = float(t.value)
        return t

    @_(r'\d+')
    def LITERAL_INTEGER(self, t):
        t.value = int(t.value)
        return t
    
    # Ignorar comentarios y actualizar lineo
    @_(r'/\*(.|\n)*?\*/')
    def ignore_comment(self, t):
        self.lineno += t.value.count('\n')

    @_(r'//.*')
    def ignore_cppcomment(self, t):
        pass

    # Actualizador del contador de lineas
    @_('\n+')
    def ignore_newline(self, t):
        self.lineno += t.value.count('\n')

    # Manejo de errores
    def error(self, t):
        print(f"{self.lineno}: Caracter ilegal '{t.value[0]}'")
        self.index += 1

def pprint(source):
    lex = Lexer()

    table = Table(title='Analizador Léxico')
    table.add_column('Token', style='cyan')
    table.add_column('Value', style='magenta')
    table.add_column('Lineno', justify='right', style='green')

    for tok in lex.tokenize(source):
        # Convertimos el valor a string para que 'rich' no falle al pintar números
        value = tok.value if isinstance(tok.value, str) else str(tok.value)
        table.add_row(tok.type, value, str(tok.lineno))
    
    console = Console()
    console.print(table, justify='center')

if __name__ == '__main__':
    import sys

    if len(sys.argv) != 2:
        print(f'usage: python lexer.py <filename>')
        raise SyntaxError()

    txt = open(sys.argv[1], encoding='utf-8').read()
    pprint(txt)