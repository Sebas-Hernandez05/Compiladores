# Analizador Semántico — B++ / B-Minor+

Proyecto de compiladores. Implementa un analizador semántico completo sobre el AST generado por el parser del lenguaje B-Minor extendido (B++).

---

## Cómo ejecutar el analizador semántico

### Requisitos

```bash
pip install sly multimethod rich
```

### Uso básico

```bash
python checker.py <archivo.bpp>
```

### Mostrar la tabla de símbolos

```bash
python checker.py <archivo.bpp> --symtab
```

Si el análisis es exitoso, imprime:

```
semantic check: success
```

En caso de errores, los lista con número de línea antes de reportar el resultado:

```
error (línea 5): símbolo 'x' ya definido en este alcance
error (línea 12): operador '+' no aplica a tipos IntType y BoolType

semantic check: failed  (2 error(s))
```

> El checker depende de `parser.py`, `lexer.py` y `model.py`. Todos deben estar en el mismo directorio.

---

## Tabla de símbolos

La tabla de símbolos está implementada en la clase `Symtab` con soporte de **alcance léxico anidado**.

### Estructura

Cada instancia de `Symtab` representa un alcance (scope) e incluye:

- `entries`: diccionario `nombre → Symbol` con los símbolos declarados localmente.
- `parent`: referencia al scope padre, lo que forma una cadena de alcances.
- `_is_loop`: bandera que indica si el scope pertenece a un bucle (`for`/`while`).
- `_func_return`: tipo de retorno esperado para el scope de función activo.

### Símbolo (`Symbol`)

Cada entrada almacena:

| Campo  | Descripción                                              |
|--------|----------------------------------------------------------|
| `name` | Nombre del identificador                                 |
| `kind` | Categoría: `variable`, `const`, `function`, `param`, `array` |
| `type_`| Tipo interno (`IntType`, `FuncTypeT`, `ArrayTypeT`, etc.) |
| `node` | Nodo AST original                                        |

### Operaciones principales

- `add(name, symbol)` — inserta un símbolo; lanza `SymbolDefinedError` si ya existe en el scope actual.
- `get(name)` — busca el símbolo en el scope actual y recursivamente en los padres.
- `get_local(name)` — busca solo en el scope actual (sin subir).
- `in_loop()` — sube la cadena de scopes hasta encontrar uno marcado como bucle.
- `expected_return()` — sube la cadena hasta encontrar el tipo de retorno de la función contenedora.

### Scopes creados

| Situación          | Scope nuevo           |
|--------------------|-----------------------|
| Programa           | `global`              |
| Cuerpo de función  | nombre de la función  |
| Bloque `{}`        | `block`               |
| Bucle `while`      | `while`               |
| Bucle `for`        | `for`                 |

---

## Visitor con multimethod

