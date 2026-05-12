# Entregables: optimizacion de IR `-O1` y `-O2`

## Archivos entregados

- `iroptimizer.py`: optimizador completo con CLI.
- `tests_ir/o1_optimizacion.bminor`: programa de prueba para `-O1`.
- `tests_ir/o2_temporales_muertos.bminor`: programa de prueba para `-O2`.
- `test_iroptimizer.py`: pruebas unitarias sobre listas de instrucciones IR.

## Uso

```bash
python iroptimizer.py tests_ir/o1_optimizacion.bminor -O0
python iroptimizer.py tests_ir/o1_optimizacion.bminor -O1
python iroptimizer.py tests_ir/o2_temporales_muertos.bminor -O2
python iroptimizer.py tests_ir/o2_temporales_muertos.bminor --compare
python -m unittest test_iroptimizer
```

Tambien se aceptan estas variantes:

```bash
python iroptimizer.py archivo.bminor -O 2
python iroptimizer.py archivo.bminor 2
```

## Optimizaciones implementadas

`-O0` conserva el IR original generado por `IRCodeGen`.

`-O1` implementa:

- constant folding para `ADDI`, `SUBI`, `MULI`, `DIVI`, `ADDF`, `SUBF`, `MULF`, `DIVF`, `AND`, `OR`, `XOR`, `CMPI`, `CMPF`, `CMPB`, `CMPS`;
- simplificacion algebraica local cuando el resultado puede materializarse como constante;
- preservacion de divisiones por cero sin optimizar;
- conversion de `CBRANCH` constante en `BRANCH`;
- eliminacion de instrucciones inalcanzables despues de `BRANCH` o `RET` hasta el siguiente `LABEL`;
- eliminacion de `BRANCH` al `LABEL` inmediatamente siguiente.

`-O2` ejecuta primero todo `-O1` y agrega:

- separacion conceptual en bloques basicos;
- analisis hacia atras por bloque;
- eliminacion conservadora de definiciones puras de temporales no usados;
- preservacion de instrucciones con efectos laterales como `STORE`, `PRINT`, `CALL`, `BRANCH`, `CBRANCH`, `RET`, `LABEL` y `DATAS`.

## Comparacion textual

Programa usado: `tests_ir/o2_temporales_muertos.bminor`.

### IR original (`-O0`)

```text
function main() -> void
  ALLOCI x
  MOVI 10, R1
  STOREI R1, x
  MOVI 2, R2
  MOVI 3, R3
  MOVI 4, R4
  MULI R3, R4, R5
  ADDI R2, R5, R6
  LOADI x, R7
  PRINTI R7
  RET
```

### IR con `-O1`

```text
function main() -> void
  ALLOCI x
  MOVI 10, R1
  STOREI R1, x
  MOVI 2, R2
  MOVI 3, R3
  MOVI 4, R4
  MOVI 12, R5
  MOVI 14, R6
  LOADI x, R7
  PRINTI R7
  RET
```

### IR con `-O2`

```text
function main() -> void
  ALLOCI x
  MOVI 10, R1
  STOREI R1, x
  LOADI x, R7
  PRINTI R7
  RET
```

En esta comparacion, `-O1` pliega `3 * 4` y luego `2 + 12`. `-O2` elimina los temporales de esa expresion completa porque el resultado no se usa y las instrucciones no tienen efectos laterales.

## Evidencia adicional para `-O1`

Programa usado: `tests_ir/o1_optimizacion.bminor`.

Fragmento relevante del IR original:

```text
  MOVI 1, R6
  MOVI 2, R7
  CMPI <, R6, R7, R8
  CBRANCH R8, IF_THEN1, IF_ELSE2
  LABEL IF_THEN1
```

Fragmento relevante con `-O1`:

```text
  MOVI 1, R6
  MOVI 2, R7
  MOVI 1, R8
  LABEL IF_THEN1
```

La comparacion constante `1 < 2` se reemplaza por `MOVI 1, R8`, el `CBRANCH` se convierte en `BRANCH IF_THEN1` y luego ese salto se elimina porque cae directamente al `LABEL IF_THEN1`. El codigo posterior a `return;` tambien se elimina como inalcanzable.