El checker implementa el patrón **Visitor** usando la librería [`multimethod`](https://pypi.org/project/multimethod/), que permite despacho múltiple por tipo en Python.

### Cómo funciona

En lugar de un único método con `isinstance` o de sobreescribir `visit` en cada nodo del AST, se declaran múltiples versiones del método `visit` anotadas con los tipos concretos:

```python
from multimethod import multimethod

class Checker:

    @multimethod
    def visit(self, node: Program, env: Symtab):
        ...

    @multimethod
    def visit(self, node: VarDeclaration, env: Symtab):
        ...

    @multimethod
    def visit(self, node: BinaryExpr, env: Symtab):
        ...
```

`multimethod` selecciona en tiempo de ejecución la implementación correcta según el tipo real del primer argumento (`node`). Esto evita grandes cadenas de `if/elif` y mantiene cada regla semántica aislada en su propio método.

### Fallback genérico

Se incluye un visitor de último recurso para nodos sin visitor específico:

```python
@multimethod
def visit(self, node: Node, env: Symtab):
    for val in node.__dict__.values():
        if isinstance(val, Node):
            self.visit(val, env)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, Node):
                    self.visit(item, env)
    return ErrorType()
```

Esto garantiza que el recorrido del AST nunca falle silenciosamente aunque un nodo no tenga chequeo semántico propio.

---

## Tipos soportados

### Tipos primitivos

| Tipo interno  | Palabra clave en B++ |
|---------------|----------------------|
| `IntType`     | `integer`            |
| `FloatType`   | `float`              |
| `BoolType`    | `boolean`            |
| `CharType`    | `char`               |
| `StringType`  | `string`             |
| `VoidType`    | `void`               |

### Tipos compuestos

- **`ArrayTypeT(element_type, size)`** — array homogéneo de cualquier tipo primitivo. Dos arrays son compatibles si tienen el mismo `element_type`, independientemente del tamaño.
- **`FuncTypeT(return_type, param_types)`** — tipo de función, con tipo de retorno y lista de tipos de parámetros.

### Tipo centinela

- **`ErrorType`** — se propaga cuando ya se reportó un error, evitando errores en cascada (si un subárbol falla, el error no se duplica en sus padres).

### Compatibilidad de tipos

La compatibilidad es estricta salvo una excepción:

- `integer` es compatible con `float` (promoción numérica implícita).
- Todos los demás tipos deben coincidir exactamente.

---

## Chequeos semánticos implementados

### Declaraciones y alcance

- Redeclaración de un símbolo en el mismo scope.
- Uso de un identificador no declarado en ningún scope visible.
- Registra variables, constantes, arrays, funciones y parámetros en la tabla de símbolos.

### Tipos en expresiones

- **Operadores binarios** (`+`, `-`, `*`, `/`, `%`, `^`, `<`, `<=`, `>`, `>=`, `&&`, `||`): verifica que los tipos de los operandos sean compatibles con el operador y calcula el tipo resultado.
- **Igualdad** (`==`, `!=`): requiere que ambos operandos sean del mismo tipo (no `void` ni `error`).
- **Operadores unarios** (`-`, `!`, `++`, `--`): verifica que el operando sea del tipo correcto.
- **Operadores compuestos** (`+=`, `-=`, `*=`, `/=`, `%=`): solo aplicables a tipos numéricos (`integer`, `float`).

### Asignaciones

- El tipo del valor asignado debe ser compatible con el tipo de la variable destino.
- Soporta lvalues simples (`x = ...`) e indexados (`a[i] = ...`).

### Llamadas a función

- El símbolo llamado debe existir y ser de tipo función.
- Número de argumentos debe coincidir con la declaración.
- Cada argumento se chequea contra el tipo del parámetro correspondiente.

### Acceso a arrays

- El símbolo accedido debe ser de tipo array.
- El índice debe ser de tipo `integer`.

### Sentencias de control

- La condición de `if`, `while` y `for` debe ser de tipo `boolean`.
- `break` y `continue` solo son válidos dentro de un bucle `for` o `while`.

### Funciones

- Una función no-`void` que no tiene `return` en su nivel superior genera un error.
- Un `return` con valor en una función `void` genera error.
- Un `return` vacío en una función no-`void` genera error.

### Programa

- Se verifica que exista una función `main` declarada en el scope global.

---

## Aspectos pendientes

Los siguientes aspectos no fueron implementados en esta versión del checker:

- **Tipos de usuario / clases**: el nodo `ClassDeclaration` y los tipos `UserType` no tienen visitor semántico; no se valida herencia ni acceso a miembros con `.`.
- **`this` y `super`**: no se resuelve su tipo dentro de métodos de clase.
- **Verificación de `main`**: solo comprueba que exista el nombre, no valida su firma (parámetros ni tipo de retorno).
- **Retorno en todas las ramas**: se comprueba si hay al menos un `return` en el nivel superior del cuerpo, pero no se hace análisis de flujo completo para garantizar que todos los caminos de ejecución retornan un valor.
- **Constantes**: `ConstDeclaration` es declarada en la tabla de símbolos pero no se impide su reasignación posterior.
- **Sobrecarga de funciones**: no está soportada; dos funciones con el mismo nombre en el mismo scope son un error incluso si tienen distinta firma.
- **Inferencia de tipos**: los tipos deben declararse explícitamente; no hay inferencia automática.
